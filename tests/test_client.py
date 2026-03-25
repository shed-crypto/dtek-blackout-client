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