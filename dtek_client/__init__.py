"""dtek-blackout-client – Async Python client for DTEK regional disconnection-schedule sites."""

__version__ = "0.1.5"

from .client import DtekClient
from .exceptions import (
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
from .models import (
    AddressResult,
    FactDaySchedule,
    FactSchedule,
    GroupWeekSchedule,
    HomeNumResponse,
    HouseEntry,
    PresetSchedule,
    SlotStatus,
    StreetSuggestion,
    WeekDaySchedule,
)
from .stub_client import StubDtekClient

__all__ = [
    "DtekClient",
    "StubDtekClient",
    # Models
    "AddressResult",
    "FactDaySchedule",
    "FactSchedule",
    "GroupWeekSchedule",
    "HomeNumResponse",
    "HouseEntry",
    "PresetSchedule",
    "SlotStatus",
    "StreetSuggestion",
    "WeekDaySchedule",
    # Exceptions
    "DtekAPIError",
    "DtekClientError",
    "DtekConnectionError",
    "DtekDataError",
    "DtekNotFoundError",
    "DtekRateLimitError",
    "DtekServerError",
    "DtekSiteError",
    "DtekSSLError",
    "DtekTimeoutError",
    "DtekUnauthorizedError",
]
