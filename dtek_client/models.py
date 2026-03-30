"""Pydantic models for dtek-blackout-client.

Terminology (as returned by the DTEK site):
    preset   – static weekly outage plan
    fact     – confirmed daily schedule (published by NPC Ukrenerho)
    slot     – a 30-minute time interval (e.g. "00:00–00:30")
    group_id – disconnection group identifier (e.g. "GPV3.1")

Slot status values:
    yes     → electricity available (no outage)
    no      → definite outage for the whole slot
    maybe   → possible outage for the whole slot
    first   → outage in the first half of the slot (~15 min)
    second  → outage in the second half of the slot (~15 min)
    mfirst  → possible outage in the first half
    msecond → possible outage in the second half

All models are frozen=True — safe to pass between coroutines.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class _FrozenModel(BaseModel):
    model_config = {  # type: ignore[assignment]
        "frozen": True,
        "extra": "ignore",
        "populate_by_name": True,
    }


# ── Slot status enum ──────────────────────────────────────────────────────────


class SlotStatus(StrEnum):
    """Possible status values for a time-slot cell in the DTEK schedule table."""

    YES = "yes"  # Electricity available — no outage
    NO = "no"  # Definite outage for the whole slot
    MAYBE = "maybe"  # Possible outage for the whole slot
    FIRST = "first"  # Outage in the first half of the slot (~15 min)
    SECOND = "second"  # Outage in the second half of the slot (~15 min)
    MFIRST = "mfirst"  # Possible outage in the first half
    MSECOND = "msecond"  # Possible outage in the second half
    UNKNOWN = "unknown"  # Fallback for unrecognised values

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
        """True if this slot has a definite OR possible outage."""
        return self in (
            SlotStatus.NO,
            SlotStatus.FIRST,
            SlotStatus.SECOND,
            SlotStatus.MAYBE,
            SlotStatus.MFIRST,
            SlotStatus.MSECOND,
        )


# ── Weekly planned schedule (preset.data) ─────────────────────────────────────


class WeekDaySchedule(_FrozenModel):
    """Schedule for one disconnection group on one day of the week.

    ``slots`` maps a time-zone key (e.g. "1", "2", …, "48") to a SlotStatus.
    The human-readable time labels (e.g. "00:00–00:30") live in
    ``PresetSchedule.time_zone``.
    """

    slots: dict[str, SlotStatus] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_slots(cls, data: Any) -> Any:
        """Accept a raw {slot_key: str_value} dict from the AJAX response."""
        if not isinstance(data, dict):
            return data
        return {"slots": {k: SlotStatus(v) for k, v in data.items() if isinstance(v, str)}}

    @property
    def outage_slot_count(self) -> int:
        """Number of slots with a definite outage."""
        return sum(1 for s in self.slots.values() if s.has_outage)

    @property
    def has_any_outage(self) -> bool:
        """True if at least one slot has a definite outage."""
        return self.outage_slot_count > 0


class GroupWeekSchedule(_FrozenModel):
    """Weekly planned schedule for one disconnection group.

    ``days`` maps a DTEK day-index (1=Mon, …, 7=Sun) to a WeekDaySchedule.
    """

    group_id: str
    days: dict[int, WeekDaySchedule] = Field(default_factory=dict)

    def get_day(self, dtek_weekday: int) -> WeekDaySchedule | None:
        """Return the schedule for a given DTEK weekday (1–7)."""
        return self.days.get(dtek_weekday)


class PresetSchedule(_FrozenModel):
    """Full static (planned) weekly schedule as returned in ``preset``.

    Attributes:
        groups    – dict of group_id → GroupWeekSchedule
        time_zone – time-slot labels, e.g. {"1": "00:00–00:30", …}
        sch_names – group display names, e.g. {"GPV3.1": "Черга 3.1"}
        days      – day names, e.g. {1: "Понеділок", …}
        is_active – False if the schedule is empty or inactive
    """

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

        raw_data: dict = data.get("data", {})
        groups: dict[str, GroupWeekSchedule] = {}

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

        # time_zone values may be arrays like ["00:00–00:30", "00:00"] — take first.
        raw_tz: dict = data.get("time_zone", {})
        time_zone = {k: (v[0] if isinstance(v, list) else str(v)) for k, v in raw_tz.items()}

        # days may come with string keys {"1": "Понеділок", …}.
        raw_days: dict = data.get("days", {})
        days_out = {int(k): str(v) for k, v in raw_days.items() if str(k).isdigit()}

        sch_names: dict = data.get("sch_names", {})

        # is_active: False when time_zone or data is empty.
        is_active = bool(time_zone) and bool(raw_data)

        return {
            "groups": groups,
            "time_zone": time_zone,
            "sch_names": {str(k): str(v) for k, v in sch_names.items()},
            "days": days_out,
            "is_active": is_active,
        }

    @property
    def available_groups(self) -> list[str]:
        """Sorted list of group IDs present in this schedule."""
        return sorted(self.groups.keys())


# ── Actual (fact) schedule ────────────────────────────────────────────────────


class FactDaySchedule(_FrozenModel):
    """Actual confirmed schedule for one group on one specific calendar day.

    ``slots`` maps a time-zone key to a SlotStatus (same keys as preset.time_zone).
    """

    group_id: str
    day_ts: int  # Unix timestamp of the day (midnight Kyiv time)
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
        """Return the day as a UTC datetime."""
        return datetime.fromtimestamp(self.day_ts, tz=UTC)


class FactSchedule(_FrozenModel):
    """Confirmed actual schedule for today (and possibly tomorrow) from ``fact``.

    ``days`` maps unix-timestamp strings to per-group slot maps.
    ``today_ts`` is the unix timestamp of today (from ``fact.today``).
    ``update`` is the last-updated timestamp string from the site.
    """

    today_ts: int
    update: str | None = None
    # Structure: {ts_str: {group_id: {tz_key: SlotStatus}}}
    days: dict[str, dict[str, dict[str, SlotStatus]]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _parse_fact(cls, data: Any) -> Any:
        """Parse the raw AJAX fact dict into structured model fields."""
        if not isinstance(data, dict):
            return data

        raw_data: dict = data.get("data", {})
        days: dict[str, dict[str, dict[str, SlotStatus]]] = {}

        for ts_str, group_map in raw_data.items():
            if not isinstance(group_map, dict):
                continue
            day_entry: dict[str, dict[str, SlotStatus]] = {}
            for group_id, slot_map in group_map.items():
                if not isinstance(slot_map, dict):
                    continue
                day_entry[group_id] = {k: SlotStatus(v) for k, v in slot_map.items()}
            days[ts_str] = day_entry

        return {
            "today_ts": int(data.get("today", 0)),
            "update": data.get("update"),
            "days": days,
        }

    def get_group_today(self, group_id: str) -> dict[str, SlotStatus] | None:
        """Return today's slot map for a group, or None if unavailable."""
        ts_str = str(self.today_ts)
        day = self.days.get(ts_str)
        if day is None:
            return None
        return day.get(group_id)

    def get_group_day(self, ts: int, group_id: str) -> dict[str, SlotStatus] | None:
        """Return the slot map for a specific day (by unix timestamp) and group."""
        return self.days.get(str(ts), {}).get(group_id)


# ── House entry (from getHomeNum response) ────────────────────────────────────


class HouseEntry(_FrozenModel):
    """One house from the ``getHomeNum`` AJAX response.

    Attributes:
        house_number  – key from the ``data`` dict (e.g. "1", "1A", "3/B")
        group_ids     – list from ``sub_type_reason`` (e.g. ["GPV3.1"])
        is_multi_group – True when len(group_ids) > 1
        is_excluded    – True when group_ids is empty (address not in schedule)
        sub_type       – non-empty when there is a current planned outage reason
        outage_type    – "1" = planned works, "2" = other
    """

    house_number: str
    group_ids: list[str] = Field(default_factory=list)
    sub_type: str = ""
    start_date: str = ""
    end_date: str = ""
    outage_type: str = Field(default="", alias="type")
    voluntarily: bool | None = None

    @property
    def is_multi_group(self) -> bool:
        """True if this address belongs to more than one disconnection group."""
        return len(self.group_ids) > 1

    @property
    def is_excluded(self) -> bool:
        """True if this address is not in any outage group."""
        return len(self.group_ids) == 0

    @property
    def primary_group(self) -> str | None:
        """Return the first group_id, or None if excluded."""
        return self.group_ids[0] if self.group_ids else None

    @property
    def has_current_outage(self) -> bool:
        """True if the site reports a current (non-scheduled) outage for this address."""
        return bool(self.sub_type) or bool(self.start_date)

    def __str__(self) -> str:
        if self.is_excluded:
            return f"{self.house_number} → (not in schedule)"
        if self.is_multi_group:
            return f"{self.house_number} → groups: {', '.join(self.group_ids)}"
        return f"{self.house_number} → group: {self.primary_group}"


# ── Full getHomeNum response ───────────────────────────────────────────────────


class HomeNumResponse(_FrozenModel):
    """Full parsed response from the ``getHomeNum`` AJAX call.

    Attributes:
        houses              – dict of house_number → HouseEntry
        preset              – static weekly schedule (or None if not returned)
        fact                – confirmed daily schedule (or None if not returned)
        show_cur_schedule   – True if the site currently shows the schedule table
        show_table_plan     – True if the static plan table should be shown
        show_table_fact     – True if the fact table should be shown
        show_table_schedule – True if the schedule table should be shown
        update_timestamp    – display string like "26.03.2026 14:00"
    """

    houses: dict[str, HouseEntry] = Field(default_factory=dict)
    preset: PresetSchedule | None = None
    fact: FactSchedule | None = None
    show_cur_schedule: bool = Field(default=False, alias="showCurSchedule")
    show_table_plan: bool = Field(default=False, alias="showTablePlan")
    show_table_fact: bool = Field(default=False, alias="showTableFact")
    show_table_schedule: bool = Field(default=False, alias="showTableSchedule")
    update_timestamp: str | None = Field(default=None, alias="updateTimestamp")

    @model_validator(mode="before")
    @classmethod
    def _parse_response(cls, data: Any) -> Any:
        """Parse the raw AJAX dict into typed houses, preset and fact."""
        if not isinstance(data, dict):
            return data

        raw_data: dict = data.get("data", {})
        houses: dict[str, HouseEntry] = {}
        for house_num, entry in raw_data.items():
            if not isinstance(entry, dict):
                continue
            houses[house_num] = HouseEntry(
                house_number=house_num,
                group_ids=entry.get("sub_type_reason", []),
                sub_type=entry.get("sub_type", ""),
                start_date=entry.get("start_date", ""),
                end_date=entry.get("end_date", ""),
                type=entry.get("type", ""),
                voluntarily=entry.get("voluntarily"),
            )

        result = dict(data)
        result["houses"] = houses

        # Parse preset and fact if present in the raw dict.
        if "preset" in data and isinstance(data["preset"], dict):
            result["preset"] = PresetSchedule.model_validate(data["preset"])
        if "fact" in data and isinstance(data["fact"], dict):
            result["fact"] = FactSchedule.model_validate(data["fact"])

        return result

    def get_group_for_house(self, house_number: str) -> str | None:
        """Return the primary group_id for a house number, or None."""
        entry = self.houses.get(house_number)
        if entry is None:
            return None
        return entry.primary_group

    @property
    def available_houses(self) -> list[str]:
        """Sorted list of all house numbers in this response."""
        return sorted(self.houses.keys())


# ── Street suggestion ─────────────────────────────────────────────────────────


class StreetSuggestion(_FrozenModel):
    """One street returned by the ``getStreets`` AJAX call.

    The DTEK site returns a plain list of street name strings.
    """

    name: str

    def __str__(self) -> str:
        return self.name


# ── Address lookup result ─────────────────────────────────────────────────────


class AddressResult(_FrozenModel):
    """Result of a full address lookup (site → city → street → house → group).

    This is the high-level return value of ``DtekClient.get_group_by_address()``.
    """

    site_key: str
    city: str
    street: str
    house_number: str
    group_id: str
    group_display_name: str = ""

    def __str__(self) -> str:
        label = self.group_display_name or self.group_id
        return f"{self.city}, {self.street}, {self.house_number} → {label}"
