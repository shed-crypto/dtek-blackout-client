"""Exceptions for the dtek-blackout-client."""

class DtekClientError(Exception):
    """Base exception for all DTEK client errors."""

class DtekConnectionError(DtekClientError):
    """Raised when the connection to the DTEK site fails."""

class DtekTimeoutError(DtekClientError):
    """Raised when a request times out."""

class DtekAPIError(DtekClientError):
    """Raised when the API returns an error HTTP status."""