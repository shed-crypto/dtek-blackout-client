"""dtek-blackout-client – Async Python client for DTEK regional disconnection-schedule sites.

DTEK operates separate WordPress sites for each regional subsidiary
(Kyiv, Dnipro, Donetsk, Odesa, Zaporizhzhia, etc.).  This library scrapes
the AJAX endpoint from each site and provides a clean, fully-typed async
interface to the disconnection schedule.

Quick start::

    import asyncio
    from dtek_client import DtekClient

    async def main() -> None:
        async with DtekClient("kem") as client:

            # 1. Get all streets in a city
            streets = await client.get_streets("м. Україна")
            print([s.name for s in streets])

            # 2. Get all houses + groups for a street
            response = await client.get_home_num("м. Україна", "вул. Юності")
            for house, entry in response.houses.items():
                print(house, "→", entry.primary_group)

            # 3. Find your group by address
            result = await client.get_group_by_address(
                city="м. Україна",
                street="вул. Юності",
                house_number="10",
            )
            print(result)  # м. Україна, вул. Юності, 10 → Черга 3.1

    asyncio.run(main())

Supported site_keys (DTEK regional sites):
    "kem"  – DTEK Kyivenerho       (Kyiv city and oblast)
    "krem" – DTEK Kyiv Regional    (Kyiv oblast, smaller towns)
    "dnem" – DTEK Dnipro           (Dnipro, Dnipropetrovsk oblast)
    "dem"  – DTEK Donetsk          (government-controlled Donetsk oblast)
    "oem"  – DTEK Odesa            (Odesa, Odesa oblast)
    "zem"  – DTEK Zaporizhzhia     (Zaporizhzhia)
"""

from importlib.metadata import PackageNotFoundError, version

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

try:
    __version__ = version("dtek-blackout-client")
except PackageNotFoundError:
    __version__ = "unknown"

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
