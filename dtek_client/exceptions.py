"""Exceptions for the dtek-blackout-client."""

class DtekClientError(Exception):
    """Base exception for all DTEK client errors."""

class DtekConnectionError(DtekClientError):
    """Raised when the connection to the DTEK site fails."""

class DtekTimeoutError(DtekClientError):
    """Raised when a request times out."""

class DtekAPIError(DtekClientError):
    """Raised when the API returns an error HTTP status."""

class DtekUnauthorizedError(DtekAPIError):
    """Raised when the site returns 401/403 (WAF block or missing cookies)."""

class DtekRateLimitError(DtekAPIError):
    """Raised when hitting Cloudflare rate limits (429)."""

class DtekSiteError(DtekClientError):
    """Raised when the site structure changes (e.g. missing meta tags)."""