"""Pydantic models for dtek-blackout-client.

Terminology (as returned by the DTEK site):
    preset   - static weekly outage plan
    fact     - confirmed daily schedule (published by NPC Ukrenerho)
    slot     - a 30-minute or 60-minute time interval key
    group_id - disconnection group identifier (e.g. "GPV3.1")

All models are frozen=True so instances can be safely shared across tasks.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from .const import DEFAULT_TIMEZONE

_LOGGER = logging.getLogger(__name__)

# Latin letters frequently typed in place of visually identical Cyrillic letters
# in Ukrainian building numbers (e.g. "8a" vs "8а").
_HOUSE_LOOKALIKES = str.maketrans("aceiopxkmhtby", "асеіорхкмнтву")


def normalize_house_key(number: str) -> str:
    """Normalize a house number for tolerant comparison across scripts and spacing."""
    return "".join(number.split()).casefold().translate(_HOUSE_LOOKALIKES)


class _FrozenModel(BaseModel):
    model_config = {
        "frozen": True,
        "extra": "ignore",
        "populate_by_name": True,
    }


class SlotStatus(StrEnum):
    """Status values for a time-slot cell in the DTEK schedule table."""

    YES = "yes"
    NO = "no"
    MAYBE = "maybe"
    FIRST = "first"
    SECOND = "second"
    MFIRST = "mfirst"
    MSECOND = "msecond"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> SlotStatus:
        """Return UNKNOWN for any unrecognised slot value."""
        return cls.UNKNOWN

    @property
    def has_outage(self) -> bool:
        """True if this slot definitely has an outage (NO, FIRST, or SECOND)."""
        return self in (SlotStatus.NO, SlotStatus.FIRST, SlotStatus.SECOND)

    @property
    def may_have_outage(self) -> bool:
        """True if this slot has a definite or possible outage."""
        return self in (
            SlotStatus.NO,
            SlotStatus.FIRST,
            SlotStatus.SECOND,
            SlotStatus.MAYBE,
            SlotStatus.MFIRST,
            SlotStatus.MSECOND,
        )


class WeekDaySchedule(_FrozenModel):
    """Schedule for one disconnection group on one day of the week."""

    slots: dict[str, SlotStatus] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_slots(cls, data: Any) -> Any:
        """Accept a raw {slot_key: str_value} dict from the AJAX response."""
        if not isinstance(data, dict):
            return data
        if "slots" in data and isinstance(data["slots"], dict):
            return {
                "slots": {
                    str(k): SlotStatus(v) for k, v in data["slots"].items() if isinstance(v, str)
                }
            }
        return {"slots": {str(k): SlotStatus(v) for k, v in data.items() if isinstance(v, str)}}

    @property
    def outage_slot_count(self) -> int:
        """Number of slots with a definite outage."""
        return sum(1 for s in self.slots.values() if s.has_outage)

    @property
    def has_any_outage(self) -> bool:
        """True if at least one slot has a definite outage."""
        return self.outage_slot_count > 0


class GroupWeekSchedule(_FrozenModel):
    """Weekly planned schedule for one disconnection group."""

    group_id: str
    days: dict[int, WeekDaySchedule] = Field(default_factory=dict)

    def get_day(self, dtek_weekday: int) -> WeekDaySchedule | None:
        """Return the schedule for a given DTEK weekday (1-7)."""
        return self.days.get(dtek_weekday)


class PresetSchedule(_FrozenModel):
    """Full static (planned) weekly schedule as returned in ``preset``."""

    groups: dict[str, GroupWeekSchedule] = Field(default_factory=dict)
    time_zone: dict[str, str] = Field(default_factory=dict)
    sch_names: dict[str, str] = Field(default_factory=dict)
    days: dict[int, str] = Field(default_factory=dict)
    is_active: bool = True

    @model_validator(mode="before")
    @classmethod
    def _parse_preset(cls, data: Any) -> Any:
        """Parse the raw AJAX preset dict into structured model fields."""
        if not isinstance(data, dict):
            return data

        raw_data = data.get("data", {})

        if isinstance(raw_data, list):
            if len(raw_data) > 0:
                _LOGGER.warning("preset.data is a non-empty list. Unexpected DTEK API format.")
            raw_data = {}

        groups: dict[str, GroupWeekSchedule] = {}

        if isinstance(raw_data, dict):
            for group_id, day_map in raw_data.items():
                if not isinstance(day_map, dict):
                    continue
                days_parsed: dict[int, WeekDaySchedule] = {}
                for day_str, slot_map in day_map.items():
                    try:
                        day_idx = int(day_str)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(slot_map, dict):
                        days_parsed[day_idx] = WeekDaySchedule.model_validate(slot_map)
                groups[group_id] = GroupWeekSchedule(group_id=group_id, days=days_parsed)

        raw_tz = data.get("time_zone", {})
        if isinstance(raw_tz, list):
            raw_tz = {}
        time_zone = (
            {
                str(k): (str(v[0]) if isinstance(v, list) and v else str(v))
                for k, v in raw_tz.items()
            }
            if isinstance(raw_tz, dict)
            else {}
        )

        raw_days = data.get("days", {})
        if isinstance(raw_days, list):
            raw_days = {}
        days_out = {
            int(k): str(v)
            for k, v in raw_days.items()
            if isinstance(raw_days, dict) and str(k).isdigit()
        }

        sch_names = data.get("sch_names", {})
        if isinstance(sch_names, list):
            sch_names = {}

        is_active = bool(time_zone) and bool(raw_data)

        return {
            "groups": groups,
            "time_zone": time_zone,
            "sch_names": (
                {str(k): str(v) for k, v in sch_names.items()}
                if isinstance(sch_names, dict)
                else {}
            ),
            "days": days_out,
            "is_active": is_active,
        }

    @property
    def available_groups(self) -> list[str]:
        """Sorted list of group IDs present in this schedule."""
        return sorted(self.groups.keys())


class FactDaySchedule(_FrozenModel):
    """Confirmed schedule for one group on one specific calendar day."""

    group_id: str
    day_ts: int
    slots: dict[str, SlotStatus] = Field(default_factory=dict)

    @property
    def outage_slot_count(self) -> int:
        """Number of slots with a definite outage."""
        return sum(1 for s in self.slots.values() if s.has_outage)

    @property
    def has_any_outage(self) -> bool:
        """True if at least one slot has a definite outage."""
        return self.outage_slot_count > 0

    @property
    def day_date(self) -> datetime:
        """Return the day timestamp as a UTC datetime."""
        return datetime.fromtimestamp(self.day_ts, tz=UTC)


class FactSchedule(_FrozenModel):
    """Confirmed actual schedule for today and tomorrow from ``fact``."""

    today_ts: int
    update: str | None = None
    days: dict[str, dict[str, dict[str, SlotStatus]]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _parse_fact(cls, data: Any) -> Any:
        """Parse the raw AJAX fact dict into structured model fields."""
        if not isinstance(data, dict):
            return data

        raw_data = data.get("data", {})

        if isinstance(raw_data, list):
            if len(raw_data) > 0:
                _LOGGER.warning("fact.data is a non-empty list. Unexpected DTEK API format.")
            raw_data = {}

        days: dict[str, dict[str, dict[str, SlotStatus]]] = {}

        if isinstance(raw_data, dict):
            for ts_str, group_map in raw_data.items():
                if not isinstance(group_map, dict):
                    continue
                day_entry: dict[str, dict[str, SlotStatus]] = {}
                for group_id, slot_map in group_map.items():
                    if not isinstance(slot_map, dict):
                        continue
                    day_entry[group_id] = {str(k): SlotStatus(v) for k, v in slot_map.items()}
                days[str(ts_str)] = day_entry

        return {
            "today_ts": int(data.get("today", 0)),
            "update": data.get("update"),
            "days": days,
        }

    @property
    def today_date(self) -> date:
        """Return today's local calendar date in Europe/Kyiv timezone."""
        return datetime.fromtimestamp(self.today_ts, tz=ZoneInfo(DEFAULT_TIMEZONE)).date()

    def get_group_today(self, group_id: str) -> dict[str, SlotStatus] | None:
        """Return today's slot map for a group, or None if unavailable."""
        ts_str = str(self.today_ts)
        day = self.days.get(ts_str)
        if day is not None:
            return day.get(group_id)
        if self.today_ts <= 0:
            return None
        return self.get_group_for_date(self.today_date, group_id)

    def get_group_day(self, ts: int, group_id: str) -> dict[str, SlotStatus] | None:
        """Return the slot map for a specific day timestamp and group."""
        return self.days.get(str(ts), {}).get(group_id)

    def get_group_for_date(
        self,
        target_date: date,
        group_id: str,
        *,
        tz_name: str = DEFAULT_TIMEZONE,
    ) -> dict[str, SlotStatus] | None:
        """Return the slot map for a calendar date and group.

        Matches day keys by converting each Unix timestamp to a local date in
        ``tz_name`` so DST transitions (23-hour and 25-hour days) never shift
        midnight lookups by an hour.
        """
        tz = ZoneInfo(tz_name)
        for ts_str, group_map in self.days.items():
            try:
                ts = int(ts_str)
                day_date = datetime.fromtimestamp(ts, tz=tz).date()
            except (ValueError, OSError, OverflowError):
                continue
            if day_date == target_date:
                return group_map.get(group_id)
        return None


def _build_house_entry(house_num: str, raw_entry: Any) -> HouseEntry | None:
    """Build a HouseEntry from a single dict or a list of outage dicts."""
    records: list[dict[str, Any]]
    if isinstance(raw_entry, dict):
        records = [raw_entry]
    elif isinstance(raw_entry, list):
        records = [r for r in raw_entry if isinstance(r, dict)]
    else:
        return None

    if not records:
        return None

    group_ids: list[str] = []
    for rec in records:
        reasons = rec.get("sub_type_reason")
        if isinstance(reasons, list):
            for gid in reasons:
                gid_str = str(gid)
                if gid_str and gid_str not in group_ids:
                    group_ids.append(gid_str)

    # Prefer the record that carries an active outage reason or start_date.
    primary_rec = next(
        (r for r in records if r.get("sub_type") or r.get("start_date")),
        records[0],
    )
    external = any(bool(r.get("cek")) for r in records)

    return HouseEntry(
        house_number=house_num,
        group_ids=group_ids,
        sub_type=str(primary_rec.get("sub_type") or ""),
        start_date=str(primary_rec.get("start_date") or ""),
        end_date=str(primary_rec.get("end_date") or ""),
        type=str(primary_rec.get("type") or ""),
        voluntarily=primary_rec.get("voluntarily"),
        external_operator=external,
    )


class HouseEntry(_FrozenModel):
    """One house from the ``getHomeNum`` AJAX response."""

    house_number: str
    group_ids: list[str] = Field(default_factory=list)
    sub_type: str = ""
    start_date: str = ""
    end_date: str = ""
    outage_type: str = Field(default="", alias="type")
    voluntarily: bool | None = None
    external_operator: bool = False

    @property
    def is_multi_group(self) -> bool:
        """True if this address belongs to more than one disconnection group."""
        return len(self.group_ids) > 1

    @property
    def is_excluded(self) -> bool:
        """True if this address is not assigned to any outage group."""
        return len(self.group_ids) == 0

    @property
    def primary_group(self) -> str | None:
        """Return the first group_id, or None if excluded."""
        return self.group_ids[0] if self.group_ids else None

    @property
    def has_current_outage(self) -> bool:
        """True if the site reports a current outage for this address."""
        return bool(self.sub_type) or bool(self.start_date)

    def __str__(self) -> str:
        if self.is_excluded:
            return f"{self.house_number} -> (not in schedule)"
        if self.is_multi_group:
            return f"{self.house_number} -> groups: {', '.join(self.group_ids)}"
        return f"{self.house_number} -> group: {self.primary_group}"


class HomeNumResponse(_FrozenModel):
    """Full parsed response from the ``getHomeNum`` AJAX call."""

    houses: dict[str, HouseEntry] = Field(default_factory=dict)
    preset: PresetSchedule | None = None
    fact: FactSchedule | None = None
    show_cur_schedule: bool = Field(default=False, alias="showCurSchedule")
    show_cur_outage_param: bool = Field(default=False, alias="showCurOutageParam")
    show_table_plan: bool = Field(default=False, alias="showTablePlan")
    show_table_fact: bool = Field(default=False, alias="showTableFact")
    show_table_schedule: bool = Field(default=False, alias="showTableSchedule")
    update_timestamp: str | None = Field(default=None, alias="updateTimestamp")

    @model_validator(mode="before")
    @classmethod
    def _parse_response(cls, data: Any) -> Any:
        """Parse the raw AJAX dict into typed houses, preset, and fact."""
        if not isinstance(data, dict):
            return data

        raw_data = data.get("data", {})
        houses: dict[str, HouseEntry] = {}

        if isinstance(raw_data, list):
            for entry in raw_data:
                if not isinstance(entry, dict):
                    continue
                house_num = (
                    entry.get("num")
                    or entry.get("house_num")
                    or entry.get("house_number")
                    or entry.get("name")
                    or entry.get("id")
                )
                if house_num is None:
                    _LOGGER.warning(
                        "getHomeNum list item has no recognised house-number key: %s", entry
                    )
                    continue
                hn_str = str(house_num)
                built = _build_house_entry(hn_str, entry)
                if built is not None:
                    houses[hn_str] = built
        elif isinstance(raw_data, dict):
            for house_num, entry in raw_data.items():
                hn_str = str(house_num)
                built = _build_house_entry(hn_str, entry)
                if built is not None:
                    houses[hn_str] = built
        else:
            _LOGGER.warning("getHomeNum: unexpected 'data' type: %s", type(raw_data))

        result = dict(data)
        result["houses"] = houses

        if "preset" in data and isinstance(data["preset"], dict):
            result["preset"] = PresetSchedule.model_validate(data["preset"])
        if "fact" in data and isinstance(data["fact"], dict):
            result["fact"] = FactSchedule.model_validate(data["fact"])

        return result

    def find_house(self, house_number: str) -> HouseEntry | None:
        """Find a house entry by number, tolerating case, spaces, and Latin lookalikes.

        An exact key match always takes priority.
        """
        if (exact := self.houses.get(house_number)) is not None:
            return exact
        wanted = normalize_house_key(house_number)
        if not wanted:
            return None
        matches = [
            entry for key, entry in self.houses.items() if normalize_house_key(key) == wanted
        ]
        return matches[0] if matches else None

    def get_group_for_house(self, house_number: str) -> str | None:
        """Return the primary group_id for a house number, or None."""
        entry = self.find_house(house_number)
        if entry is None:
            return None
        return entry.primary_group

    @property
    def available_houses(self) -> list[str]:
        """Sorted list of all house numbers in this response."""
        return sorted(self.houses.keys())


class StreetSuggestion(_FrozenModel):
    """One street returned by the ``getStreets`` AJAX call."""

    name: str

    def __str__(self) -> str:
        return self.name


class AddressResult(_FrozenModel):
    """Result of a full address lookup (site -> city -> street -> house -> group)."""

    site_key: str
    city: str
    street: str
    house_number: str
    group_id: str
    group_display_name: str = ""

    def __str__(self) -> str:
        label = self.group_display_name or self.group_id
        return f"{self.city}, {self.street}, {self.house_number} -> {label}"
