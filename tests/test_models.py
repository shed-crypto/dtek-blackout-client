"""Unit tests for dtek_client.models."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from dtek_client.models import (
    AddressResult,
    FactDaySchedule,
    FactSchedule,
    HomeNumResponse,
    HouseEntry,
    PresetSchedule,
    SlotStatus,
    StreetSuggestion,
    WeekDaySchedule,
    normalize_house_key,
)


class TestSlotStatus:
    def test_known_values_parse(self) -> None:
        assert SlotStatus("yes") is SlotStatus.YES
        assert SlotStatus("no") is SlotStatus.NO
        assert SlotStatus("maybe") is SlotStatus.MAYBE
        assert SlotStatus("first") is SlotStatus.FIRST
        assert SlotStatus("second") is SlotStatus.SECOND
        assert SlotStatus("mfirst") is SlotStatus.MFIRST
        assert SlotStatus("msecond") is SlotStatus.MSECOND

    def test_unknown_value_returns_unknown(self) -> None:
        assert SlotStatus("something_new") is SlotStatus.UNKNOWN

    def test_has_outage(self) -> None:
        assert SlotStatus.NO.has_outage is True
        assert SlotStatus.FIRST.has_outage is True
        assert SlotStatus.SECOND.has_outage is True
        assert SlotStatus.YES.has_outage is False
        assert SlotStatus.MAYBE.has_outage is False

    def test_may_have_outage(self) -> None:
        assert SlotStatus.MAYBE.may_have_outage is True
        assert SlotStatus.MFIRST.may_have_outage is True
        assert SlotStatus.MSECOND.may_have_outage is True
        assert SlotStatus.YES.may_have_outage is False
        assert SlotStatus.UNKNOWN.may_have_outage is False


class TestWeekDaySchedule:
    def test_coerces_string_values(self) -> None:
        raw = {"1": "no", "2": "yes", "3": "maybe"}
        wd = WeekDaySchedule.model_validate(raw)
        assert wd.slots["1"] is SlotStatus.NO
        assert wd.slots["2"] is SlotStatus.YES
        assert wd.slots["3"] is SlotStatus.MAYBE

    def test_outage_slot_count(self) -> None:
        raw = {"1": "no", "2": "no", "3": "yes", "4": "first"}
        wd = WeekDaySchedule.model_validate(raw)
        assert wd.outage_slot_count == 3

    def test_has_any_outage_true(self) -> None:
        wd = WeekDaySchedule.model_validate({"1": "no"})
        assert wd.has_any_outage is True

    def test_has_any_outage_false(self) -> None:
        wd = WeekDaySchedule.model_validate({"1": "yes", "2": "maybe"})
        assert wd.has_any_outage is False

    def test_empty_slots(self) -> None:
        wd = WeekDaySchedule(slots={})
        assert wd.has_any_outage is False
        assert wd.outage_slot_count == 0


class TestHouseEntry:
    def test_single_group(self) -> None:
        h = HouseEntry(house_number="10", group_ids=["GPV3.1"])
        assert h.primary_group == "GPV3.1"
        assert h.is_multi_group is False
        assert h.is_excluded is False

    def test_multi_group(self) -> None:
        h = HouseEntry(house_number="3/А", group_ids=["GPV3.1", "GPV3.2"])
        assert h.is_multi_group is True
        assert h.primary_group == "GPV3.1"

    def test_excluded(self) -> None:
        h = HouseEntry(house_number="5", group_ids=[])
        assert h.is_excluded is True
        assert h.primary_group is None

    def test_has_current_outage(self) -> None:
        h = HouseEntry(
            house_number="7",
            group_ids=["GPV3.1"],
            sub_type="Планові роботи",
            start_date="26.03.2026 09:00",
        )
        assert h.has_current_outage is True

    def test_no_current_outage(self) -> None:
        h = HouseEntry(house_number="1", group_ids=["GPV3.1"])
        assert h.has_current_outage is False

    def test_str_single(self) -> None:
        h = HouseEntry(house_number="10", group_ids=["GPV3.1"])
        assert "GPV3.1" in str(h)

    def test_str_excluded(self) -> None:
        h = HouseEntry(house_number="5", group_ids=[])
        assert "not in schedule" in str(h)


class TestHomeNumResponse:
    def test_parses_full_fixture(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert "1" in r.houses
        assert "3/A" in r.houses
        assert r.show_cur_schedule is True
        assert r.update_timestamp == "26.03.2026 14:00"

    def test_houses_group_ids(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.houses["1"].group_ids == ["GPV3.1"]
        assert r.houses["1/1"].group_ids == ["GPV3.2"]
        assert r.houses["5"].group_ids == []

    def test_multi_group_house(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.houses["3/A"].is_multi_group is True

    def test_preset_parsed(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.preset is not None
        assert "GPV3.1" in r.preset.groups
        assert "GPV3.1" in r.preset.sch_names
        assert len(r.preset.sch_names["GPV3.1"]) > 0

    def test_fact_parsed(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.fact is not None
        assert r.fact.today_ts == 1774483200

    def test_fact_today_slots(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.fact is not None
        slots = r.fact.get_group_today("GPV3.1")
        assert slots is not None
        assert slots["1"] is SlotStatus.NO
        assert slots["9"] is SlotStatus.YES
        assert slots["17"] is SlotStatus.MAYBE

    def test_get_group_for_house(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.get_group_for_house("1") == "GPV3.1"
        assert r.get_group_for_house("2") == "GPV3.2"
        assert r.get_group_for_house("5") is None
        assert r.get_group_for_house("999") is None

    def test_find_house_matches_cyrillic_and_latin_lookalikes(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        # Fixture key is "3/A" with Latin A; querying with Cyrillic "3/а" or spaces must match.
        entry = r.find_house(" 3/а ")
        assert entry is not None
        assert entry.house_number == "3/A"
        assert r.get_group_for_house("3/А") == "GPV3.1"
        assert r.find_house("   ") is None

    def test_parses_house_with_multiple_outage_records_and_cek(self) -> None:
        raw = {
            "data": {
                "12а": [
                    {
                        "sub_type_reason": ["GPV1.1"],
                        "sub_type": "",
                        "start_date": "",
                        "end_date": "",
                        "type": "",
                        "cek": None,
                    },
                    {
                        "sub_type_reason": ["GPV1.2"],
                        "sub_type": "Аварійні роботи",
                        "start_date": "10:00 16.11.2026",
                        "end_date": "14:00 16.11.2026",
                        "type": "2",
                        "cek": True,
                    },
                ]
            },
            "showCurOutageParam": True,
        }
        r = HomeNumResponse.model_validate(raw)
        assert r.show_cur_outage_param is True
        house = r.find_house("12A")
        assert house is not None
        assert house.group_ids == ["GPV1.1", "GPV1.2"]
        assert house.sub_type == "Аварійні роботи"
        assert house.external_operator is True

    def test_parses_top_level_list_data_format(self) -> None:
        raw = {
            "data": [
                {"num": "7", "sub_type_reason": ["GPV2.1"], "sub_type": ""},
                {"invalid": "no_num_key"},
                "not_a_dict",
            ]
        }
        r = HomeNumResponse.model_validate(raw)
        assert "7" in r.houses
        assert r.houses["7"].primary_group == "GPV2.1"

    def test_available_houses(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        houses = r.available_houses
        assert "1" in houses
        assert "7" in houses
        assert houses == sorted(houses)

    def test_result_false_still_parses(self) -> None:
        raw: dict = {
            "data": {
                "10": {
                    "sub_type_reason": ["GPV3.1"],
                    "sub_type": "",
                    "start_date": "",
                    "end_date": "",
                    "type": "",
                    "voluntarily": None,
                }
            },
            "showCurSchedule": False,
            "showTablePlan": False,
            "showTableFact": False,
            "showTableSchedule": False,
        }
        r = HomeNumResponse.model_validate(raw)
        assert "10" in r.houses


class TestPresetSchedule:
    def test_available_groups(self, home_num_raw: dict) -> None:
        preset = PresetSchedule.model_validate(home_num_raw["preset"])
        assert "GPV3.1" in preset.available_groups

    def test_time_zone_labels(self, home_num_raw: dict) -> None:
        preset = PresetSchedule.model_validate(home_num_raw["preset"])
        assert preset.time_zone["1"] == "00:00-00:30"

    def test_is_active_true(self, home_num_raw: dict) -> None:
        preset = PresetSchedule.model_validate(home_num_raw["preset"])
        assert preset.is_active is True

    def test_is_active_false_empty_data(self) -> None:
        raw = {"data": {}, "time_zone": {}, "sch_names": {}, "days": {}}
        preset = PresetSchedule.model_validate(raw)
        assert preset.is_active is False

    def test_day_schedule_access(self, home_num_raw: dict) -> None:
        preset = PresetSchedule.model_validate(home_num_raw["preset"])
        g = preset.groups["GPV3.1"]
        monday = g.get_day(1)
        assert monday is not None
        assert monday.slots["1"] is SlotStatus.NO


class TestFactSchedule:
    def test_parses_raw(self, home_num_raw: dict) -> None:
        fact = FactSchedule.model_validate(home_num_raw["fact"])
        assert fact.today_ts == 1774483200
        assert fact.update == "26.03.2026 13:45"

    def test_get_group_today_found(self, home_num_raw: dict) -> None:
        fact = FactSchedule.model_validate(home_num_raw["fact"])
        slots = fact.get_group_today("GPV3.1")
        assert slots is not None
        assert slots["1"] is SlotStatus.NO

    def test_get_group_today_wrong_group(self, home_num_raw: dict) -> None:
        fact = FactSchedule.model_validate(home_num_raw["fact"])
        assert fact.get_group_today("GPV99.99") is None

    def test_get_group_day_found(self, home_num_raw: dict) -> None:
        fact = FactSchedule.model_validate(home_num_raw["fact"])
        slots = fact.get_group_day(1774483200, "GPV3.2")
        assert slots is not None
        assert slots["9"] is SlotStatus.NO

    def test_get_group_day_not_found(self, home_num_raw: dict) -> None:
        fact = FactSchedule.model_validate(home_num_raw["fact"])
        assert fact.get_group_day(0, "GPV3.1") is None

    def test_get_group_for_date_across_spring_dst_transition(self) -> None:
        """On 2026-03-29 Europe/Kyiv springs forward (23-hour day = 82800s).

        Looking up tomorrow (2026-03-30) by calendar date must find the
        midnight timestamp 1774818000 even though 1774735200 + 86400 != 1774818000.
        """
        tz = ZoneInfo("Europe/Kyiv")
        ts_mar_29 = int(datetime(2026, 3, 29, 0, 0, tzinfo=tz).timestamp())
        ts_mar_30 = int(datetime(2026, 3, 30, 0, 0, tzinfo=tz).timestamp())
        assert ts_mar_30 - ts_mar_29 == 82800

        fact = FactSchedule.model_validate(
            {
                "today": ts_mar_29,
                "update": "29.03.2026 18:00",
                "data": {
                    str(ts_mar_29): {"GPV3.1": {"1": "yes"}},
                    str(ts_mar_30): {"GPV3.1": {"1": "no"}},
                },
            }
        )
        slots_mar_30 = fact.get_group_for_date(date(2026, 3, 30), "GPV3.1")
        assert slots_mar_30 == {"1": SlotStatus.NO}
        assert fact.get_group_for_date(date(2026, 3, 31), "GPV3.1") is None

    def test_day_date_property(self, home_num_raw: dict) -> None:
        fact = FactSchedule.model_validate(home_num_raw["fact"])
        dt = datetime.fromtimestamp(fact.today_ts, tz=UTC)
        assert dt.year == 2026
        assert dt.month == 3


class TestAddressResult:
    def test_str(self) -> None:
        r = AddressResult(
            site_key="kem",
            city="м. Українка",
            street="вул. Юності",
            house_number="10",
            group_id="GPV3.1",
            group_display_name="Черга 3.1",
        )
        s = str(r)
        assert "Юності" in s
        assert "Черга 3.1" in s

    def test_str_no_display_name(self) -> None:
        r = AddressResult(
            site_key="kem",
            city="м. Київ",
            street="вул. Хрещатик",
            house_number="1",
            group_id="GPV3.1",
        )
        assert "GPV3.1" in str(r)


class TestStreetSuggestion:
    def test_str(self) -> None:
        s = StreetSuggestion(name="вул. Юності")
        assert str(s) == "вул. Юності"


class TestWeekDayScheduleValidatorGuard:
    def test_non_dict_input_raises(self) -> None:
        with pytest.raises((ValidationError, Exception)):
            WeekDaySchedule.model_validate("not_a_dict")


class TestPresetScheduleValidatorGuards:
    def test_non_dict_input_raises(self) -> None:
        with pytest.raises((ValidationError, Exception)):
            PresetSchedule.model_validate("not_a_dict")

    def test_non_empty_list_data_logs_warning_and_returns_empty(self) -> None:
        raw: dict = {
            "data": ["unexpected"],
            "time_zone": {"1": "00:00-00:30"},
            "sch_names": {},
            "days": {"1": "Понеділок"},
        }
        preset = PresetSchedule.model_validate(raw)
        assert preset.groups == {}
        assert preset.is_active is False

    def test_group_with_non_dict_day_map_is_skipped(self) -> None:
        raw: dict = {
            "data": {"GPV3.1": "should_be_a_dict"},
            "time_zone": {"1": "00:00-00:30"},
            "sch_names": {},
            "days": {"1": "Понеділок"},
        }
        preset = PresetSchedule.model_validate(raw)
        assert "GPV3.1" not in preset.groups

    def test_non_integer_day_key_is_skipped(self) -> None:
        raw: dict = {
            "data": {
                "GPV3.1": {
                    "monday": {"1": "no"},
                    "1": {"1": "yes"},
                }
            },
            "time_zone": {"1": "00:00-00:30"},
            "sch_names": {},
            "days": {"1": "Понеділок"},
        }
        preset = PresetSchedule.model_validate(raw)
        assert 1 in preset.groups["GPV3.1"].days
        assert len(preset.groups["GPV3.1"].days) == 1


class TestFactDayScheduleProperties:
    def _make(self, slots: dict[str, SlotStatus]) -> FactDaySchedule:
        return FactDaySchedule(group_id="GPV3.1", day_ts=1774483200, slots=slots)

    def test_outage_slot_count_counts_definite_outages_only(self) -> None:
        fd = self._make({"1": SlotStatus.NO, "2": SlotStatus.YES, "3": SlotStatus.FIRST})
        assert fd.outage_slot_count == 2

    def test_has_any_outage_true_when_at_least_one_no_slot(self) -> None:
        assert self._make({"1": SlotStatus.NO}).has_any_outage is True

    def test_has_any_outage_false_when_only_yes_and_maybe(self) -> None:
        fd = self._make({"1": SlotStatus.YES, "2": SlotStatus.MAYBE})
        assert fd.has_any_outage is False

    def test_day_date_returns_utc_aware_datetime(self) -> None:
        dt = self._make({}).day_date
        assert isinstance(dt, datetime)
        assert dt.tzinfo == UTC
        assert dt.year == 2026 and dt.month == 3


class TestFactScheduleValidatorGuards:
    def test_non_dict_input_raises(self) -> None:
        with pytest.raises((ValidationError, Exception)):
            FactSchedule.model_validate("not_a_dict")

    def test_non_empty_list_data_returns_empty_days(self) -> None:
        fact = FactSchedule.model_validate({"today": 1774483200, "data": ["unexpected"]})
        assert fact.days == {}

    def test_day_entry_that_is_not_a_dict_is_skipped(self) -> None:
        raw: dict = {
            "today": 1774483200,
            "update": "26.03.2026 13:45",
            "data": {"1774483200": "should_be_a_dict"},
        }
        fact = FactSchedule.model_validate(raw)
        assert fact.days == {}

    def test_group_slot_map_that_is_not_a_dict_is_skipped(self) -> None:
        raw: dict = {
            "today": 1774483200,
            "update": "26.03.2026 13:45",
            "data": {"1774483200": {"GPV3.1": "should_be_slots_dict"}},
        }
        fact = FactSchedule.model_validate(raw)
        assert "GPV3.1" not in fact.days.get("1774483200", {})

    def test_get_group_today_returns_none_when_today_ts_not_in_days(self) -> None:
        fact = FactSchedule.model_construct(
            today_ts=0,
            update=None,
            days={"1774483200": {"GPV3.1": {"1": SlotStatus.NO}}},
        )
        assert fact.get_group_today("GPV3.1") is None

    def test_get_group_for_date_ignores_invalid_timestamp_keys(self) -> None:
        fact = FactSchedule.model_construct(
            today_ts=1774483200,
            update=None,
            days={"not_an_int": {"GPV3.1": {"1": SlotStatus.NO}}},
        )
        assert fact.get_group_for_date(date(2026, 3, 26), "GPV3.1") is None


class TestHouseEntryStr:
    def test_str_for_multi_group_house_lists_all_group_ids(self) -> None:
        h = HouseEntry(house_number="3/А", group_ids=["GPV3.1", "GPV3.2"])
        s = str(h)
        assert "GPV3.1" in s
        assert "GPV3.2" in s
        assert "groups" in s


class TestHomeNumResponseValidatorGuards:
    def test_non_dict_input_raises(self) -> None:
        with pytest.raises((ValidationError, Exception)):
            HomeNumResponse.model_validate("not_a_dict")

    def test_house_entry_that_is_not_a_dict_is_skipped(self) -> None:
        raw: dict = {
            "data": {"99": "not_a_dict", "100": []},
            "showCurSchedule": False,
            "showTablePlan": False,
            "showTableFact": False,
            "showTableSchedule": False,
        }
        r = HomeNumResponse.model_validate(raw)
        assert "99" not in r.houses
        assert "100" not in r.houses

    def test_unexpected_data_type_leaves_houses_empty(self) -> None:
        raw: dict = {"data": "invalid_type"}
        r = HomeNumResponse.model_validate(raw)
        assert r.houses == {}


def test_fact_schedule_empty_list_fallback() -> None:
    raw = {"today": 12345, "update": "now", "data": []}
    fact = FactSchedule.model_validate(raw)
    assert fact.today_ts == 12345
    assert fact.days == {}


def test_preset_schedule_empty_list_fallback() -> None:
    raw = {"data": [], "time_zone": [], "days": [], "sch_names": []}
    preset = PresetSchedule.model_validate(raw)
    assert preset.groups == {}
    assert preset.time_zone == {}
    assert preset.is_active is False


def test_normalize_house_key_converts_latin_to_cyrillic() -> None:
    assert normalize_house_key(" 10 A ") == normalize_house_key("10а")
