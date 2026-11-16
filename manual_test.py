"""Manual verification script for dtek-blackout-client against stub and live sites."""

from __future__ import annotations

import asyncio
import datetime
import logging
import re

from dtek_client import DtekClient
from dtek_client.models import HouseEntry, SlotStatus, StreetSuggestion
from dtek_client.stub_client import StubDtekClient

logging.basicConfig(level=logging.INFO)


def suggest_streets(all_streets: list[StreetSuggestion], query: str) -> list[str]:
    """Filter streets by a case-insensitive substring query."""
    q = query.lower().strip()
    return [s.name for s in all_streets if q in s.name.lower()]


def suggest_houses(all_houses: dict[str, HouseEntry], query: str) -> list[str]:
    """Filter house numbers by a substring query and sort numerically where possible."""
    q = query.lower().strip()

    def sort_key(key: str) -> tuple[int, str]:
        nums = re.findall(r"\d+", key)
        return (int(nums[0]) if nums else 9999, key)

    matched = [h for h in all_houses if q in h.lower()]
    return sorted(matched, key=sort_key)


def _format_slot_marker(status: SlotStatus) -> str:
    if status.has_outage:
        return "[OUT]"
    if status.may_have_outage:
        return "[MAY]"
    return "[ON ]"


async def test_stub() -> None:
    print("\n=== TEST: StubDtekClient ===")
    async with StubDtekClient("kem") as client:
        streets = await client.get_streets("м. Українка")
        print("Streets in Ukrainka:", [s.name for s in streets])

        response = await client.get_home_num("м. Українка", "вул. Юності")
        for house, entry in sorted(response.houses.items()):
            status = "excluded" if entry.is_excluded else entry.primary_group
            print(f"  House {house:6s} -> {status}")

        slots = await client.get_today_schedule(
            "м. Українка", "вул. Юності", "1", response=response
        )
        if slots and response.preset:
            for key, slot_status in list(slots.items())[:6]:
                label = response.preset.time_zone.get(key, key)
                print(f"  {_format_slot_marker(slot_status)} {label:15s} {slot_status.value}")

        address_result = await client.get_group_by_address(
            "м. Українка", "вул. Юності", "1/1", response=response
        )
        print("Address lookup:", address_result)


async def test_krem() -> None:
    print("\n=== TEST: DTEK Kyiv Regional Networks (krem) ===")
    async with DtekClient("krem") as client:
        streets = await client.get_streets("м. Фастів")
        print(f"Found {len(streets)} streets in Fastiv. First 5:")
        for s in streets[:5]:
            print(f"  {s.name}")

        response = await client.get_home_num("м. Фастів", "вул. Шевченка")
        print(f"Found {len(response.houses)} houses on Shevchenka street.")
        for house, entry in sorted(response.houses.items())[:10]:
            status = "excluded" if entry.is_excluded else entry.primary_group
            print(f"  {house:6s} -> {status}")

        slots = await client.get_today_schedule(
            "м. Фастів", "вул. Шевченка", "13", response=response
        )
        if slots and response.preset:
            print("Today schedule for house 13:")
            for key, slot_status in slots.items():
                label = response.preset.time_zone.get(key, key)
                print(f"  {_format_slot_marker(slot_status)} {label:15s} {slot_status.value}")
        else:
            print("Today schedule is not published.")


async def test_oem() -> None:
    print("\n=== TEST: DTEK Odesa Networks (oem) ===")
    async with DtekClient("oem") as client:
        response = await client.get_home_num("м. Одеса", "вул. Героїв оборони Одеси")
        house_entry = response.find_house("14")
        if house_entry is None:
            print("House 14 not found.")
            return
        print(f"House 14 group: {house_entry.primary_group}")
        slots = await client.get_today_schedule(
            "м. Одеса", "вул. Героїв оборони Одеси", "14", response=response
        )
        if slots and response.preset:
            for key, slot_status in list(slots.items())[:8]:
                label = response.preset.time_zone.get(key, key)
                print(f"  {_format_slot_marker(slot_status)} {label:15s} {slot_status.value}")


async def test_kem() -> None:
    print("\n=== TEST: DTEK Kyiv City Networks (kem) ===")
    async with DtekClient("kem") as client:
        streets = await client.get_streets()
        print(f"Found {len(streets)} streets in Kyiv. First 5:")
        for s in streets[:5]:
            print(f"  {s.name}")

        test_street = "вул. Хрещатик"
        response = await client.get_home_num("м. Київ", test_street)
        print(
            f"Found {len(response.houses)} houses on {test_street} "
            f"(updated: {response.update_timestamp})"
        )

        dates = client.get_available_fact_dates(response)
        if dates and response.fact:
            today = response.fact.today_date
            for d in dates:
                marker = (
                    " (today)"
                    if d == today
                    else (" (tomorrow)" if d == today + datetime.timedelta(days=1) else "")
                )
                day_slots = await client.get_schedule_for_date(
                    "м. Київ", test_street, "1", d, response=response
                )
                outages = sum(1 for v in (day_slots or {}).values() if v.has_outage)
                print(f"  Date {d}{marker}: {len(day_slots or {})} slots, {outages} outage slots")


async def main() -> None:
    await test_stub()
    await test_krem()
    await test_oem()
    await test_kem()


if __name__ == "__main__":
    asyncio.run(main())
