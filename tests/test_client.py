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


