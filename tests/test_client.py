"""Unit tests for DtekClient — all HTTP calls are mocked."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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
            '<html><head>'
            '<meta name="ajaxUrl" content="https://www.dtek-kem.com.ua/ua/ajax">'
            '</head></html>'
        )
        mock_session.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text=html)
        )
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"

    async def test_extracts_meta_reversed_attrs(self, mock_session: MagicMock) -> None:
        """content attr before name attr should still work."""
        html = '<meta content="https://example.com/ajax" name="ajaxUrl">'
        mock_session.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text=html)
        )
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://example.com/ajax"

    async def test_resolves_relative_ajax_url(self, mock_session: MagicMock) -> None:
        """A relative path in the meta tag is resolved against base_url."""
        html = '<meta name="ajaxUrl" content="/ua/ajax">'
        mock_session.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text=html)
        )
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://www.dtek-kem.com.ua/ua/ajax"

    async def test_meta_not_found_uses_fallback(self, mock_session: MagicMock) -> None:
        """When no meta tag is found, the client falls back to base_url + /ua/ajax."""
        html = "<html><body>No meta here</body></html>"
        mock_session.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text=html)
        )
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        # Fallback URL = base_url + /ua/ajax
        assert "/ua/ajax" in url

    async def test_ajax_url_cached(self, mock_session: MagicMock) -> None:
        """Second call must NOT make a second HTTP request."""
        html = '<meta name="ajaxUrl" content="https://example.com/ajax">'
        mock_session.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text=html)
        )
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
        mock_session.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text=html)
        )
        client = DtekClient("kem", session=mock_session)
        url = await client._get_ajax_url()
        assert url == "https://example.com/wp-admin/admin-ajax.php"

# ── Session lifecycle ─────────────────────────────────────────────────────────

class TestSessionLifecycle:
    async def test_no_session_raises_on_post(self) -> None:
        """_post() without a session raises DtekConnectionError."""
        client = DtekClient("kem", ajax_url="https://example.com/ajax")
        with pytest.raises(DtekConnectionError):
            await client._post({"method": "test"})

    async def test_close_injected_session_is_noop(
        self, mock_session: MagicMock
    ) -> None:
        """close() must NOT close an externally injected session."""
        client = DtekClient("kem", session=mock_session)
        await client.close()
        mock_session.close.assert_not_called()

    async def test_context_manager_opens_and_closes_own_session(self) -> None:
        """Context manager creates a session on enter and closes it on exit."""
        mock_sess = MagicMock()
        mock_sess.close = AsyncMock()
        # Warm-up GET during connect().
        mock_sess.get = AsyncMock(
            return_value=make_mock_response(status_code=200, text="")
        )

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

# ── _post() — retry logic ─────────────────────────────────────────────────────

class TestPostRetry:
    async def test_retries_on_server_error_then_succeeds(
        self, mock_session: MagicMock
    ) -> None:
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

    async def test_unauthorized_is_not_retried(
        self, client_with_ajax: DtekClient
    ) -> None:
        """401 responses are not transient — re-raise immediately without retry."""
        client_with_ajax._session.post = AsyncMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=401)
        )
        with pytest.raises(DtekUnauthorizedError):
            await client_with_ajax._post({"method": "test"})

    async def test_rate_limit_is_not_retried(
        self, client_with_ajax: DtekClient
    ) -> None:
        """429 responses are not retried — the caller should honour Retry-After."""
        client_with_ajax._session.post = AsyncMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=429)
        )
        with pytest.raises(DtekRateLimitError):
            await client_with_ajax._post({"method": "test"})

    async def test_not_found_is_not_retried(
        self, client_with_ajax: DtekClient
    ) -> None:
        """404 from the AJAX endpoint means the resource genuinely does not exist
        and should not be retried."""
        client_with_ajax._session.post = AsyncMock(  # type: ignore[union-attr]
            return_value=make_mock_response(status_code=404)
        )
        with pytest.raises(DtekNotFoundError):
            await client_with_ajax._post({"method": "test"})


# ── _handle_response() — Retry-After edge case ────────────────────────────────

class TestHandleResponseRetryAfterHeader:
    def test_non_numeric_retry_after_is_treated_as_none(
        self, client_with_ajax: DtekClient
    ) -> None:
        """When Retry-After contains an HTTP-date string rather than a number
        of seconds, parsing fails gracefully and retry_after is left as None."""
        resp = make_mock_response(
            status_code=429,
            headers={"Retry-After": "Mon, 29 Mar 2026 12:00:00 GMT"},
        )
        with pytest.raises(DtekRateLimitError) as ei:
            client_with_ajax._handle_response(resp, "/test")
        assert ei.value.retry_after is None

