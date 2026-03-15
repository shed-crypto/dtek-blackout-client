"""Stub (hardcoded) implementation of DtekClient.

PURPOSE
-------
Teammates working on the Home Assistant integration can start coding
*immediately* without waiting for the real DTEK site to respond.
"""

from .models import StreetSuggestion, HomeNumResponse, AddressResult
from typing import Any

# ── Hardcoded API Response Mock Data ──────────────────────────────────────────

# Імітація відповіді на запит getStreets (список вулиць)
MOCK_STREETS_RESPONSE = [
    {"name": "вул. Юності"},
    {"name": "вул. Садова"},
    {"name": "вул. Паркова"},
    {"name": "пр. Незалежності"}
]

# Імітація тайм-зон, які приходять від DTEK (48 слотів по 30 хв)
MOCK_TIME_ZONE = {
    str(i): f"{((i-1)*30)//60:02d}:{((i-1)*30)%60:02d}–{((i*30))//60:02d}:{((i*30))%60:02d}"
    for i in range(1, 48)
}
MOCK_TIME_ZONE["48"] = "23:30–24:00"

# Імітація відповіді на запит getHomeNum (розклад та будинки)
MOCK_HOME_NUM_RESPONSE = {
    "houses": {
        "1": {"group_ids": ["GPV3.1"], "sub_type": "", "start_date": "", "end_date": "", "voluntarily": None},
        "2": {"group_ids": ["GPV3.2"], "sub_type": "", "start_date": "", "end_date": "", "voluntarily": None},
        "3": {"group_ids": ["GPV3.1"], "sub_type": "", "start_date": "", "end_date": "", "voluntarily": None},
    },
    "preset": {
        "time_zone": MOCK_TIME_ZONE,
        "sch_names": {
            "GPV3.1": "Черга планових відключень 3.1",
            "GPV3.2": "Черга планових відключень 3.2",
        },
        "days": {
            1: "Понеділок", 2: "Вівторок", 3: "Середа", 
            4: "Четвер", 5: "П'ятниця", 6: "Субота", 7: "Неділя"
        },
        # Спрощений приклад графіку на тиждень
        "groups": {
            "GPV3.1": {
                "group_id": "GPV3.1",
                "days": {
                    "1": {"slots": {str(i): "no" if i < 10 else "yes" for i in range(1, 49)}},
                    "2": {"slots": {str(i): "no" if 10 <= i < 20 else "yes" for i in range(1, 49)}},
                }
            }
        },
        "is_active": True
    },
    "fact": {
        "today_ts": 1709251200, # Приклад timestamp
        "update": "Stub data update",
        "days": {
            "1709251200": {
                 "GPV3.1": {str(i): "no" if i < 10 else "yes" for i in range(1, 49)}
            }
        }
    },
    "show_cur_schedule": True,
    "show_table_plan": True,
    "show_table_fact": True,
    "show_table_schedule": True,
    "update_timestamp": "2026-02-08 14:00:00"
}

# ── StubDtekClient ────────────────────────────────────────────────────────────

class StubDtekClient:
    """Drop-in replacement for DtekClient returning raw mock JSON data."""

    def __init__(self, site_key: str = "kem"):
        self.site_key = site_key

    async def connect(self) -> None:
        """No-op — stub requires no network connection."""
        pass

    async def close(self) -> None:
        """No-op — stub has no resources to release."""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def get_streets(self, city: str, **kwargs) -> list[StreetSuggestion]:
        """Return hardcoded list of StreetSuggestion objects."""
        return [StreetSuggestion(name=s["name"]) for s in MOCK_STREETS_RESPONSE]

    async def get_home_num(self, city: str, street: str, **kwargs) -> HomeNumResponse:
        """Return hardcoded HomeNumResponse model."""
        return HomeNumResponse.model_validate(MOCK_HOME_NUM_RESPONSE)

    async def get_group_by_address(self, city: str, street: str, house_number: str) -> AddressResult:
        response = await self.get_home_num(city, street)
        entry = response.houses.get(house_number)
        group_id = entry.primary_group if entry else "unknown"
        return AddressResult(
            site_key=self.site_key, city=city, street=street, 
            house_number=house_number, group_id=group_id
        )

    async def get_today_schedule(self, city: str, street: str, house_number: str) -> dict[str, Any] | None:
        response = await self.get_home_num(city, street)
        entry = response.houses.get(house_number)
        if entry and entry.primary_group and response.fact:
            return response.fact.get_group_today(entry.primary_group)
        return None