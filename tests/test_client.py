"""Behavioral unit tests for DtekClient."""

from __future__ import annotations

import base64
import copy
import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import aiohttp
import pytest

from dtek_client import DtekClient, extract_csrf_token, mask_csrf_token
from dtek_client.const import DEFAULT_TIMEZONE, FORCE_UPDATE_FACT
from dtek_client.exceptions import (
    DtekAPIError,
    DtekBlockedError,
    DtekConnectionError,
    DtekDataError,
    DtekNotFoundError,
    DtekRateLimitError,
    DtekServerError,
    DtekSiteError,
    DtekSSLError,
    DtekTimeoutError,
    DtekUnauthorizedError,
)
from dtek_client.models import AddressResult, HomeNumResponse, SlotStatus
from tests.conftest import SAMPLE_CSRF_COOKIE, SAMPLE_RAW_CSRF, make_mock_response

_TODAY_TS = 1774483200
_TOMORROW_TS = _TODAY_TS + 86400


@pytest.fixture
def home_num_raw_with_tomorrow(home_num_raw: dict[str, Any]) -> dict[str, Any]:
    raw = copy.deepcopy(home_num_raw)
    today_slots = raw["fact"]["data"].get(str(_TODAY_TS), {})
    raw["fact"]["data"][str(_TOMORROW_TS)] = copy.deepcopy(today_slots)
    return raw


class TestConstructor:
    def test_valid_site_key(self) -> None:
        client = DtekClient("kem")
        assert client.site_key == "kem"

    def test_invalid_site_key_raises(self) -> None:
        with pytest.raises(DtekSiteError):
            DtekClient("invalid_key_xyz")

    def test_removed_zem_site_key_raises(self) -> None:
        with pytest.raises(DtekSiteError):
            DtekClient("zem")

    def test_custom_ajax_url(self) -> None:
        client = DtekClient("kem", ajax_url="https://custom.example.com/ajax")
        assert client.ajax_url == "https://custom.example.com/ajax"

    def test_base_url_matches_site(self) -> None:
        client = DtekClient("kem")
        assert "dtek-kem.com.ua" in client.base_url

    def test_all_valid_site_keys(self) -> None:
        for key in ("kem", "krem", "dnem", "dem", "oem"):
            client = DtekClient(key)
            assert client.site_key == key


class TestYii2CsrfFunctions:
    def test_extracts_raw_token_from_signed_yii2_cookie(self) -> None:
        assert extract_csrf_token(SAMPLE_CSRF_COOKIE) == SAMPLE_RAW_CSRF

    def test_returns_none_for_invalid_cookie_value(self) -> None:
        assert extract_csrf_token("not-a-valid-yii2-cookie") is None

    def test_mask_csrf_token_produces_reversible_yii2_token(self) -> None:
        masked_b64 = mask_csrf_token(SAMPLE_RAW_CSRF)
        decoded = base64.urlsafe_b64decode(masked_b64.encode("ascii"))
        half = len(decoded) // 2
        mask, xored = decoded[:half], decoded[half:]
        unmasked = bytes(a ^ b for a, b in zip(mask, xored, strict=True)).decode("utf-8")
        assert unmasked == SAMPLE_RAW_CSRF

    def test_mask_csrf_token_deterministic_with_explicit_mask(self) -> None:
        raw = "abcd"
        mask = b"\x01\x02\x03\x04"
        masked = mask_csrf_token(raw, mask=mask)
        expected = base64.urlsafe_b64encode(
            mask + bytes(a ^ b for a, b in zip(mask, b"abcd", strict=True))
        ).decode("ascii")
        assert masked == expected


class TestCsrfBootstrapAndRefresh:
    async def test_bootstraps_csrf_cookie_on_first_request_when_jar_is_empty(
        self, streets_raw: dict[str, Any]
    ) -> None:
        session = MagicMock()
        session.closed = False
        session.cookie_jar = []

        bootstrap_resp = make_mock_response(
            status_code=400,
            text="Bad Request",
            cookies={"_csrf-dtek-krem": SAMPLE_CSRF_COOKIE},
        )
        data_resp = make_mock_response(status_code=200, json_data=streets_raw)
        session.post = MagicMock(side_effect=[bootstrap_resp, data_resp])

        client = DtekClient("krem", session=session)
        streets = await client.get_streets("м. Українка")

        assert len(streets) > 0
        assert session.post.call_count == 2
        second_call_headers = session.post.call_args_list[1].kwargs["headers"]
        assert "X-CSRF-Token" in second_call_headers

    async def test_refreshes_stale_csrf_token_on_http_400_and_succeeds(
        self, streets_raw: dict[str, Any]
    ) -> None:
        session = MagicMock()
        session.closed = False
        cookie_jar = MagicMock()
        cookie_jar.__iter__ = MagicMock(return_value=iter([]))
        session.cookie_jar = cookie_jar

        fresh_csrf = "NEW_CSRF_12345678901234567890123"
        fresh_cookie = SAMPLE_CSRF_COOKIE.replace(SAMPLE_RAW_CSRF, fresh_csrf)

        stale_resp = make_mock_response(
            status_code=400,
            text="CSRF validation failed",
            cookies={"_csrf-dtek-krem": fresh_cookie},
        )
        ok_resp = make_mock_response(status_code=200, json_data=streets_raw)
        session.post = MagicMock(side_effect=[stale_resp, ok_resp])

        client = DtekClient("krem", session=session, csrf_token="old_expired_csrf")  # noqa: S106
        streets = await client.get_streets("м. Українка")

        assert len(streets) > 0
        assert session.post.call_count == 2

    async def test_re_bootstraps_when_400_response_has_no_cookie(
        self, streets_raw: dict[str, Any]
    ) -> None:
        session = MagicMock()
        session.closed = False
        cookie_jar = MagicMock()
        cookie_jar.__iter__ = MagicMock(return_value=iter([]))
        session.cookie_jar = cookie_jar

        first_400 = make_mock_response(status_code=400, text="Bad Request")
        bootstrap_400 = make_mock_response(
            status_code=400,
            text="Bad Request",
            cookies={"_csrf-dtek-krem": SAMPLE_CSRF_COOKIE},
        )
        ok_resp = make_mock_response(status_code=200, json_data=streets_raw)
        session.post = MagicMock(side_effect=[first_400, bootstrap_400, ok_resp])

        client = DtekClient("krem", session=session, csrf_token="stale_csrf")  # noqa: S106
        streets = await client.get_streets("м. Українка")

        assert len(streets) > 0
        assert session.post.call_count == 3
        cookie_jar.clear.assert_called_once()

    async def test_persistent_400_raises_api_error(self) -> None:
        session = MagicMock()
        session.closed = False
        session.cookie_jar = []
        session.post = MagicMock(return_value=make_mock_response(status_code=400, text="Bad"))

        client = DtekClient("krem", session=session, csrf_token="csrf_val")  # noqa: S106
        with pytest.raises(DtekAPIError) as ei:
            await client.get_streets("м. Українка")
        assert ei.value.status_code == 400


class TestAjaxUrlDiscovery:
    async def test_defaults_to_fallback_path_without_html_get(
        self, mock_session: MagicMock
    ) -> None:
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"
        mock_session.get.assert_not_called()

    async def test_discovers_meta_tag_when_discover_enabled(self, mock_session: MagicMock) -> None:
        html = (
            "<html><head>"
            '<meta name="ajaxUrl" content="https://www.dtek-kem.com.ua/ua/ajax">'
            "</head></html>"
        )
        mock_session.get = MagicMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session, discover_ajax_url=True)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"

    async def test_extracts_meta_reversed_attrs(self, mock_session: MagicMock) -> None:
        html = '<meta content="https://example.com/ajax" name="ajaxUrl">'
        mock_session.get = MagicMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session, discover_ajax_url=True)
        url = await client._get_ajax_url()
        assert url == "https://example.com/ajax"

    async def test_resolves_relative_ajax_url(self, mock_session: MagicMock) -> None:
        html = '<meta name="ajaxUrl" content="/ua/ajax">'
        mock_session.get = MagicMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session, discover_ajax_url=True)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"

    async def test_meta_not_found_uses_fallback(self, mock_session: MagicMock) -> None:
        html = "<html><body>No meta here</body></html>"
        mock_session.get = MagicMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session, discover_ajax_url=True)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"

    async def test_ajax_url_cached(self, mock_session: MagicMock) -> None:
        html = '<meta name="ajaxUrl" content="https://example.com/ajax">'
        mock_session.get = MagicMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session, discover_ajax_url=True)
        await client._get_ajax_url()
        await client._get_ajax_url()
        assert mock_session.get.call_count == 1

    async def test_no_session_raises(self) -> None:
        client = DtekClient("kem", ajax_url=None)
        with pytest.raises(DtekConnectionError):
            await client._get_ajax_url()

    async def test_extracts_js_var_pattern(self, mock_session: MagicMock) -> None:
        html = '<script>var ajaxUrl = "https://example.com/custom-ajax";</script>'
        mock_session.get = MagicMock(return_value=make_mock_response(status_code=200, text=html))
        client = DtekClient("kem", session=mock_session, discover_ajax_url=True)
        url = await client._get_ajax_url()
        assert url == "https://example.com/custom-ajax"

    async def test_skips_404_path_and_uses_next(self, mock_session: MagicMock) -> None:
        good_html = '<meta name="ajaxUrl" content="https://www.dtek-kem.com.ua/ua/ajax">'
        mock_session.get = MagicMock(
            side_effect=[
                make_mock_response(status_code=404),
                make_mock_response(status_code=200, text=good_html),
            ]
        )
        client = DtekClient("kem", session=mock_session, discover_ajax_url=True)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"


class TestFetchPageHtml:
    async def test_404_returns_none(self, mock_session: MagicMock) -> None:
        mock_session.get = MagicMock(return_value=make_mock_response(status_code=404))
        client = DtekClient("kem", session=mock_session)
        assert await client._fetch_page_html("/ua/shutdowns") is None

    async def test_5xx_raises_server_error(self, mock_session: MagicMock) -> None:
        mock_session.get = MagicMock(return_value=make_mock_response(status_code=503))
        client = DtekClient("kem", session=mock_session)
        with pytest.raises(DtekServerError) as ei:
            await client._fetch_page_html("/ua/shutdowns")
        assert ei.value.status_code == 503

    async def test_timeout_raises_timeout_error(self, mock_session: MagicMock) -> None:
        mock_session.get = MagicMock(side_effect=TimeoutError("timed out"))
        client = DtekClient("kem", session=mock_session)
        with pytest.raises(DtekTimeoutError):
            await client._fetch_page_html("/ua/shutdowns")

    async def test_ssl_error_raises_ssl_error(self, mock_session: MagicMock) -> None:
        ssl_err = aiohttp.ClientSSLError(MagicMock(), OSError("bad cert"))
        mock_session.get = MagicMock(side_effect=ssl_err)
        client = DtekClient("kem", session=mock_session)
        with pytest.raises(DtekSSLError):
            await client._fetch_page_html("/ua/shutdowns")

    async def test_network_error_raises_connection_error(self, mock_session: MagicMock) -> None:
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("connection refused"))
        client = DtekClient("kem", session=mock_session)
        with pytest.raises(DtekConnectionError):
            await client._fetch_page_html("/ua/shutdowns")

    async def test_incapsula_waf_page_returns_none(self, mock_session: MagicMock) -> None:
        waf_html = "<html><body>var _Incapsula_Resource = {};</body></html>"
        mock_session.get = MagicMock(
            return_value=make_mock_response(status_code=200, text=waf_html)
        )
        client = DtekClient("kem", session=mock_session)
        assert await client._fetch_page_html("/ua/shutdowns") is None


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
        form = DtekClient._build_form("getStreets", [])
        assert form == {"method": "getStreets"}


class TestHandleResponse:
    def test_incapsula_challenge_raises_blocked_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekBlockedError):
            client_with_ajax._handle_response(
                200,
                "<html>_Incapsula_Resource</html>",
                {},
                "/ua/ajax",
            )

    def test_401_raises_unauthorized(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekUnauthorizedError):
            client_with_ajax._handle_response(401, "", {}, "/test")

    def test_404_raises_not_found(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekNotFoundError):
            client_with_ajax._handle_response(404, "", {}, "/test")

    def test_429_no_header(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekRateLimitError) as ei:
            client_with_ajax._handle_response(429, "", {}, "/test")
        assert ei.value.retry_after is None

    def test_429_with_header(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekRateLimitError) as ei:
            client_with_ajax._handle_response(429, "", {"Retry-After": "30"}, "/test")
        assert ei.value.retry_after == 30.0

    def test_non_numeric_retry_after_is_treated_as_none(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekRateLimitError) as ei:
            client_with_ajax._handle_response(
                429,
                "",
                {"Retry-After": "Mon, 29 Mar 2026 12:00:00 GMT"},
                "/test",
            )
        assert ei.value.retry_after is None

    def test_500_raises_server_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekServerError):
            client_with_ajax._handle_response(500, "", {}, "/test")

    def test_503_raises_server_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekServerError) as ei:
            client_with_ajax._handle_response(503, "", {}, "/test")
        assert ei.value.status_code == 503

    def test_400_raises_api_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekAPIError):
            client_with_ajax._handle_response(400, "", {}, "/test")

    def test_200_returns_json(self, client_with_ajax: DtekClient) -> None:
        result = client_with_ajax._handle_response(
            200,
            '{"result": true, "data": {}}',
            {},
            "/test",
        )
        assert result == {"result": True, "data": {}}

    def test_200_bad_json_raises_data_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekDataError):
            client_with_ajax._handle_response(200, "not-json", {}, "/test")

    def test_result_false_raises_data_error(self, client_with_ajax: DtekClient) -> None:
        with pytest.raises(DtekDataError):
            client_with_ajax._handle_response(200, '{"result": false}', {}, "/test")


class TestSessionLifecycle:
    async def test_no_session_raises_on_post(self) -> None:
        client = DtekClient("kem", ajax_url="https://example.com/ajax")
        with pytest.raises(DtekConnectionError):
            await client._post({"method": "test"})

    async def test_close_injected_session_is_noop(self, mock_session: MagicMock) -> None:
        client = DtekClient("kem", session=mock_session)
        await client.close()
        mock_session.close.assert_not_called()

    async def test_context_manager_opens_and_closes_own_session(self) -> None:
        mock_sess = MagicMock()
        mock_sess.closed = False
        mock_sess.close = AsyncMock()

        with patch("dtek_client.client.aiohttp.ClientSession", return_value=mock_sess):
            async with DtekClient("kem", ajax_url="https://x.com/ajax") as client:
                assert client._session is mock_sess

        mock_sess.close.assert_awaited_once()

    async def test_replaces_closed_session_when_session_factory_provided(
        self, streets_raw: dict[str, Any]
    ) -> None:
        closed_session = MagicMock()
        closed_session.closed = True

        fresh_session = MagicMock()
        fresh_session.closed = False
        cookie = MagicMock()
        cookie.key = "_csrf-dtek-krem"
        cookie.value = SAMPLE_CSRF_COOKIE
        fresh_session.cookie_jar = [cookie]
        fresh_session.post = MagicMock(
            return_value=make_mock_response(status_code=200, json_data=streets_raw)
        )

        client = DtekClient(
            "krem",
            session=closed_session,
            session_factory=lambda: fresh_session,
            csrf_token="old_csrf",  # noqa: S106
        )
        streets = await client.get_streets("м. Українка")
        assert len(streets) > 0
        assert client._session is fresh_session

    async def test_closed_injected_session_without_factory_raises(self) -> None:
        closed_session = MagicMock()
        closed_session.closed = True
        client = DtekClient("krem", session=closed_session)
        with pytest.raises(DtekConnectionError, match="closed"):
            await client.get_streets("м. Українка")

    async def test_connect_uses_session_factory_when_provided(self) -> None:
        created_session = MagicMock()
        created_session.closed = False
        created_session.close = AsyncMock()
        client = DtekClient("krem", session_factory=lambda: created_session)
        await client.connect()
        assert client._session is created_session
        await client.close()
        created_session.close.assert_not_called()

    async def test_lazy_session_creation_via_factory_without_explicit_connect(
        self, streets_raw: dict[str, Any]
    ) -> None:
        lazy_session = MagicMock()
        lazy_session.closed = False
        lazy_session.cookie_jar = None
        lazy_session.post = MagicMock(
            return_value=make_mock_response(
                status_code=200,
                json_data=streets_raw,
                cookies={"other_cookie": "ignored", "_csrf-dtek-krem": SAMPLE_CSRF_COOKIE},
            )
        )
        client = DtekClient("krem", session_factory=lambda: lazy_session)
        streets = await client.get_streets("м. Українка")
        assert len(streets) > 0
        assert client._session is lazy_session

    async def test_handles_non_iterable_cookie_jar_gracefully(
        self, streets_raw: dict[str, Any]
    ) -> None:
        session = MagicMock()
        session.closed = False
        bad_jar = MagicMock()
        bad_jar.__iter__ = MagicMock(side_effect=TypeError("not iterable"))
        bad_jar.clear = MagicMock(side_effect=TypeError("cannot clear"))
        session.cookie_jar = bad_jar

        first_400 = make_mock_response(status_code=400, text="Bad")
        boot_400 = make_mock_response(
            status_code=400,
            text="Bad",
            cookies={"_csrf-dtek-krem": SAMPLE_CSRF_COOKIE},
        )
        ok_200 = make_mock_response(status_code=200, json_data=streets_raw)
        session.post = MagicMock(side_effect=[first_400, boot_400, ok_200])

        client = DtekClient("krem", session=session, csrf_token="stale_csrf")  # noqa: S106
        streets = await client.get_streets("м. Українка")
        assert len(streets) > 0


class TestPostRetryAndErrors:
    async def test_retries_on_server_error_then_succeeds(self, mock_session: MagicMock) -> None:
        mock_session.post = MagicMock(
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
        mock_session.post = MagicMock(return_value=make_mock_response(status_code=503))
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
        client_with_ajax._session.post = MagicMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=401)
        )
        with pytest.raises(DtekUnauthorizedError):
            await client_with_ajax._post({"method": "test"})

    async def test_rate_limit_is_not_retried(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._session.post = MagicMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=429)
        )
        with pytest.raises(DtekRateLimitError):
            await client_with_ajax._post({"method": "test"})

    async def test_not_found_is_not_retried(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._session.post = MagicMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=404)
        )
        with pytest.raises(DtekNotFoundError):
            await client_with_ajax._post({"method": "test"})

    async def test_post_timeout_raises_timeout_error(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._session.post = MagicMock(  # type: ignore[union-attr]
            side_effect=TimeoutError("timed out")
        )
        with pytest.raises(DtekTimeoutError):
            await client_with_ajax._post({"method": "test"})

    async def test_post_ssl_error_raises_ssl_error(self, client_with_ajax: DtekClient) -> None:
        ssl_err = aiohttp.ClientSSLError(MagicMock(), OSError("ssl fail"))
        client_with_ajax._session.post = MagicMock(side_effect=ssl_err)  # type: ignore[union-attr]
        with pytest.raises(DtekSSLError):
            await client_with_ajax._post({"method": "test"})

    async def test_post_client_error_raises_connection_error(
        self, client_with_ajax: DtekClient
    ) -> None:
        client_with_ajax._session.post = MagicMock(  # type: ignore[union-attr]
            side_effect=aiohttp.ClientError("socket closed")
        )
        with pytest.raises(DtekConnectionError):
            await client_with_ajax._post({"method": "test"})


class TestGetStreets:
    async def test_success_dict_format(
        self, client_with_ajax: DtekClient, streets_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=streets_raw)  # type: ignore[method-assign]
        streets = await client_with_ajax.get_streets("м. Українка")
        assert len(streets) > 0
        assert all(isinstance(s.name, str) and len(s.name) > 0 for s in streets)

    async def test_success_list_format_without_city(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"result": True, "streets": ["вул. Хрещатик", "вул. Білоруська"]}
        )
        streets = await client_with_ajax.get_streets()
        assert [s.name for s in streets] == ["вул. Хрещатик", "вул. Білоруська"]

    async def test_dict_format_without_city_returns_unique_sorted_streets(
        self, client_with_ajax: DtekClient
    ) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "result": True,
                "streets": {
                    "м. А": ["вул. Садова", "вул. Миру"],
                    "м. Б": ["вул. Садова", "вул. Центральна"],
                },
            }
        )
        streets = await client_with_ajax.get_streets()
        assert [s.name for s in streets] == ["вул. Миру", "вул. Садова", "вул. Центральна"]

    async def test_get_all_streets_normalizes_list_and_dict(
        self, client_with_ajax: DtekClient
    ) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"result": True, "streets": ["вул. Хрещатик"]}
        )
        kyiv_map = await client_with_ajax.get_all_streets()
        assert kyiv_map == {"м. Київ": ["вул. Хрещатик"]}

        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"result": True, "streets": {"м. Ірпінь": ["вул. Соборна"]}}
        )
        region_map = await client_with_ajax.get_all_streets(refresh=True)
        assert region_map == {"м. Ірпінь": ["вул. Соборна"]}

    async def test_get_all_streets_and_get_streets_reuse_cached_directory(
        self, client_with_ajax: DtekClient, streets_raw: dict[str, Any]
    ) -> None:
        mock_post = AsyncMock(return_value=streets_raw)
        client_with_ajax._post = mock_post  # type: ignore[method-assign]

        all_map = await client_with_ajax.get_all_streets()
        city_streets = await client_with_ajax.get_streets("м. Українка")

        assert "м. Українка" in all_map
        assert len(city_streets) > 0
        assert mock_post.await_count == 1

        await client_with_ajax.get_streets("м. Українка", refresh=True)
        assert mock_post.await_count == 2

    async def test_get_streets_error_is_not_cached(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                DtekServerError(503),
                {"streets": {"м. Українка": ["вул. Юності"]}},
            ]
        )
        with pytest.raises(DtekServerError):
            await client_with_ajax.get_all_streets()

        streets = await client_with_ajax.get_streets("м. Українка")
        assert [s.name for s in streets] == ["вул. Юності"]

    async def test_get_all_streets_raises_on_non_dict(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(return_value="invalid")  # type: ignore[method-assign]
        with pytest.raises(DtekDataError):
            await client_with_ajax.get_all_streets()

    async def test_get_all_streets_returns_empty_on_unexpected_streets_type(
        self, client_with_ajax: DtekClient
    ) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": 123}
        )
        assert await client_with_ajax.get_all_streets() == {}

    async def test_non_dict_raises_data_error(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(return_value="not a dict")  # type: ignore[method-assign]
        with pytest.raises(DtekDataError):
            await client_with_ajax.get_streets("м. Тест")

    async def test_empty_data_returns_empty_list(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(return_value={"result": True, "data": {}})  # type: ignore[method-assign]
        streets = await client_with_ajax.get_streets("м. Тест")
        assert streets == []

    async def test_city_not_found_returns_empty(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": {"м. Інше": ["вул. Центральна"]}}
        )
        streets = await client_with_ajax.get_streets("м. Невідоме")
        assert streets == []

    async def test_case_insensitive_city_lookup(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": {"м. Українка": ["вул. Юності", "вул. Садова"]}}
        )
        streets = await client_with_ajax.get_streets("М. УКРАЇНКА")
        assert len(streets) == 2
        assert streets[0].name == "вул. Юності"

    async def test_city_value_not_a_list_returns_empty(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": {"м. Українка": {"nested": "unexpected"}}}
        )
        assert await client_with_ajax.get_streets("м. Українка") == []

    async def test_completely_unexpected_streets_type_returns_empty(
        self, client_with_ajax: DtekClient
    ) -> None:
        client_with_ajax._post = AsyncMock(  # type: ignore[method-assign]
            return_value={"streets": "totally_wrong"}
        )
        assert await client_with_ajax.get_streets("м. Українка") == []


class TestGetHomeNum:
    async def test_sends_force_update_fact_by_default(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert isinstance(result, HomeNumResponse)
        assert "1" in result.houses
        posted_form = client_with_ajax._post.call_args.args[0]
        assert posted_form["data[2][name]"] == "updateFact"
        assert posted_form["data[2][value]"] == FORCE_UPDATE_FACT

    async def test_non_dict_raises(self, client_with_ajax: DtekClient) -> None:
        client_with_ajax._post = AsyncMock(return_value=[1, 2, 3])  # type: ignore[method-assign]
        with pytest.raises(DtekDataError):
            await client_with_ajax.get_home_num("м. Тест", "вул. Тест")

    async def test_preset_and_fact_parsed(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert result.preset is not None
        assert "GPV3.1" in result.preset.groups
        assert result.fact is not None
        assert result.fact.today_ts == 1774483200


class TestGetHomeNumGlobalScheduleFallback:
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
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        base = self._raw_without_schedule()
        global_sched = {"preset": home_num_raw["preset"], "fact": home_num_raw["fact"]}
        call_count = 0

        async def _side_effect(form: dict[str, Any]) -> dict[str, Any]:
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
        base = self._raw_without_schedule()
        call_count = 0

        async def _side_effect(form: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return base
            raise RuntimeError("global schedule unavailable")

        client_with_ajax._post = _side_effect  # type: ignore[method-assign]
        result = await client_with_ajax.get_home_num("м. Українка", "вул. Юності")
        assert isinstance(result, HomeNumResponse)
        assert result.preset is None

    async def test_global_schedule_refreshes_when_newer_schedule_arrives(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        v1 = copy.deepcopy(home_num_raw)
        v1["fact"]["update"] = "16.11.2026 10:00"

        v2 = copy.deepcopy(home_num_raw)
        v2["fact"]["update"] = "16.11.2026 18:00"

        mock_post = AsyncMock(
            side_effect=[
                v1,
                self._raw_without_schedule(),
                v2,
                self._raw_without_schedule(),
            ]
        )
        client_with_ajax._post = mock_post  # type: ignore[method-assign]

        r1 = await client_with_ajax.get_home_num(
            "м. Українка", "вул. Юності", update_fact="01.01.2000 00:00"
        )
        assert r1.fact is not None
        assert r1.fact.update == "16.11.2026 10:00"

        r1_delta = await client_with_ajax.get_home_num(
            "м. Українка", "вул. Юності", update_fact="16.11.2026 10:00"
        )
        assert r1_delta.fact is not None
        assert r1_delta.fact.update == "16.11.2026 10:00"

        r2 = await client_with_ajax.get_home_num(
            "м. Українка", "вул. Юності", update_fact="16.11.2026 10:00"
        )
        assert r2.fact is not None
        assert r2.fact.update == "16.11.2026 18:00"

        r2_delta = await client_with_ajax.get_home_num(
            "м. Українка", "вул. Юності", update_fact="16.11.2026 18:00"
        )
        assert r2_delta.fact is not None
        assert r2_delta.fact.update == "16.11.2026 18:00"
        assert mock_post.await_count == 4

    async def test_validation_error_raises_data_error(self, client_with_ajax: DtekClient) -> None:
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


class TestGetGroupByAddress:
    async def test_success(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_group_by_address("м. Українка", "вул. Юності", "1")
        assert isinstance(result, AddressResult)
        assert result.group_id == "GPV3.1"
        assert result.house_number == "1"

    async def test_matches_cyrillic_house_number_against_latin_fixture_key(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        result = await client_with_ajax.get_group_by_address("м. Українка", "вул. Юності", "3/а")
        assert result.group_id == "GPV3.1"
        assert result.house_number == "3/A"

    async def test_reuses_provided_response_without_network_call(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        parsed = HomeNumResponse.model_validate(home_num_raw)
        client_with_ajax._post = AsyncMock()  # type: ignore[method-assign]
        result = await client_with_ajax.get_group_by_address(
            "м. Українка", "вул. Юності", "2", response=parsed
        )
        assert result.group_id == "GPV3.2"
        client_with_ajax._post.assert_not_called()

    async def test_house_not_found_raises(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        with pytest.raises(DtekNotFoundError):
            await client_with_ajax.get_group_by_address("м. Українка", "вул. Юності", "999")


class TestScheduleLookups:
    _today = datetime.datetime.fromtimestamp(_TODAY_TS, tz=ZoneInfo(DEFAULT_TIMEZONE)).date()
    _tomorrow = datetime.datetime.fromtimestamp(_TOMORROW_TS, tz=ZoneInfo(DEFAULT_TIMEZONE)).date()

    async def test_get_today_schedule_returns_slot_map(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        slots = await client_with_ajax.get_today_schedule("м. Українка", "вул. Юності", "1")
        assert slots is not None
        assert slots["1"] is SlotStatus.NO

    async def test_get_today_schedule_house_not_found_returns_none(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        assert (
            await client_with_ajax.get_today_schedule("м. Українка", "вул. Юності", "999") is None
        )

    async def test_get_tomorrow_schedule_returns_slot_map_when_present(
        self, client_with_ajax: DtekClient, home_num_raw_with_tomorrow: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw_with_tomorrow)  # type: ignore[method-assign]
        result = await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert result is not None
        assert all(isinstance(v, SlotStatus) for v in result.values())

    async def test_get_tomorrow_schedule_across_dst_spring_forward(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        ts_mar_29 = int(datetime.datetime(2026, 3, 29, 0, 0, tzinfo=tz).timestamp())
        ts_mar_30 = int(datetime.datetime(2026, 3, 30, 0, 0, tzinfo=tz).timestamp())
        assert ts_mar_30 - ts_mar_29 == 82800

        raw = copy.deepcopy(home_num_raw)
        today_slots = raw["fact"]["data"][str(_TODAY_TS)]
        raw["fact"]["today"] = ts_mar_29
        raw["fact"]["data"] = {
            str(ts_mar_29): today_slots,
            str(ts_mar_30): today_slots,
        }

        client_with_ajax._post = AsyncMock(return_value=raw)  # type: ignore[method-assign]
        tmrw = await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert tmrw is not None
        assert tmrw["1"] is SlotStatus.NO

    async def test_get_tomorrow_schedule_returns_none_when_absent(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        client_with_ajax._post = AsyncMock(return_value=home_num_raw)  # type: ignore[method-assign]
        assert (
            await client_with_ajax.get_tomorrow_schedule("м. Українка", "вул. Юності", "1") is None
        )

    async def test_get_schedule_for_date_matches_today_and_tomorrow(
        self, client_with_ajax: DtekClient, home_num_raw_with_tomorrow: dict[str, Any]
    ) -> None:
        parsed = HomeNumResponse.model_validate(home_num_raw_with_tomorrow)
        today_direct = await client_with_ajax.get_today_schedule(
            "м. Українка", "вул. Юності", "1", response=parsed
        )
        today_by_date = await client_with_ajax.get_schedule_for_date(
            "м. Українка", "вул. Юності", "1", self._today, response=parsed
        )
        assert today_direct == today_by_date

        tmrw_direct = await client_with_ajax.get_tomorrow_schedule(
            "м. Українка", "вул. Юності", "1", response=parsed
        )
        tmrw_by_date = await client_with_ajax.get_schedule_for_date(
            "м. Українка", "вул. Юності", "1", self._tomorrow, response=parsed
        )
        assert tmrw_direct == tmrw_by_date

    async def test_get_schedule_for_date_returns_none_when_house_or_date_missing(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        parsed = HomeNumResponse.model_validate(home_num_raw)
        assert (
            await client_with_ajax.get_schedule_for_date(
                "м. Українка", "вул. Юності", "999", self._today, response=parsed
            )
            is None
        )
        assert (
            await client_with_ajax.get_schedule_for_date(
                "м. Українка",
                "вул. Юності",
                "1",
                datetime.date(2099, 1, 1),
                response=parsed,
            )
            is None
        )


class TestGetAvailableFactDates:
    async def test_returns_sorted_dates(
        self, client_with_ajax: DtekClient, home_num_raw_with_tomorrow: dict[str, Any]
    ) -> None:
        parsed = HomeNumResponse.model_validate(home_num_raw_with_tomorrow)
        dates = DtekClient.get_available_fact_dates(parsed)
        assert len(dates) == 2
        assert dates == sorted(dates)

    def test_ignores_invalid_timestamp_keys_and_handles_none_fact(self) -> None:
        no_fact = HomeNumResponse.model_construct(houses={}, preset=None, fact=None)
        assert DtekClient.get_available_fact_dates(no_fact) == []

        from dtek_client.models import FactSchedule

        bad_fact = FactSchedule.model_construct(
            today_ts=_TODAY_TS,
            update=None,
            days={"invalid_ts": {}, str(_TODAY_TS): {}},
        )
        with_bad = HomeNumResponse.model_construct(houses={}, preset=None, fact=bad_fact)
        dates = DtekClient.get_available_fact_dates(with_bad)
        assert len(dates) == 1

    async def test_get_tomorrow_schedule_returns_none_when_house_missing(
        self, client_with_ajax: DtekClient, home_num_raw: dict[str, Any]
    ) -> None:
        parsed = HomeNumResponse.model_validate(home_num_raw)
        assert (
            await client_with_ajax.get_tomorrow_schedule(
                "м. Українка", "вул. Юності", "999", response=parsed
            )
            is None
        )
