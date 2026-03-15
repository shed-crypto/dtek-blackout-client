"""dtek-blackout-client – Async Python client for DTEK regional disconnection-schedule sites."""

__version__ = "0.1.0"

from .client import DtekClient
from .stub_client import StubDtekClient
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
from .exceptions import (
    DtekAPIError,
    DtekClientError,
    DtekConnectionError,
    DtekNotFoundError,
    DtekRateLimitError,
    DtekSiteError,
    DtekTimeoutError,
    DtekUnauthorizedError,
)

__all__ = [
    "DtekClient",
    "StubDtekClient",
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
    "DtekAPIError",
    "DtekClientError",
    "DtekConnectionError",
    "DtekNotFoundError",
    "DtekRateLimitError",
    "DtekSiteError",
    "DtekTimeoutError",
    "DtekUnauthorizedError",
]