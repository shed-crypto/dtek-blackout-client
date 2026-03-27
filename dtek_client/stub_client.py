"""Stub (hardcoded) implementation of DtekClient.

PURPOSE
-------
Teammates working on the Home Assistant integration can start coding
*immediately* without waiting for the real DTEK site to respond.

HOW TO USE
----------
Swap one import line in your HA code::

    # Production:
    # from dtek_client import DtekClient

    # During development:
    from dtek_client.stub_client import StubDtekClient as DtekClient

The interface is 100% identical.  When the real client is ready,
revert that one import — nothing else changes.
"""
from __future__ import annotations

from types import TracebackType
from typing import Any

from .models import (
    AddressResult,
    FactSchedule,
    GroupWeekSchedule,
    HomeNumResponse,
    HouseEntry,
    PresetSchedule,
    SlotStatus,
    StreetSuggestion,
    WeekDaySchedule,
)

__all__ = ["StubDtekClient"]

# ── Hardcoded time-zone labels ────────────────────────────────────────────────

_TIME_ZONE: dict[str, str] = {
    str(i): (
        f"{((i-1)*30)//60:02d}:{((i-1)*30)%60:02d}"
        f"–{((i*30))//60:02d}:{((i*30))%60:02d}"
    )
    for i in range(1, 49)
}
# Slot 48 ends at 24:00, not 00:00.
_TIME_ZONE["48"] = "23:30–24:00"

# ── Outage patterns for preset data ──────────────────────────────────────────

_OUTAGE_PATTERN_1 = {str(i) for i in range(1, 9)} | {str(i) for i in range(37, 45)}
_OUTAGE_PATTERN_2 = {str(i) for i in range(9, 17)} | {str(i) for i in range(25, 33)}
_OUTAGE_PATTERN_3 = {str(i) for i in range(17, 25)} | {str(i) for i in range(41, 49)}

_PATTERNS: dict[str, set[str]] = {
    "GPV3.1": _OUTAGE_PATTERN_1,
    "GPV3.2": _OUTAGE_PATTERN_2,
    "GPV4.1": _OUTAGE_PATTERN_3,
}


def _make_week_day(outage_slots: set[str]) -> WeekDaySchedule:
    """Build a WeekDaySchedule from a set of outage slot keys."""
    slots = {
        k: (SlotStatus.NO if k in outage_slots else SlotStatus.YES)
        for k in _TIME_ZONE
    }
    return WeekDaySchedule(slots=slots)


def _make_preset() -> PresetSchedule:
    """Build a realistic PresetSchedule with three outage groups."""
    groups: dict[str, GroupWeekSchedule] = {}
    for group_id, pattern in _PATTERNS.items():
        days = {d: _make_week_day(pattern) for d in range(1, 8)}
        # Use model_construct to bypass model_validator (expects raw AJAX dict).
        groups[group_id] = GroupWeekSchedule.model_construct(
            group_id=group_id, days=days
        )

    return PresetSchedule.model_construct(
        groups=groups,
        time_zone=_TIME_ZONE,
        sch_names={
            "GPV3.1": "Черга планових відключень 3.1",
            "GPV3.2": "Черга планових відключень 3.2",
            "GPV4.1": "Черга планових відключень 4.1",
        },
        days={
            1: "Понеділок", 2: "Вівторок", 3: "Середа", 4: "Четвер",
            5: "П'ятниця", 6: "Субота", 7: "Неділя",
        },
        is_active=True,
    )


def _make_fact(today_ts: int, group_id: str, outage_slots: set[str]) -> FactSchedule:
    """Build a FactSchedule stub for today."""
    slots = {
        k: (SlotStatus.NO if k in outage_slots else SlotStatus.YES)
        for k in _TIME_ZONE
    }
    # Use model_construct to bypass model_validator (expects raw AJAX dict).
    return FactSchedule.model_construct(
        today_ts=today_ts,
        update="Stub data",
        days={str(today_ts): {group_id: slots}},
    )


# ── Hardcoded address data ────────────────────────────────────────────────────

_STREETS: dict[str, dict[str, list[str]]] = {
    "м. Українка": {
        "вул. Юності":       ["1", "2", "3", "5", "7", "9", "11", "12", "14"],
        "вул. Садова":       ["1", "1А", "2", "2А", "3"],
        "вул. Паркова":      ["1", "2", "4", "6", "8", "10"],
        "пр. Незалежності":  ["1", "1/1", "2", "3", "4", "5"],
    },
    "м. Обухів": {
        "вул. Центральна": ["1", "2", "3"],
        "вул. Миру":       ["5", "7", "9"],
    },
}

_HOUSE_GROUPS: dict[str, str] = {
    "1": "GPV3.1", "1А": "GPV3.1", "1/1": "GPV3.2",
    "2": "GPV3.2", "2А": "GPV3.2",
    "3": "GPV3.1", "4": "GPV4.1",
    "5": "GPV3.1", "6": "GPV4.1",
    "7": "GPV3.2", "8": "GPV4.1",
    "9": "GPV3.1", "10": "GPV4.1",
    "11": "GPV3.2", "12": "GPV3.1",
    "14": "GPV3.2",
}


def _make_home_num_response(city: str, street: str) -> HomeNumResponse:
    """Build a complete HomeNumResponse stub for a given city and street."""
    import time as _time

    today_ts = int(_time.time()) // 86400 * 86400  # midnight UTC approximation

    streets_map = _STREETS.get(city, {})
    house_list = streets_map.get(street, ["1", "2", "3", "5", "7"])
    houses: dict[str, HouseEntry] = {}

    for hn in house_list:
        gid = _HOUSE_GROUPS.get(hn, "GPV3.1")
        houses[hn] = HouseEntry(
            house_number=hn,
            group_ids=[gid],
            sub_type="",
            start_date="",
            end_date="",
            voluntarily=None,
        )

    preset = _make_preset()
    fact = _make_fact(today_ts, "GPV3.1", _OUTAGE_PATTERN_1)

    # Use model_construct to bypass HomeNumResponse.model_validator
    # (which expects a raw AJAX dict, not pre-built model objects).
    return HomeNumResponse.model_construct(
        houses=houses,
        preset=preset,
        fact=fact,
        show_cur_schedule=True,
        show_table_plan=True,
        show_table_fact=True,
        show_table_schedule=True,
        update_timestamp="Stub data",
    )


# ── StubDtekClient ────────────────────────────────────────────────────────────

class StubDtekClient:
    """Drop-in replacement for :class:`~dtek_client.DtekClient`.

    Returns hardcoded but realistic data — no network calls, no site scraping.
    The async interface is 100% identical to DtekClient — swap one import line.
    """

    def __init__(self, site_key: str = "kem", **kwargs: Any) -> None:
        self._site_key = site_key

    async def connect(self) -> None:
        """No-op — stub requires no network connection."""

    async def close(self) -> None:
        """No-op — stub has no resources to release."""

    async def __aenter__(self) -> "StubDtekClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_streets(
        self,
        city: str,
        *,
        update_fact: str | None = None,
    ) -> list[StreetSuggestion]:
        """Return hardcoded streets for the given city."""
        streets = _STREETS.get(city, {})
        if not streets:
            # Return a generic fallback for unknown cities.
            return [StreetSuggestion(name="вул. Центральна")]
        return [StreetSuggestion(name=s) for s in sorted(streets.keys())]

    async def get_home_num(
        self,
        city: str,
        street: str,
        *,
        update_fact: str | None = None,
    ) -> HomeNumResponse:
        """Return hardcoded house numbers and schedule for the given city/street."""
        return _make_home_num_response(city, street)

    async def get_group_by_address(
        self,
        city: str,
        street: str,
        house_number: str,
        *,
        update_fact: str | None = None,
    ) -> AddressResult:
        """Return the hardcoded disconnection group for a given address."""
        response = _make_home_num_response(city, street)
        entry = response.houses.get(house_number)
        group_id = (entry.primary_group if entry else None) or "GPV3.1"
        group_name = (
            response.preset.sch_names.get(group_id, "")
            if response.preset else ""
        )
        return AddressResult(
            site_key=self._site_key,
            city=city,
            street=street,
            house_number=house_number,
            group_id=group_id,
            group_display_name=group_name,
        )

    async def get_today_schedule(
        self,
        city: str,
        street: str,
        house_number: str,
        *,
        update_fact: str | None = None,
    ) -> dict[str, Any] | None:
        """Return today's slot map for one address — always returns data in the stub."""
        response = _make_home_num_response(city, street)
        entry = response.houses.get(house_number)
        if not entry or not entry.primary_group or not response.fact:
            return None
        return response.fact.get_group_today(entry.primary_group)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def site_key(self) -> str:
        """The site_key this stub is configured for."""
        return self._site_key

    @property
    def base_url(self) -> str:
        """Base URL for the configured region (from DTEK_SITES)."""
        from .const import DTEK_SITES
        return DTEK_SITES.get(self._site_key, ("https://stub.example.com", ""))[0]

    @property
    def ajax_url(self) -> str | None:
        """Always None — the stub does not use an AJAX endpoint."""
        return None
