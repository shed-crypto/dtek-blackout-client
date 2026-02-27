"""Pydantic models for dtek-blackout-client."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


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
