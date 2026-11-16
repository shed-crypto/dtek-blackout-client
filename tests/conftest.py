"""Shared pytest fixtures for dtek-blackout-client tests."""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SAMPLE_RAW_CSRF = "hcngll8nSRRncXlsYEvw2Z8QlBAgLbvP"
SAMPLE_CSRF_COOKIE = (
    "de0758ab90a20e48c9328d0a8170697b7d351377faaffe6058657768418c1d8fa%3A2%3A%7B"
    "i%3A0%3Bs%3A15%3A%22_csrf-dtek-krem%22%3B"
    f"i%3A1%3Bs%3A32%3A%22{SAMPLE_RAW_CSRF}%22%3B%7D"
)


@pytest.fixture
def home_num_raw() -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / "home_num_response.json").read_text(encoding="utf-8"))


@pytest.fixture
def streets_raw() -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / "streets_response.json").read_text(encoding="utf-8"))


def make_mock_response(
    status_code: int = 200,
    text: str = "",
    json_data: Any = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock aiohttp ClientResponse context manager."""
    if json_data is not None and not text:
        text = json.dumps(json_data, ensure_ascii=False)

    resp = MagicMock()
    resp.status = status_code
    resp.headers = headers or {}

    simple_cookie = SimpleCookie()
    for k, v in (cookies or {}).items():
        simple_cookie[k] = v
    resp.cookies = simple_cookie

    resp.text = AsyncMock(return_value=text)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)
    return resp


@pytest.fixture
def mock_session() -> MagicMock:
    """Mock aiohttp.ClientSession with pre-populated CSRF cookie in its jar."""
    session = MagicMock()
    session.closed = False

    cookie = MagicMock()
    cookie.key = "_csrf-dtek-kem"
    cookie.value = SAMPLE_CSRF_COOKIE
    session.cookie_jar = [cookie]

    session.get = MagicMock(return_value=make_mock_response(status_code=200, text=""))
    session.post = MagicMock(
        return_value=make_mock_response(status_code=200, json_data={"result": True})
    )
    session.close = AsyncMock()
    return session


@pytest.fixture
def client_with_ajax(mock_session: MagicMock) -> Any:
    """DtekClient configured with a mock session and pre-set ajaxUrl."""
    from dtek_client import DtekClient

    return DtekClient(
        "kem",
        ajax_url="https://www.dtek-kem.com.ua/ua/ajax",
        session=mock_session,
    )
