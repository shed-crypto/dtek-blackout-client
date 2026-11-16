"""dtek-blackout-client - Async Python client for DTEK regional disconnection-schedule sites.

DTEK operates separate web applications for each regional subsidiary
(Kyiv, Kyiv Region, Dnipro, Donetsk, Odesa). This library communicates with
the AJAX endpoint on each site and provides a typed async interface to the
disconnection schedule.

Supported site_keys (DTEK regional sites):
    "kem"  - DTEK Kyiv City Networks (Kyiv city)
    "krem" - DTEK Kyiv Regional Networks (Kyiv oblast)
    "dnem" - DTEK Dnipro Networks (Dnipropetrovsk oblast)
    "dem"  - DTEK Donetsk Networks (Donetsk oblast)
    "oem"  - DTEK Odesa Networks (Odesa oblast)
"""

from importlib.metadata import PackageNotFoundError, version

from .client import DtekClient
from .exceptions import (
    DtekAPIError,
    DtekBlockedError,
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

try:
    __version__ = version("dtek-blackout-client")
except PackageNotFoundError:
    __version__ = "unknown"

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
    "DtekBlockedError",
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
