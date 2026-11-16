"""Stub (hardcoded) implementation of DtekClient for offline development."""

from __future__ import annotations

import datetime
from types import TracebackType
from typing import Any
from zoneinfo import ZoneInfo

from .const import DEFAULT_TIMEZONE, DTEK_SITES
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

_TIME_ZONE: dict[str, str] = {
    str(i): (
        f"{((i - 1) * 30) // 60:02d}:{((i - 1) * 30) % 60:02d}"
        f"-{(i * 30) // 60:02d}:{(i * 30) % 60:02d}"
    )
    for i in range(1, 49)
}
_TIME_ZONE["48"] = "23:30-24:00"

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
    slots = {k: (SlotStatus.NO if k in outage_slots else SlotStatus.YES) for k in _TIME_ZONE}
    return WeekDaySchedule(slots=slots)


def _make_preset() -> PresetSchedule:
    """Build a realistic PresetSchedule with three outage groups."""
    groups: dict[str, GroupWeekSchedule] = {}
    for group_id, pattern in _PATTERNS.items():
        days = {d: _make_week_day(pattern) for d in range(1, 8)}
        groups[group_id] = GroupWeekSchedule.model_construct(group_id=group_id, days=days)

    return PresetSchedule.model_construct(
        groups=groups,
        time_zone=_TIME_ZONE,
        sch_names={
            "GPV3.1": "Черга планових відключень 3.1",
            "GPV3.2": "Черга планових відключень 3.2",
            "GPV4.1": "Черга планових відключень 4.1",
        },
        days={
            1: "Понеділок",
            2: "Вівторок",
            3: "Середа",
            4: "Четвер",
            5: "П'ятниця",
            6: "Субота",
            7: "Неділя",
        },
        is_active=True,
    )


def _kyiv_midnight_ts(target_date: datetime.date) -> int:
    """Return the Unix timestamp for midnight in Europe/Kyiv on target_date."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    dt = datetime.datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
    return int(dt.timestamp())


def _make_fact(today_date: datetime.date) -> FactSchedule:
    """Build a FactSchedule stub for today and tomorrow across all stub groups."""
    today_ts = _kyiv_midnight_ts(today_date)
    tomorrow_ts = _kyiv_midnight_ts(today_date + datetime.timedelta(days=1))

    day_groups: dict[str, dict[str, SlotStatus]] = {}
    for group_id, pattern in _PATTERNS.items():
        day_groups[group_id] = {
            k: (SlotStatus.NO if k in pattern else SlotStatus.YES) for k in _TIME_ZONE
        }

    return FactSchedule.model_construct(
        today_ts=today_ts,
        update="Stub data",
        days={
            str(today_ts): {gid: dict(slots) for gid, slots in day_groups.items()},
            str(tomorrow_ts): {gid: dict(slots) for gid, slots in day_groups.items()},
        },
    )


_STREETS: dict[str, dict[str, list[str]]] = {
    "м. Українка": {
        "вул. Юності": ["1", "2", "3", "5", "7", "9", "11", "12", "14"],
        "вул. Садова": ["1", "1А", "2", "2А", "3"],
        "вул. Паркова": ["1", "2", "4", "6", "8", "10"],
        "пр. Незалежності": ["1", "1/1", "2", "3", "4", "5"],
    },
    "м. Обухів": {
        "вул. Центральна": ["1", "2", "3"],
        "вул. Миру": ["5", "7", "9"],
    },
}

_HOUSE_GROUPS: dict[str, str] = {
    "1": "GPV3.1",
    "1А": "GPV3.1",
    "1/1": "GPV3.2",
    "2": "GPV3.2",
    "2А": "GPV3.2",
    "3": "GPV3.1",
    "4": "GPV4.1",
    "5": "GPV3.1",
    "6": "GPV4.1",
    "7": "GPV3.2",
    "8": "GPV4.1",
    "9": "GPV3.1",
    "10": "GPV4.1",
    "11": "GPV3.2",
    "12": "GPV3.1",
    "14": "GPV3.2",
}


def _make_home_num_response(city: str, street: str) -> HomeNumResponse:
    """Build a complete HomeNumResponse stub for a given city and street."""
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    today_date = datetime.datetime.now(tz=tz).date()

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
    fact = _make_fact(today_date)

    return HomeNumResponse.model_construct(
        houses=houses,
        preset=preset,
        fact=fact,
        show_cur_schedule=True,
        show_cur_outage_param=True,
        show_table_plan=True,
        show_table_fact=True,
        show_table_schedule=True,
        update_timestamp="Stub data",
    )


class StubDtekClient:
    """Drop-in offline replacement for DtekClient."""

    def __init__(self, site_key: str = "kem", **kwargs: Any) -> None:
        self._site_key = site_key

    async def connect(self) -> None:
        """No-op because the stub requires no network connection."""

    async def close(self) -> None:
        """No-op because the stub holds no network resources."""

    async def __aenter__(self) -> StubDtekClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def get_all_streets(self) -> dict[str, list[str]]:
        """Return all hardcoded settlements and their street names."""
        return {city: sorted(streets.keys()) for city, streets in _STREETS.items()}

    async def get_streets(
        self,
        city: str | None = None,
    ) -> list[StreetSuggestion]:
        """Return hardcoded streets for the given city."""
        if city is None:
            all_names = sorted({s for streets in _STREETS.values() for s in streets})
            return [StreetSuggestion(name=s) for s in all_names]
        streets = _STREETS.get(city, {})
        if not streets:
            return [StreetSuggestion(name="вул. Центральна")]
        return [StreetSuggestion(name=s) for s in sorted(streets.keys())]

    async def get_home_num(
        self,
        city: str,
        street: str,
        *,
        update_fact: str | None = None,
    ) -> HomeNumResponse:
        """Return hardcoded house numbers and schedule for the given city and street."""
        return _make_home_num_response(city, street)

    async def get_group_by_address(
        self,
        city: str,
        street: str,
        house_number: str,
        *,
        update_fact: str | None = None,
        response: HomeNumResponse | None = None,
    ) -> AddressResult:
        """Return the hardcoded disconnection group for a given address."""
        resolved = response or _make_home_num_response(city, street)
        entry = resolved.find_house(house_number)
        group_id = (entry.primary_group if entry else None) or "GPV3.1"
        group_name = resolved.preset.sch_names.get(group_id, "") if resolved.preset else ""
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
        response: HomeNumResponse | None = None,
    ) -> dict[str, SlotStatus] | None:
        """Return today's slot map for one address."""
        resolved = response or _make_home_num_response(city, street)
        entry = resolved.find_house(house_number)
        if not entry or not entry.primary_group or not resolved.fact:
            return None
        return resolved.fact.get_group_today(entry.primary_group)

    async def get_tomorrow_schedule(
        self,
        city: str,
        street: str,
        house_number: str,
        *,
        update_fact: str | None = None,
        response: HomeNumResponse | None = None,
    ) -> dict[str, SlotStatus] | None:
        """Return tomorrow's slot map for one address."""
        resolved = response or _make_home_num_response(city, street)
        entry = resolved.find_house(house_number)
        if not entry or not entry.primary_group or not resolved.fact:
            return None
        tomorrow_date = resolved.fact.today_date + datetime.timedelta(days=1)
        return resolved.fact.get_group_for_date(tomorrow_date, entry.primary_group)

    async def get_schedule_for_date(
        self,
        city: str,
        street: str,
        house_number: str,
        date: datetime.date,
        *,
        update_fact: str | None = None,
        response: HomeNumResponse | None = None,
    ) -> dict[str, SlotStatus] | None:
        """Return the slot map for a specific calendar date."""
        resolved = response or _make_home_num_response(city, street)
        entry = resolved.find_house(house_number)
        if not entry or not entry.primary_group or not resolved.fact:
            return None
        return resolved.fact.get_group_for_date(date, entry.primary_group)

    @staticmethod
    def get_available_fact_dates(response: Any) -> list[datetime.date]:
        """Return all calendar dates available in a HomeNumResponse.fact."""
        if response.fact is None:
            return []
        tz = ZoneInfo(DEFAULT_TIMEZONE)
        dates: list[datetime.date] = []
        for ts_str in response.fact.days:
            try:
                ts = int(ts_str)
                d = datetime.datetime.fromtimestamp(ts, tz=tz).date()
                dates.append(d)
            except (ValueError, OSError):
                continue
        return sorted(dates)

    @property
    def site_key(self) -> str:
        """The site_key this stub is configured for."""
        return self._site_key

    @property
    def base_url(self) -> str:
        """Base URL for the configured region (from DTEK_SITES)."""
        return DTEK_SITES.get(self._site_key, ("https://stub.example.com", ""))[0]

    @property
    def ajax_url(self) -> str | None:
        """Always None because the stub does not use an AJAX endpoint."""
        return None
