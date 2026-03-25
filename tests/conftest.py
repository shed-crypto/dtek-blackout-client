"""Shared pytest fixtures for dtek-blackout-client tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def home_num_raw() -> dict[str, Any]:
    # encoding="utf-8" is required on Windows where the default is cp1252.
    return json.loads(
        (FIXTURES_DIR / "home_num_response.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def streets_raw() -> dict[str, Any]:
    return json.loads(
        (FIXTURES_DIR / "streets_response.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def mock_session() -> MagicMock:
    """A MagicMock that mimics curl_cffi AsyncSession."""
    session = MagicMock()
    # get() and post() must be awaitable.
    session.get = AsyncMock()
    session.post = AsyncMock()
    # close() must be awaitable.
    session.close = AsyncMock()
    return session


def make_mock_response(
    status_code: int = 200,
    text: str = "",
    json_data: Any = None,
    headers: dict | None = None,
) -> MagicMock:
    """Create a mock response object that matches the curl_cffi Response API.

    curl_cffi responses expose:
        - ``.status_code``  (int)
        - ``.text``         (str property)
        - ``.headers``      (dict-like)
        - ``.json()``       (sync method)
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("No JSON configured"))
    return resp


@pytest.fixture
def client_with_ajax(mock_session: MagicMock) -> Any:
    """DtekClient with a pre-set ajaxUrl (skips meta-tag discovery)."""
    from dtek_client import DtekClient

    return DtekClient(
        "kem",
        ajax_url="https://www.dtek-kem.com.ua/ua/ajax",
        session=mock_session,
    )
