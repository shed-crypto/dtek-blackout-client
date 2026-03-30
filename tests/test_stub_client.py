"""Unit tests for StubDtekClient."""

from __future__ import annotations

import pytest

from dtek_client.models import AddressResult, HomeNumResponse, SlotStatus, StreetSuggestion
from dtek_client.stub_client import StubDtekClient


class TestStubInterface:
    async def test_context_manager(self) -> None:
        async with StubDtekClient("kem") as c:
            assert c is not None

    async def test_connect_close_noop(self) -> None:
        c = StubDtekClient()
        await c.connect()
        await c.close()

    def test_site_key(self) -> None:
        assert StubDtekClient("dnem").site_key == "dnem"

    def test_base_url_has_domain(self) -> None:
        assert "dtek" in StubDtekClient("kem").base_url

    def test_ajax_url_is_none(self) -> None:
        assert StubDtekClient().ajax_url is None


class TestStubGetStreets:
    async def test_known_city_returns_streets(self) -> None:
        async with StubDtekClient() as c:
            streets = await c.get_streets("м. Українка")
        assert len(streets) > 0
        assert all(isinstance(s, StreetSuggestion) for s in streets)

    async def test_unknown_city_returns_fallback(self) -> None:
        async with StubDtekClient() as c:
            streets = await c.get_streets("невідоме місто")
        assert len(streets) >= 1

    async def test_streets_are_sorted(self) -> None:
        async with StubDtekClient() as c:
            streets = await c.get_streets("м. Українка")
        names = [s.name for s in streets]
        assert names == sorted(names)


class TestStubGetHomeNum:
    async def test_returns_home_num_response(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_home_num("м. Українка", "вул. Юності")
        assert isinstance(r, HomeNumResponse)

    async def test_houses_have_groups(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_home_num("м. Українка", "вул. Юності")
        for entry in r.houses.values():
            assert isinstance(entry.group_ids, list)

    async def test_preset_present(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_home_num("м. Українка", "вул. Юності")
        assert r.preset is not None
        assert r.preset.is_active is True

    async def test_fact_present(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_home_num("м. Українка", "вул. Юності")
        assert r.fact is not None
        assert r.fact.today_ts > 0

    async def test_unknown_street_still_works(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_home_num("м. Українка", "вул. Невідома")
        assert isinstance(r, HomeNumResponse)


class TestStubGetGroupByAddress:
    async def test_returns_address_result(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_group_by_address("м. Українка", "вул. Юності", "1")
        assert isinstance(r, AddressResult)
        assert r.group_id.startswith("GPV")

    async def test_city_and_street_in_result(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_group_by_address("м. Українка", "вул. Юності", "3")
        assert r.city == "м. Українка"
        assert r.street == "вул. Юності"
        assert r.house_number == "3"

    async def test_display_name_populated(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_group_by_address("м. Українка", "вул. Юності", "1")
        assert "Черга" in r.group_display_name or r.group_display_name == ""


class TestStubGetTodaySchedule:
    async def test_returns_slots_or_none(self) -> None:
        async with StubDtekClient() as c:
            result = await c.get_today_schedule("м. Українка", "вул. Юності", "1")
        assert result is None or isinstance(result, dict)

    async def test_slot_values_are_slot_status(self) -> None:
        async with StubDtekClient() as c:
            result = await c.get_today_schedule("м. Українка", "вул. Юності", "1")
        if result is not None:
            for v in result.values():
                assert isinstance(v, SlotStatus)


class TestStubProperties:
    def test_base_url_fallback_for_unrecognised_site_key(self) -> None:
        """When a site_key that does not exist in DTEK_SITES is passed (e.g.
        during testing with a dummy key), base_url returns the hardcoded
        fallback URL rather than raising an exception."""
        stub = StubDtekClient("unknown_key_xyz")
        assert "stub.example.com" in stub.base_url
