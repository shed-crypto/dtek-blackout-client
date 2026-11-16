"""Custom exception classes for dtek-blackout-client.

Hierarchy:
    DtekClientError                  (base)
    ├── DtekConnectionError          (network / connectivity issues)
    │   ├── DtekTimeoutError         (request timed out)
    │   ├── DtekSSLError             (TLS/SSL handshake failure)
    │   └── DtekBlockedError         (WAF / anti-bot challenge page)
    ├── DtekAPIError                 (server returned an error response)
    │   ├── DtekUnauthorizedError    (401)
    │   ├── DtekNotFoundError        (404)
    │   ├── DtekRateLimitError       (429)
    │   └── DtekServerError          (5xx)
    ├── DtekDataError                (response cannot be parsed)
    └── DtekSiteError                (site configuration / meta discovery issue)
"""

from __future__ import annotations


class DtekClientError(Exception):
    """Base exception for all DTEK client errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={str(self)!r}, status_code={self.status_code!r})"


class DtekConnectionError(DtekClientError):
    """Raised when a network-level error prevents reaching the DTEK site."""


class DtekTimeoutError(DtekConnectionError):
    """Raised when the request exceeds the configured timeout."""

    def __init__(self, timeout: float) -> None:
        super().__init__(f"DTEK request timed out after {timeout:.1f}s")
        self.timeout = timeout


class DtekSSLError(DtekConnectionError):
    """Raised when the TLS/SSL handshake with the DTEK site fails."""


class DtekBlockedError(DtekConnectionError):
    """Raised when the DTEK site returns an anti-bot WAF challenge instead of data."""


class DtekAPIError(DtekClientError):
    """Raised when the site returns a non-2xx HTTP status code."""


class DtekUnauthorizedError(DtekAPIError):
    """Raised on HTTP 401."""

    def __init__(self) -> None:
        super().__init__("Unauthorized: DTEK site rejected the request.", status_code=401)


class DtekNotFoundError(DtekAPIError):
    """Raised on HTTP 404 when a page, street, or house is not found."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Not found: {path}", status_code=404)
        self.path = path


class DtekRateLimitError(DtekAPIError):
    """Raised on HTTP 429 when rate limits are exceeded."""

    def __init__(self, retry_after: float | None = None) -> None:
        msg = "Rate limit exceeded."
        if retry_after is not None:
            msg += f" Retry after {retry_after:.0f}s."
        super().__init__(msg, status_code=429)
        self.retry_after = retry_after


class DtekServerError(DtekAPIError):
    """Raised on HTTP 5xx server-side fault."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"DTEK server error (HTTP {status_code}).", status_code=status_code)


class DtekDataError(DtekClientError):
    """Raised when an AJAX response cannot be parsed into the expected models."""

    def __init__(self, message: str, raw: object = None) -> None:
        super().__init__(message)
        self.raw = raw


class DtekSiteError(DtekClientError):
    """Raised when an unknown site_key is provided or site configuration fails."""
