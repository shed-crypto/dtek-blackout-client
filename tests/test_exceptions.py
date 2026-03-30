"""Unit tests for dtek_client.exceptions."""

from __future__ import annotations

import pytest

from dtek_client.exceptions import (
    DtekAPIError,
    DtekClientError,
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


class TestHierarchy:
    def test_base_is_exception(self) -> None:
        assert issubclass(DtekClientError, Exception)

    def test_connection_is_client(self) -> None:
        assert issubclass(DtekConnectionError, DtekClientError)

    def test_timeout_is_connection(self) -> None:
        assert issubclass(DtekTimeoutError, DtekConnectionError)

    def test_ssl_is_connection(self) -> None:
        assert issubclass(DtekSSLError, DtekConnectionError)

    def test_api_is_client(self) -> None:
        assert issubclass(DtekAPIError, DtekClientError)

    def test_unauthorized_is_api(self) -> None:
        assert issubclass(DtekUnauthorizedError, DtekAPIError)

    def test_not_found_is_api(self) -> None:
        assert issubclass(DtekNotFoundError, DtekAPIError)

    def test_rate_limit_is_api(self) -> None:
        assert issubclass(DtekRateLimitError, DtekAPIError)

    def test_server_is_api(self) -> None:
        assert issubclass(DtekServerError, DtekAPIError)

    def test_data_is_client(self) -> None:
        assert issubclass(DtekDataError, DtekClientError)

    def test_site_is_client(self) -> None:
        assert issubclass(DtekSiteError, DtekClientError)


class TestMessages:
    def test_base_stores_status_code(self) -> None:
        e = DtekClientError("oops", status_code=500)
        assert e.status_code == 500
        assert "oops" in str(e)

    def test_base_repr(self) -> None:
        e = DtekClientError("oops", status_code=418)
        assert "418" in repr(e)
        assert "DtekClientError" in repr(e)

    def test_timeout_message(self) -> None:
        e = DtekTimeoutError(15.0)
        assert "15.0" in str(e)
        assert e.timeout == 15.0

    def test_not_found_stores_path(self) -> None:
        e = DtekNotFoundError("/schedule")
        assert e.path == "/schedule"
        assert e.status_code == 404

    def test_unauthorized_status(self) -> None:
        assert DtekUnauthorizedError().status_code == 401

    def test_rate_limit_with_retry_after(self) -> None:
        e = DtekRateLimitError(retry_after=60.0)
        assert e.retry_after == 60.0
        assert "60" in str(e)
        assert e.status_code == 429

    def test_rate_limit_none(self) -> None:
        assert DtekRateLimitError().retry_after is None

    def test_server_error(self) -> None:
        e = DtekServerError(503)
        assert e.status_code == 503
        assert "503" in str(e)

    def test_data_error_stores_raw(self) -> None:
        raw = {"broken": True}
        e = DtekDataError("bad payload", raw=raw)
        assert e.raw is raw

    def test_no_status_code(self) -> None:
        assert DtekClientError("plain").status_code is None
