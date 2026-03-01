"""Pydantic models for dtek-blackout-client."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, model_validator


class _FrozenModel(BaseModel):
    model_config = {  # type: ignore[assignment]
        "frozen": True,
        "extra": "ignore",
        "populate_by_name": True,
    }


# ── Slot status enum ──────────────────────────────────────────────────────────

class SlotStatus(str, Enum):
    """Possible status values for a time-slot cell in the DTEK schedule table."""

    YES = "yes"
    NO = "no"
    MAYBE = "maybe"
    FIRST = "first"
    SECOND = "second"
    MFIRST = "mfirst"
    MSECOND = "msecond"
    UNKNOWN = "unknown"

    @classmethod
    def _missing_(cls, value: object) -> "SlotStatus":
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
            SlotStatus.NO, SlotStatus.FIRST, SlotStatus.SECOND,
            SlotStatus.MAYBE, SlotStatus.MFIRST, SlotStatus.MSECOND,
        )


# ── Weekly planned schedule (preset.data) ─────────────────────────────────────

class WeekDaySchedule(_FrozenModel):
    """Schedule for one disconnection group on one day of the week."""

    slots: dict[str, SlotStatus] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_slots(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {
            "slots": {
                k: SlotStatus(v)
                for k, v in data.items()
                if isinstance(v, str)
            }
        }

    @property
    def outage_slot_count(self) -> int:
        return sum(1 for s in self.slots.values() if s.has_outage)

    @property
    def has_any_outage(self) -> bool:
        return self.outage_slot_count > 0

class GroupWeekSchedule(_FrozenModel):
    group_id: str
    days: dict[int, WeekDaySchedule] = Field(default_factory=dict)

    def get_day(self, dtek_weekday: int) -> WeekDaySchedule | None:
        """Return the schedule for a given DTEK weekday (1–7)."""
        return self.days.get(dtek_weekday)
    
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
