"""Unit tests for DtekClient — all HTTP calls are mocked."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import copy
import datetime
import pytest

from dtek_client import DtekClient
from dtek_client.exceptions import (
    DtekAPIError,
    DtekConnectionError,
    DtekDataError,
    DtekNotFoundError,
    DtekRateLimitError,
    DtekServerError,
    DtekSiteError,
    DtekUnauthorizedError,
)
from dtek_client.models import AddressResult, HomeNumResponse, SlotStatus
from tests.conftest import make_mock_response


# ── Constructor ───────────────────────────────────────────────────────────────


class TestConstructor:
    def test_valid_site_key(self) -> None:
        client = DtekClient("kem")
        assert client.site_key == "kem"

    def test_invalid_site_key_raises(self) -> None:
        with pytest.raises(DtekSiteError):
            DtekClient("invalid_key_xyz")

    def test_custom_ajax_url(self) -> None:
        client = DtekClient("kem", ajax_url="https://custom.example.com/ajax")
        assert client.ajax_url == "https://custom.example.com/ajax"

    def test_base_url_matches_site(self) -> None:
        client = DtekClient("kem")
        assert "dtek-kem.com.ua" in client.base_url

    def test_all_valid_site_keys(self) -> None:
        for key in ("kem", "krem", "dnem", "dem", "oem", "zem"):
            client = DtekClient(key)
            assert client.site_key == key

    def test_owns_session_true_when_no_session_injected(self) -> None:
        client = DtekClient("kem")
        assert client._owns_session is True

    def test_owns_session_false_when_session_injected(self, mock_session: MagicMock) -> None:
        client = DtekClient("kem", session=mock_session)
        assert client._owns_session is False


# ── ajaxUrl discovery ─────────────────────────────────────────────────────────


class TestAjaxUrlDiscovery:
    async def test_extracts_meta_tag(self, mock_session: MagicMock) -> None:
        """Discovers ajaxUrl from <meta name="ajaxUrl" content="...">."""
        html = (
            "<html><head>"
            '<meta name="ajaxUrl" content="https://www.dtek-kem.com.ua/ua/ajax">'
            "</head></html>"
        )
        mock_session.get = AsyncMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"

    async def test_extracts_meta_reversed_attrs(self, mock_session: MagicMock) -> None:
        """content attr before name attr should still work."""
        html = '<meta content="https://example.com/ajax" name="ajaxUrl">'
        mock_session.get = AsyncMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://example.com/ajax"

    async def test_resolves_relative_ajax_url(self, mock_session: MagicMock) -> None:
        """A relative path in the meta tag is resolved against base_url."""
        html = '<meta name="ajaxUrl" content="/ua/ajax">'
        mock_session.get = AsyncMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"

    async def test_meta_not_found_uses_fallback(self, mock_session: MagicMock) -> None:
        """When no meta tag is found, the client falls back to base_url + /ua/ajax."""
        html = "<html><body>No meta here</body></html>"
        mock_session.get = AsyncMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        # Fallback URL = base_url + /ua/ajax
        assert "/ua/ajax" in url

    async def test_ajax_url_cached(self, mock_session: MagicMock) -> None:
        """Second call must NOT make a second HTTP request."""
        html = '<meta name="ajaxUrl" content="https://example.com/ajax">'
        mock_session.get = AsyncMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session)
        await client._get_ajax_url()
        await client._get_ajax_url()
        # Only one GET for discovery (no WAF warmup since session is injected).
        assert mock_session.get.call_count == 1

    async def test_no_session_raises(self) -> None:
        """Calling _get_ajax_url() without a session raises DtekConnectionError."""
        client = DtekClient("kem", ajax_url=None)
        with pytest.raises(DtekConnectionError):
            await client._get_ajax_url()

    async def test_extracts_js_var_pattern(self, mock_session: MagicMock) -> None:
        """Discovers ajaxUrl from a JS variable: var ajaxUrl = "..."."""
        html = '<script>var ajaxUrl = "https://example.com/wp-admin/admin-ajax.php";</script>'
        mock_session.get = AsyncMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://example.com/wp-admin/admin-ajax.php"


# ── _build_form ────────────────────────────────────────────────────────────────


class TestBuildForm:
    def test_simple(self) -> None:
        form = DtekClient._build_form("getStreets", [("city", "м. Українка")])
        assert form["method"] == "getStreets"
        assert form["data[0][name]"] == "city"
        assert form["data[0][value]"] == "м. Українка"

    def test_with_update_fact(self) -> None:
        form = DtekClient._build_form(
            "getHomeNum",
            [("city", "м. Київ"), ("street", "вул. Хрещатик")],
            update_fact="26.03.2026 14:00",
        )
        assert form["data[2][name]"] == "updateFact"
        assert form["data[2][value]"] == "26.03.2026 14:00"

    def test_multiple_fields_indexed(self) -> None:
        form = DtekClient._build_form(
            "getHomeNum",
            [("city", "A"), ("street", "B")],
        )
        assert form["data[0][name]"] == "city"
        assert form["data[1][name]"] == "street"
        assert "data[2][name]" not in form

    def test_no_fields(self) -> None:
        """Form with no fields should only contain method."""
        form = DtekClient._build_form("getStreets", [])
        assert form == {"method": "getStreets"}


# ── _handle_response ──────────────────────────────────────────────────────────
# NOTE: _handle_response is a synchronous method (no await needed).


class TestHandleResponse:
    def _mock_resp(
        self, status_code: int, headers: dict | None = None, json_data: Any = None
    ) -> MagicMock:
        return make_mock_response(
            status_code=status_code, headers=headers or {}, json_data=json_data
        )

    def test_401_raises_unauthorized(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekUnauthorizedError):
            client_with_ajax._handle_response(self._mock_resp(401), "/test")

    def test_404_raises_not_found(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekNotFoundError):
            client_with_ajax._handle_response(self._mock_resp(404), "/test")

    def test_429_no_header(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekRateLimitError) as ei:
            client_with_ajax._handle_response(self._mock_resp(429), "/test")
        assert ei.value.retry_after is None

    def test_429_with_header(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekRateLimitError) as ei:
            client_with_ajax._handle_response(
                self._mock_resp(429, headers={"Retry-After": "30"}), "/test"
            )
        assert ei.value.retry_after == 30.0

    def test_500_raises_server_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekServerError):
            client_with_ajax._handle_response(self._mock_resp(500), "/test")

    def test_503_raises_server_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekServerError) as ei:
            client_with_ajax._handle_response(self._mock_resp(503), "/test")
        assert ei.value.status_code == 503

    def test_400_raises_api_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekAPIError):
            client_with_ajax._handle_response(self._mock_resp(400), "/test")

    def test_200_returns_json(self, client_with_ajax: DtekClient) -> None:
        resp = self._mock_resp(200, json_data={"result": True, "data": {}})
        result = client_with_ajax._handle_response(resp, "/test")
        assert result == {"result": True, "data": {}}

    def test_200_bad_json_raises_data_error(self, client_with_ajax: DtekClient) -> None:
        resp = self._mock_resp(200)
        resp.json = MagicMock(side_effect=ValueError("not json"))
        with pytest.raises(DtekDataError):
            client_with_ajax._handle_response(resp, "/test")

    def test_result_false_raises_data_error(self, client_with_ajax: DtekClient) -> None:
        resp = self._mock_resp(200, json_data={"result": False})
        with pytest.raises(DtekDataError):
            client_with_ajax._handle_response(resp, "/test")


# ── get_streets ────────────────────────────────────────────────────────────────


class TestGetStreets:
    async def test_success_dict_format(
        self, client_with_ajax: DtekClient, streets_raw: dict
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=streets_raw)  # type: ignore[method-assign]
        streets = await client_with_ajax.get_streets("м. Українка")
        assert len(streets) > 0
        assert all(isinstance(s.name, str) and len(s.name) > 0 for s in streets)

    async def test_success_list_format(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(
            return_value={  # type: ignore[method-assign]
                "result": True,
                "data": ["вул. А", "вул. Б"],
            }
        )
        streets = await client_with_ajax.get_streets("м. Тест")
        assert len(streets) == 2

    async def test_non_dict_raises_data_error(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(return_value="not a dict")  # type: ignore[method-assign]
        with pytest.raises(DtekDataError):
            await client_with_ajax.get_streets("м. Тест")

    async def test_empty_data_returns_empty_list(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(return_value={"result": True, "data": {}})  # type: ignore[method-assign]
        streets = await client_with_ajax.get_streets("м. Тест")
        assert streets == []

    async def test_city_not_found_returns_empty(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(
            return_value={  # type: ignore[method-assign]
                "streets": {"м. Інше": ["вул. Центральна"]},
            }
        )
        streets = await client_with_ajax.get_streets("м. Невідоме")
        assert streets == []


# ── get_home_num ──────────────────────────────────────────────────────────────


class TestGetHomeNum:
    async def test_success(self, client_with_ajax: DtekClient, home_num_raw: dict) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert isinstance(result, HomeNumResponse)
        assert "1" in result.houses

    async def test_non_dict_raises(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(return_value=[1, 2, 3])  # type: ignore[method-assign]
        with pytest.raises(DtekDataError):
            await client_with_ajax.get_home_num("м. Тест", "вул. Тест")

    async def test_preset_parsed(self, client_with_ajax: DtekClient, home_num_raw: dict) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert result.preset is not None
        assert "GPV3.1" in result.preset.groups

    async def test_fact_parsed(self, client_with_ajax: DtekClient, home_num_raw: dict) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert result.fact is not None
        assert result.fact.today_ts == 1774483200


# ── get_group_by_address ──────────────────────────────────────────────────────


class TestGetGroupByAddress:
    async def test_success(self, client_with_ajax: DtekClient, home_num_raw: dict) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_group_by_address("м. Українка", "вул. Юності", "1")
        assert isinstance(result, AddressResult)
        assert result.group_id == "GPV3.1"
        assert result.house_number == "1"

    async def test_house_not_found_raises(
        self, client_with_ajax: DtekClient, home_num_raw: dict
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        with pytest.raises(DtekNotFoundError):
            await client_with_ajax.get_group_by_address("м. Українка", "вул. Юності", "999")

    async def test_group_display_name_populated(
        self, client_with_ajax: DtekClient, home_num_raw: dict
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_group_by_address("м. Українка", "вул. Юності", "1")
        assert isinstance(result.group_display_name, str)
        assert len(result.group_display_name) > 0

    async def test_result_contains_site_and_address(
        self, client_with_ajax: DtekClient, home_num_raw: dict
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_group_by_address("м. Українка", "вул. Юності", "2")
        assert result.site_key == "kem"
        assert result.city == "м. Українка"
        assert result.street == "вул. Юності"
        assert result.group_id == "GPV3.2"


# ── get_today_schedule ────────────────────────────────────────────────────────


class TestGetTodaySchedule:
    async def test_returns_slot_map(self, client_with_ajax: DtekClient, home_num_raw: dict) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        slots = await client_with_ajax.get_today_schedule("м. Українка", "вул. Юності", "1")
        assert slots is not None
        assert slots["1"] is SlotStatus.NO

    async def test_house_not_found_returns_none(
        self, client_with_ajax: DtekClient, home_num_raw: dict
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_today_schedule("м. Українка", "вул. Юності", "999")
        assert result is None

    async def test_no_fact_returns_none(self, client_with_ajax: DtekClient) -> None:
        raw: dict[str, Any] = {
            "result": True,
            "data": {
                "1": {
                    "sub_type_reason": ["GPV3.1"],
                    "sub_type": "",
                    "start_date": "",
                    "end_date": "",
                    "type": "",
                    "voluntarily": None,
                }
            },
            "showCurSchedule": False,
            "showTablePlan": False,
            "showTableFact": False,
            "showTableSchedule": False,
        }
        client_with_ajax._post = AsyncMock(return_value=raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_today_schedule("м. Українка", "вул. Юності", "1")
        assert result is None

    async def test_slot_values_are_slot_status(
        self, client_with_ajax: DtekClient, home_num_raw: dict
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        slots = await client_with_ajax.get_today_schedule("м. Українка", "вул. Юності", "1")
        assert slots is not None
        for v in slots.values():
            assert isinstance(v, SlotStatus)


# ── Session lifecycle ─────────────────────────────────────────────────────────


class TestSessionLifecycle:
    async def test_no_session_raises_on_post(self) -> None:
        """_post() without a session raises DtekConnectionError."""
        client = DtekClient("kem", ajax_url="https://example.com/ajax")
        with pytest.raises(DtekConnectionError):
            await client._post({"method": "test"})

    async def test_close_injected_session_is_noop(self, mock_session: MagicMock) -> None:
        """close() must NOT close an externally injected session."""
        client = DtekClient("kem", session=mock_session)
        await client.close()
        mock_session.close.assert_not_called()

    async def test_context_manager_opens_and_closes_own_session(self) -> None:
        """Context manager creates a session on enter and closes it on exit."""
        mock_sess = MagicMock()
        mock_sess.close = AsyncMock()
        # Warm-up GET during connect().
        mock_sess.get = AsyncMock(return_value=make_mock_response(status_code=200, text=""))

        with patch("dtek_client.client.AsyncSession", return_value=mock_sess):
            async with DtekClient("kem", ajax_url="https://x.com/ajax") as client:
                assert client._session is mock_sess

        mock_sess.close.assert_called_once()


# ── connect() warm-up GET ─────────────────────────────────────────────────────


class TestConnectWarmUp:
    async def test_warmup_failure_does_not_propagate(self) -> None:
        """connect() swallows any exception from the initial warm-up GET request
        so that a flaky WAF challenge page never prevents the client from starting."""
        mock_sess = MagicMock()
        mock_sess.get = AsyncMock(side_effect=Exception("warmup blocked by WAF"))
        mock_sess.close = AsyncMock()

        with patch("dtek_client.client.AsyncSession", return_value=mock_sess):
            client = DtekClient("kem", ajax_url="https://x.com/ajax")
            await client.connect()  # must not raise

        assert client._session is mock_sess


# ── _fetch_page_html() ────────────────────────────────────────────────────────


class TestFetchPageHtml:
    async def test_404_returns_none(self, mock_session: MagicMock) -> None:
        """A 404 response is treated as 'path not found' and returns None
        so the caller can try the next fallback path."""
        mock_session.get = AsyncMock(return_value=make_mock_response(status_code=404))
        client = DtekClient("kem", session=mock_session)
        assert await client._fetch_page_html("/ua/shutdowns") is None

    async def test_5xx_raises_server_error(self, mock_session: MagicMock) -> None:
        """A 5xx response from the schedule page is a hard failure —
        raise DtekServerError immediately rather than silently ignoring it."""
        mock_session.get = AsyncMock(return_value=make_mock_response(status_code=503))
        client = DtekClient("kem", session=mock_session)
        with pytest.raises(DtekServerError) as ei:
            await client._fetch_page_html("/ua/shutdowns")
        assert ei.value.status_code == 503

    async def test_network_error_raises_connection_error(self, mock_session: MagicMock) -> None:
        """A curl_cffi RequestsError (e.g. DNS failure, connection refused)
        is wrapped in DtekConnectionError with the original message preserved."""
        from curl_cffi.requests.errors import RequestsError

        mock_session.get = AsyncMock(side_effect=RequestsError("connection refused"))
        client = DtekClient("kem", session=mock_session)
        with pytest.raises(DtekConnectionError):
            await client._fetch_page_html("/ua/shutdowns")

    async def test_incapsula_waf_page_returns_none(self, mock_session: MagicMock) -> None:
        """When the schedule page is an Incapsula/Imperva JS challenge (recognisable
        by the _Incapsula_Resource marker), it is treated like a missing page so
        the client falls through to the next discovery path."""
        waf_html = "<html><body>" "var _Incapsula_Resource = {};" "</body></html>"
        mock_session.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text=waf_html)
        )
        client = DtekClient("kem", session=mock_session)
        assert await client._fetch_page_html("/ua/shutdowns") is None

    async def test_visid_incap_marker_also_triggers_waf_detection(
        self, mock_session: MagicMock
    ) -> None:
        """The visid_incap cookie marker is another signal that the page is a
        WAF challenge rather than real schedule content."""
        waf_html = "<script>document.cookie='visid_incap_123=abc';</script>"
        mock_session.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text=waf_html)
        )
        client = DtekClient("kem", session=mock_session)
        assert await client._fetch_page_html("/ua/shutdowns") is None


# ── _get_ajax_url() — fallback path iteration ─────────────────────────────────


class TestAjaxUrlFallbackIteration:
    async def test_skips_404_path_and_uses_next(self, mock_session: MagicMock) -> None:
        """When the primary schedule path returns 404, the client moves on to
        the next fallback path and extracts the ajaxUrl from there."""
        good_html = '<meta name="ajaxUrl" content="https://www.dtek-kem.com.ua/ua/ajax">'
        mock_session.get = AsyncMock(
            side_effect=[
                make_mock_response(status_code=404),  # primary → skip
                make_mock_response(status_code=200, text=good_html),  # fallback → found
            ]
        )
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"


# ── _post() — retry logic ─────────────────────────────────────────────────────


class TestPostRetry:
    async def test_retries_on_server_error_then_succeeds(self, mock_session: MagicMock) -> None:
        """On a 5xx response the client sleeps and retries; a successful response
        on the next attempt is returned normally."""
        mock_session.post = AsyncMock(
            side_effect=[
                make_mock_response(status_code=500),
                make_mock_response(status_code=200, json_data={"result": True, "data": {}}),
            ]
        )
        client = DtekClient(
            "kem",
            ajax_url="https://x.com/ajax",
            session=mock_session,
            retry_attempts=2,
            retry_delay=0.0,
        )
        with patch("dtek_client.client.asyncio.sleep", new=AsyncMock()):
            result = await client._post({"method": "test"})
        assert result["result"] is True

    async def test_all_retries_exhausted_raises_last_server_error(
        self, mock_session: MagicMock
    ) -> None:
        """When every retry attempt ends with a 5xx error, the last
        DtekServerError is re-raised so the caller knows the request failed."""
        mock_session.post = AsyncMock(return_value=make_mock_response(status_code=503))
        client = DtekClient(
            "kem",
            ajax_url="https://x.com/ajax",
            session=mock_session,
            retry_attempts=2,
            retry_delay=0.0,
        )
        with patch("dtek_client.client.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(DtekServerError):
                await client._post({"method": "test"})

    async def test_unauthorized_is_not_retried(self, client_with_ajax: DtekClient) -> None:
        """401 responses are not transient — re-raise immediately without retry."""
        client_with_ajax._session.post = AsyncMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=401)
        )
        with pytest.raises(DtekUnauthorizedError):
            await client_with_ajax._post({"method": "test"})

    async def test_rate_limit_is_not_retried(self, client_with_ajax: DtekClient) -> None:
        """429 responses are not retried — the caller should honour Retry-After."""
        client_with_ajax._session.post = AsyncMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=429)
        )
        with pytest.raises(DtekRateLimitError):
            await client_with_ajax._post({"method": "test"})

    async def test_not_found_is_not_retried(self, client_with_ajax: DtekClient) -> None:
        """404 from the AJAX endpoint means the resource genuinely does not exist
        and should not be retried."""
        client_with_ajax._session.post = AsyncMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=404)
        )
        with pytest.raises(DtekNotFoundError):
            await client_with_ajax._post({"method": "test"})


# ── _handle_response() — Retry-After edge case ────────────────────────────────


class TestHandleResponseRetryAfterHeader:
    def test_non_numeric_retry_after_is_treated_as_none(self, client_with_ajax: DtekClient) -> None:
        """When Retry-After contains an HTTP-date string rather than a number
        of seconds, parsing fails gracefully and retry_after is left as None."""
        resp = make_mock_response(
            status_code=429,
            headers={"Retry-After": "Mon, 29 Mar 2026 12:00:00 GMT"},
        )
        with pytest.raises(DtekRateLimitError) as ei:
            client_with_ajax._handle_response(resp, "/test")
        assert ei.value.retry_after is None


# ── get_streets() — edge cases ────────────────────────────────────────────────


class TestGetStreetsEdgeCases:
    async def test_case_insensitive_city_lookup(self, client_with_ajax: DtekClient) -> None:
        """City keys in the AJAX response may use different capitalisation than
        the user's query; the client falls back to a case-insensitive comparison."""
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": {"м. Українка": ["вул. Юності", "вул. Садова"]}}
        )
        streets = await client_with_ajax.get_streets("м. Українка")
        assert len(streets) == 2

    async def test_city_value_not_a_list_returns_empty(self, client_with_ajax: DtekClient) -> None:
        """If the server sends a city entry whose value is not a list (malformed
        response), the method returns an empty list rather than crashing."""
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": {"м. Українка": {"nested": "unexpected"}}}
        )
        assert await client_with_ajax.get_streets("м. Українка") == []

    async def test_completely_unexpected_streets_type_returns_empty(
        self, client_with_ajax: DtekClient
    ) -> None:
        """If the streets value is neither dict nor list (e.g. a plain string),
        the method returns an empty list and logs a warning."""
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": "totally_wrong"}
        )
        assert await client_with_ajax.get_streets("м. Українка") == []

    async def test_case_insensitive_loop_body_is_executed(
        self, client_with_ajax: DtekClient
    ) -> None:
        """Checks the body of the case-insensitive loop (city_streets = v; break).

        The key in the response is 'm. Ukrainka' (lower case).
        The query is 'M. UKRAINE' (upper case).
        An exact match via .get() fails, so the loop executes;
        when k.lower() matches city.lower(), city_streets is assigned
        and break is called — these are the two lines that are covered."""
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": {"м. Українка": ["вул. Юності", "вул. Садова"]}}
        )
        streets = await client_with_ajax.get_streets("М. УКРАЇНКА")
        assert len(streets) == 2
        assert streets[0].name == "вул. Юності"


# ── get_home_num() — global schedule fallback ─────────────────────────────────


class TestGetHomeNumGlobalSchedule:
    """When the getHomeNum response contains no preset/fact, the client fetches
    them separately via checkDisconUpdate and merges the result."""

    def _raw_without_schedule(self) -> dict[str, Any]:
        return {
            "data": {
                "1": {
                    "sub_type_reason": ["GPV3.1"],
                    "sub_type": "",
                    "start_date": "",
                    "end_date": "",
                    "type": "",
                    "voluntarily": None,
                }
            },
            "showCurSchedule": False,
            "showTablePlan": False,
            "showTableFact": False,
            "showTableSchedule": False,
        }

    async def test_global_schedule_merged_when_present(
        self, client_with_ajax: DtekClient, home_num_raw: dict
    ) -> None:
        """preset and fact from the global schedule are injected into the result
        when the primary response omits them."""
        base = self._raw_without_schedule()
        global_sched = {"preset": home_num_raw["preset"], "fact": home_num_raw["fact"]}
        call_count = 0

        async def _side_effect(form: dict) -> dict:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            return base if call_count == 1 else global_sched

        client_with_ajax._post = _side_effect  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert result.preset is not None
        assert result.fact is not None

    async def test_global_schedule_fetch_failure_is_swallowed(
        self, client_with_ajax: DtekClient
    ) -> None:
        """A network error while fetching the global schedule is caught and logged;
        the partial result (without preset/fact) is still returned."""
        base = self._raw_without_schedule()
        call_count = 0

        async def _side_effect(form: dict) -> dict:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return base
            raise Exception("global schedule unavailable")

        client_with_ajax._post = _side_effect  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert isinstance(result, HomeNumResponse)
        assert result.preset is None

    async def test_empty_global_schedule_leaves_preset_absent(
        self, client_with_ajax: DtekClient
    ) -> None:
        """An empty global schedule response means there is genuinely no data
        to merge; preset and fact remain None."""
        base = self._raw_without_schedule()
        call_count = 0

        async def _side_effect(form: dict) -> dict:  # type: ignore[type-arg]
            nonlocal call_count
            call_count += 1
            return base if call_count == 1 else {}

        client_with_ajax._post = _side_effect  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert result.preset is None

    async def test_validation_error_raises_data_error(self, client_with_ajax: DtekClient) -> None:
        """When the AJAX response cannot be parsed into HomeNumResponse (e.g.
        preset is a string instead of an object), a DtekDataError is raised."""
        raw: dict[str, Any] = {
            "data": {},
            "preset": "not_an_object",
            "showCurSchedule": False,
            "showTablePlan": False,
            "showTableFact": False,
            "showTableSchedule": False,
        }
        client_with_ajax._post = AsyncMock(return_value=raw)  # type: ignore[method-assign]
        with pytest.raises(DtekDataError):
            await client_with_ajax.get_home_num("м. Українка", "вул. Юності")


# ── Fixtures for new-method tests ─────────────────────────────────────────────

# today_ts у fixtures/home_num_response.json = 1774483200
_TODAY_TS   = 1774483200
_TOMORROW_TS = _TODAY_TS + 86400


@pytest.fixture
def home_num_raw_with_tomorrow(home_num_raw: dict) -> dict:
    """home_num_raw з доданим tomorrow_ts у fact.data.

    Копіює слоти сьогодні під ключем tomorrow_ts, щоб get_tomorrow_schedule()
    і get_schedule_for_date(..., tomorrow) мали що повертати.
    """
    raw = copy.deepcopy(home_num_raw)
    today_slots = raw["fact"]["data"].get(str(_TODAY_TS), {})
    raw["fact"]["data"][str(_TOMORROW_TS)] = copy.deepcopy(today_slots)
    return raw


# ── get_tomorrow_schedule ─────────────────────────────────────────────────────


class TestGetTomorrowSchedule:
    async def test_returns_slot_map_when_tomorrow_in_fact(
        self,
        client_with_ajax: DtekClient,
        home_num_raw_with_tomorrow: dict,
    ) -> None:
        """Якщо tomorrow_ts є у fact.data — повертає dict зі SlotStatus."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        result = await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert result is not None
        assert isinstance(result, dict)

    async def test_returns_none_when_tomorrow_absent(
        self,
        client_with_ajax: DtekClient,
        home_num_raw: dict,
    ) -> None:
        """Якщо tomorrow_ts відсутній у fact.data — повертає None."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert result is None

    async def test_slot_values_are_slot_status(
        self,
        client_with_ajax: DtekClient,
        home_num_raw_with_tomorrow: dict,
    ) -> None:
        """Усі значення у поверненому словнику — SlotStatus."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        result = await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert result is not None
        for v in result.values():
            assert isinstance(v, SlotStatus)

    async def test_house_not_found_returns_none(
        self,
        client_with_ajax: DtekClient,
        home_num_raw_with_tomorrow: dict,
    ) -> None:
        """Неіснуючий будинок → None."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        result = await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "999")
        assert result is None

    async def test_no_fact_returns_none(self, client_with_ajax: DtekClient) -> None:
        """Якщо у відповіді взагалі немає fact — повертає None."""
        raw: dict[str, Any] = {
            "data": {
                "1": {
                    "sub_type_reason": ["GPV3.1"],
                    "sub_type": "",
                    "start_date": "",
                    "end_date": "",
                    "type": "",
                    "voluntarily": None,
                }
            },
            "showCurSchedule": False,
            "showTablePlan": False,
            "showTableFact": False,
            "showTableSchedule": False,
        }
        client_with_ajax._post = AsyncMock(return_value=raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert result is None

    async def test_tomorrow_uses_today_ts_plus_86400(
        self,
        client_with_ajax: DtekClient,
        home_num_raw_with_tomorrow: dict,
    ) -> None:
        """Метод шукає саме today_ts + 86400, а не будь-який інший ключ."""
        raw = copy.deepcopy(home_num_raw_with_tomorrow)
        # Видаляємо tomorrow_ts → метод повинен повернути None
        del raw["fact"]["data"][str(_TOMORROW_TS)]
        client_with_ajax._post = AsyncMock(return_value=raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert result is None


# ── get_schedule_for_date ─────────────────────────────────────────────────────


class TestGetScheduleForDate:
    _today    = datetime.date.fromtimestamp(_TODAY_TS)
    _tomorrow = datetime.date.fromtimestamp(_TOMORROW_TS)

    async def test_today_equals_get_today_schedule(
        self,
        client_with_ajax: DtekClient,
        home_num_raw: dict,
    ) -> None:
        """get_schedule_for_date(today) == get_today_schedule()."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        today_direct = await client_with_ajax.get_today_schedule(
            "м. Українка", "вул. Юності", "1"
        )
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        today_via_dt = await client_with_ajax.get_schedule_for_date(
            "м. Українка", "вул. Юності", "1", self._today
        )
        assert today_direct == today_via_dt

    async def test_tomorrow_equals_get_tomorrow_schedule(
        self,
        client_with_ajax: DtekClient,
        home_num_raw_with_tomorrow: dict,
    ) -> None:
        """get_schedule_for_date(tomorrow) == get_tomorrow_schedule()."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        via_tmrw = await client_with_ajax.get_tomorrow_schedule(
            "м. Українка", "вул. Юності", "1"
        )
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        via_date = await client_with_ajax.get_schedule_for_date(
            "м. Українка", "вул. Юності", "1", self._tomorrow
        )
        assert via_tmrw == via_date

    async def test_date_not_in_fact_returns_none(
        self,
        client_with_ajax: DtekClient,
        home_num_raw: dict,
    ) -> None:
        """Дата, якої немає в fact.data, повертає None."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        far_future = datetime.date(2099, 1, 1)
        result = await client_with_ajax.get_schedule_for_date(
            "м. Українка", "вул. Юності", "1", far_future
        )
        assert result is None

    async def test_slot_values_are_slot_status(
        self,
        client_with_ajax: DtekClient,
        home_num_raw: dict,
    ) -> None:
        """Усі значення повернутого словника — SlotStatus."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_schedule_for_date(
            "м. Українка", "вул. Юності", "1", self._today
        )
        if result is not None:
            for v in result.values():
                assert isinstance(v, SlotStatus)

    async def test_unknown_house_returns_none(
        self,
        client_with_ajax: DtekClient,
        home_num_raw: dict,
    ) -> None:
        """Неіснуючий будинок → None для будь-якої дати."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_schedule_for_date(
            "м. Українка", "вул. Юності", "999", self._today
        )
        assert result is None

    async def test_accepts_datetime_date_type(
        self,
        client_with_ajax: DtekClient,
        home_num_raw: dict,
    ) -> None:
        """Параметр date — саме datetime.date, не рядок і не int."""
        assert isinstance(self._today, datetime.date)
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_schedule_for_date(
            "м. Українка", "вул. Юності", "1", self._today
        )
        assert result is None or isinstance(result, dict)


# ── get_available_fact_dates ──────────────────────────────────────────────────


class TestGetAvailableFactDates:
    async def test_returns_list_of_dates(
        self, client_with_ajax: DtekClient, home_num_raw: dict
    ) -> None:
        """Повертає list[datetime.date]."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        response = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        dates = DtekClient.get_available_fact_dates(response)
        assert isinstance(dates, list)
        assert all(isinstance(d, datetime.date) for d in dates)

    async def test_today_present_in_dates(
        self, client_with_ajax: DtekClient, home_num_raw: dict
    ) -> None:
        """today_ts з fact повинен бути серед повернених дат."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        response = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        today = datetime.date.fromtimestamp(_TODAY_TS)
        dates = DtekClient.get_available_fact_dates(response)
        assert today in dates

    async def test_dates_sorted_ascending(
        self, client_with_ajax: DtekClient, home_num_raw_with_tomorrow: dict
    ) -> None:
        """Список відсортований від найранішої до найпізнішої."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        response = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        dates = DtekClient.get_available_fact_dates(response)
        assert dates == sorted(dates)

    async def test_tomorrow_present_when_in_fact(
        self, client_with_ajax: DtekClient, home_num_raw_with_tomorrow: dict
    ) -> None:
        """Якщо tomorrow_ts є у fact.data — він відображається у результаті."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        response = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        tomorrow = datetime.date.fromtimestamp(_TOMORROW_TS)
        dates = DtekClient.get_available_fact_dates(response)
        assert tomorrow in dates

    async def test_count_matches_fact_days(
        self, client_with_ajax: DtekClient, home_num_raw_with_tomorrow: dict
    ) -> None:
        """len(dates) == len(fact.days)."""
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        response = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        dates = DtekClient.get_available_fact_dates(response)
        assert len(dates) == len(response.fact.days)

    async def test_no_fact_returns_empty_list(
        self, client_with_ajax: DtekClient
    ) -> None:
        """Якщо fact=None — повертає [], без винятку."""
        response = HomeNumResponse.model_construct(
            houses={},
            preset=None,
            fact=None,
            show_cur_schedule=False,
            show_table_plan=False,
            show_table_fact=False,
            show_table_schedule=False,
            update_timestamp="",
        )
        result = DtekClient.get_available_fact_dates(response)
        assert result == []