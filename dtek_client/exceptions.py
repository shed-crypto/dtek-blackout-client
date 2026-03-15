"""Custom exception classes for dtek-blackout-client."""
from __future__ import annotations


class DtekClientError(Exception):
    """Base exception for all DTEK client errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={str(self)!r}, "
            f"status_code={self.status_code!r})"
        )


# ── Network / Connectivity ────────────────────────────────────────────────────

class DtekConnectionError(DtekClientError):
    """Raised when a network-level error prevents reaching the ДТЕК site."""


class DtekTimeoutError(DtekConnectionError):
    """Raised when the request exceeds the configured timeout."""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"ДТЕК request timed out after {timeout:.1f}s")
        self.timeout = timeout


class DtekSSLError(DtekConnectionError):
    """Raised when the TLS/SSL handshake with the DTEK site fails."""


# ── API / HTTP ────────────────────────────────────────────────────────────────

class DtekAPIError(DtekClientError):
    """Raised when the site returns a non-2xx HTTP status code."""


class DtekUnauthorizedError(DtekAPIError):
    """Raised on HTTP 401."""

    def __init__(self) -> None:
        super().__init__("Unauthorized: DTEK site rejected the request.", status_code=401)


class DtekNotFoundError(DtekAPIError):
    """Raised on HTTP 404 – page or resource not found."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Not found: {path}", status_code=404)
        self.path = path


class DtekRateLimitError(DtekAPIError):
    """Raised on HTTP 429 – too many requests.

    Args:
        retry_after: seconds to wait (from Retry-After header), or None.
    """

    def __init__(self, retry_after: float | None = None) -> None:
        msg = "Rate limit exceeded."
        if retry_after is not None:
            msg += f" Retry after {retry_after:.0f}s."
        super().__init__(msg, status_code=429)
        self.retry_after = retry_after


class DtekServerError(DtekAPIError):
    """Raised on HTTP 5xx – server-side fault."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"ДТЕК server error (HTTP {status_code}).", status_code=status_code)


# ── Data / Parsing ────────────────────────────────────────────────────────────

class DtekDataError(DtekClientError):
    """Raised when an AJAX response cannot be parsed into the expected models."""

    def __init__(self, message: str, raw: object = None) -> None:
        super().__init__(message)
        self.raw = raw


# ── Site Configuration ────────────────────────────────────────────────────────

class DtekSiteError(DtekClientError):
    """Raised when the ajaxUrl cannot be discovered from the site page,
    or when an unknown site_key is provided."""
