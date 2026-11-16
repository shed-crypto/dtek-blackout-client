"""Unit tests for StubDtekClient."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from dtek_client.const import DEFAULT_TIMEZONE
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

    async def test_none_city_returns_all_unique_streets(self) -> None:
        async with StubDtekClient() as c:
            streets = await c.get_streets()
            all_map = await c.get_all_streets()
        assert len(streets) >= 4
        assert "м. Українка" in all_map

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
        stub = StubDtekClient("unknown_key_xyz")
        assert "stub.example.com" in stub.base_url


class TestStubGetTomorrowSchedule:
    async def test_returns_dict_or_none(self) -> None:
        async with StubDtekClient() as c:
            result = await c.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert result is None or isinstance(result, dict)

    async def test_stub_includes_tomorrow_in_fact(self) -> None:
        async with StubDtekClient() as c:
            result = await c.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        assert result is not None

    async def test_slot_values_are_slot_status(self) -> None:
        async with StubDtekClient() as c:
            result = await c.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        if result is not None:
            for v in result.values():
                assert isinstance(v, SlotStatus)

    async def test_slot_count_is_48(self) -> None:
        async with StubDtekClient() as c:
            result = await c.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        if result is not None:
            assert len(result) == 48

    async def test_unknown_house_returns_none(self) -> None:
        async with StubDtekClient() as c:
            result = await c.get_tomorrow_schedule("м. Українка", "вул. Юності", "999")
        assert result is None

    async def test_unknown_city_does_not_raise(self) -> None:
        async with StubDtekClient() as c:
            result = await c.get_tomorrow_schedule("місто-нема", "вул. Нема", "1")
        assert result is None or isinstance(result, dict)

    async def test_different_from_today_schedule(self) -> None:
        async with StubDtekClient() as c:
            today = await c.get_today_schedule("м. Українка", "вул. Юності", "1")
            tomorrow = await c.get_tomorrow_schedule("м. Українка", "вул. Юності", "1")
        if today is not None and tomorrow is not None:
            assert today is not tomorrow


class TestStubGetScheduleForDate:
    async def _today_date(self) -> datetime.date:
        async with StubDtekClient() as c:
            r = await c.get_home_num("м. Українка", "вул. Юності")
        assert r.fact is not None
        return r.fact.today_date

    async def test_today_equals_get_today_schedule(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_home_num("м. Українка", "вул. Юності")
            assert r.fact is not None
            today = r.fact.today_date
            direct = await c.get_today_schedule("м. Українка", "вул. Юності", "1", response=r)
            via_dt = await c.get_schedule_for_date(
                "м. Українка", "вул. Юності", "1", today, response=r
            )
        assert direct == via_dt

    async def test_tomorrow_equals_get_tomorrow_schedule(self) -> None:
        async with StubDtekClient() as c:
            r = await c.get_home_num("м. Українка", "вул. Юності")
            assert r.fact is not None
            tomorrow = r.fact.today_date + datetime.timedelta(days=1)
            via_tmrw = await c.get_tomorrow_schedule("м. Українка", "вул. Юності", "1", response=r)
            via_date = await c.get_schedule_for_date(
                "м. Українка", "вул. Юності", "1", tomorrow, response=r
            )
        assert via_tmrw == via_date

    async def test_date_not_in_fact_returns_none(self) -> None:
        far_future = datetime.date(2099, 1, 1)
        async with StubDtekClient() as c:
            result = await c.get_schedule_for_date("м. Українка", "вул. Юності", "1", far_future)
        assert result is None

    async def test_returns_dict_or_none(self) -> None:
        today = await self._today_date()
        async with StubDtekClient() as c:
            result = await c.get_schedule_for_date("м. Українка", "вул. Юності", "1", today)
        assert result is None or isinstance(result, dict)

    async def test_slot_values_are_slot_status_when_found(self) -> None:
        today = await self._today_date()
        async with StubDtekClient() as c:
            result = await c.get_schedule_for_date("м. Українка", "вул. Юності", "1", today)
        if result is not None:
            for v in result.values():
                assert isinstance(v, SlotStatus)

    async def test_unknown_house_returns_none(self) -> None:
        today = await self._today_date()
        async with StubDtekClient() as c:
            result = await c.get_schedule_for_date("м. Українка", "вул. Юності", "999", today)
        assert result is None

    async def test_accepts_datetime_date_object(self) -> None:
        today = await self._today_date()
        assert isinstance(today, datetime.date)
        async with StubDtekClient() as c:
            result = await c.get_schedule_for_date("м. Українка", "вул. Юності", "1", today)
        assert result is None or isinstance(result, dict)


class TestStubGetAvailableFactDates:
    async def _response(self) -> HomeNumResponse:
        async with StubDtekClient() as c:
            return await c.get_home_num("м. Українка", "вул. Юності")

    async def test_returns_list_of_dates(self) -> None:
        r = await self._response()
        dates = StubDtekClient.get_available_fact_dates(r)
        assert isinstance(dates, list)
        assert all(isinstance(d, datetime.date) for d in dates)

    async def test_stub_has_at_least_two_dates(self) -> None:
        r = await self._response()
        dates = StubDtekClient.get_available_fact_dates(r)
        assert len(dates) >= 2

    async def test_dates_are_sorted_ascending(self) -> None:
        r = await self._response()
        dates = StubDtekClient.get_available_fact_dates(r)
        assert dates == sorted(dates)

    async def test_today_is_in_dates(self) -> None:
        r = await self._response()
        assert r.fact is not None
        today = datetime.datetime.fromtimestamp(
            r.fact.today_ts, tz=ZoneInfo(DEFAULT_TIMEZONE)
        ).date()
        dates = StubDtekClient.get_available_fact_dates(r)
        assert today in dates

    async def test_tomorrow_is_in_dates(self) -> None:
        r = await self._response()
        assert r.fact is not None
        today = datetime.datetime.fromtimestamp(
            r.fact.today_ts, tz=ZoneInfo(DEFAULT_TIMEZONE)
        ).date()
        tomorrow = today + datetime.timedelta(days=1)
        dates = StubDtekClient.get_available_fact_dates(r)
        assert tomorrow in dates

    async def test_no_fact_returns_empty_list(self) -> None:
        response = HomeNumResponse.model_construct(
            houses={},
            preset=None,
            fact=None,
            show_cur_schedule=False,
            show_table_plan=False,
            show_table_fact=False,
            show_table_schedule=False,
            update_timestamp="",
        )
        result = StubDtekClient.get_available_fact_dates(response)
        assert result == []

        from dtek_client.models import FactSchedule

        bad_fact = FactSchedule.model_construct(
            today_ts=1774483200,
            update=None,
            days={"not_a_number": {}},
        )
        bad_resp = HomeNumResponse.model_construct(houses={}, preset=None, fact=bad_fact)
        assert StubDtekClient.get_available_fact_dates(bad_resp) == []

    async def test_get_today_schedule_returns_none_for_unknown_house(self) -> None:
        async with StubDtekClient() as c:
            assert await c.get_today_schedule("м. Українка", "вул. Юності", "999") is None

    async def test_dates_count_matches_fact_days(self) -> None:
        r = await self._response()
        assert r.fact is not None
        dates = StubDtekClient.get_available_fact_dates(r)
        assert len(dates) == len(r.fact.days)
