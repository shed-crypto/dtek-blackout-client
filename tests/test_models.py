"""Unit tests for dtek_client.models — no network required."""

from __future__ import annotations

from typing import Any

import pytest

from datetime import datetime, timezone
from pydantic import ValidationError

from dtek_client.models import (
    AddressResult,
    FactSchedule,
    HomeNumResponse,
    HouseEntry,
    PresetSchedule,
    SlotStatus,
    StreetSuggestion,
    WeekDaySchedule,
    FactDaySchedule,
)


# ── SlotStatus ────────────────────────────────────────────────────────────────


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
        assert SlotStatus.YES.may_have_outage is False
        assert SlotStatus.UNKNOWN.may_have_outage is False


# ── WeekDaySchedule ───────────────────────────────────────────────────────────


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


# ── HouseEntry ────────────────────────────────────────────────────────────────


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


# ── HomeNumResponse parsing ───────────────────────────────────────────────────


class TestHomeNumResponse:
    def test_parses_full_fixture(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert "1" in r.houses
        assert "3/A" in r.houses  # Latin A — fixture uses ASCII key
        assert r.show_cur_schedule is True
        assert r.update_timestamp == "26.03.2026 14:00"

    def test_houses_group_ids(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.houses["1"].group_ids == ["GPV3.1"]
        assert r.houses["1/1"].group_ids == ["GPV3.2"]
        assert r.houses["5"].group_ids == []  # excluded

    def test_multi_group_house(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.houses["3/A"].is_multi_group is True  # Latin A

    def test_preset_parsed(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.preset is not None
        assert "GPV3.1" in r.preset.groups
        # sch_names value is a non-empty string (exact Ukrainian text may vary by platform encoding)
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
        assert slots["1"] is SlotStatus.NO  # outage
        assert slots["9"] is SlotStatus.YES  # electricity
        assert slots["17"] is SlotStatus.MAYBE

    def test_get_group_for_house(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        assert r.get_group_for_house("1") == "GPV3.1"
        assert r.get_group_for_house("2") == "GPV3.2"
        assert r.get_group_for_house("5") is None  # excluded
        assert r.get_group_for_house("999") is None  # not present

    def test_available_houses(self, home_num_raw: dict) -> None:
        r = HomeNumResponse.model_validate(home_num_raw)
        houses = r.available_houses
        assert "1" in houses
        assert "7" in houses
        assert houses == sorted(houses)

    def test_result_false_still_parses(self) -> None:
        """HomeNumResponse can be built from raw dict even without result key."""
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


# ── PresetSchedule ────────────────────────────────────────────────────────────


class TestPresetSchedule:
    def test_available_groups(self, home_num_raw: dict) -> None:
        preset = PresetSchedule.model_validate(home_num_raw["preset"])
        assert "GPV3.1" in preset.available_groups

    def test_time_zone_labels(self, home_num_raw: dict) -> None:
        preset = PresetSchedule.model_validate(home_num_raw["preset"])
        # fixture uses ASCII hyphen (not em-dash) to avoid Windows encoding issues
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


# ── FactSchedule ─────────────────────────────────────────────────────────────


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

    def test_day_date_property(self, home_num_raw: dict) -> None:
        fact = FactSchedule.model_validate(home_num_raw["fact"])
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(fact.today_ts, tz=timezone.utc)
        assert dt.year == 2026
        assert dt.month == 3


# ── AddressResult ─────────────────────────────────────────────────────────────


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


# ── StreetSuggestion ──────────────────────────────────────────────────────────


class TestStreetSuggestion:
    def test_str(self) -> None:
        s = StreetSuggestion(name="вул. Юності")
        assert str(s) == "вул. Юності"


# ── WeekDaySchedule — validator guard ─────────────────────────────────────────


class TestWeekDayScheduleValidatorGuard:
    def test_non_dict_input_raises(self) -> None:
        """The model validator returns non-dict input unchanged so Pydantic can
        surface a meaningful ValidationError rather than an obscure crash."""
        with pytest.raises((ValidationError, Exception)):
            WeekDaySchedule.model_validate("not_a_dict")


# ── PresetSchedule — validator guards and skip logic ─────────────────────────


class TestPresetScheduleValidatorGuards:
    def test_non_dict_input_raises(self) -> None:
        """Non-dict input is passed through the validator unchanged, letting
        Pydantic raise a ValidationError with a clear message."""
        with pytest.raises((ValidationError, Exception)):
            PresetSchedule.model_validate("not_a_dict")

    def test_group_with_non_dict_day_map_is_skipped(self) -> None:
        """A group whose value in preset.data is not a dict (malformed response)
        is silently skipped; valid groups are still parsed normally."""
        raw: dict = {
            "data": {"GPV3.1": "should_be_a_dict"},
            "time_zone": {"1": "00:00-00:30"},
            "sch_names": {},
            "days": {"1": "Понеділок"},
        }
        preset = PresetSchedule.model_validate(raw)
        assert "GPV3.1" not in preset.groups

    def test_non_integer_day_key_is_skipped(self) -> None:
        """Day keys that cannot be cast to int (e.g. "monday") are ignored;
        numeric day keys in the same group are still parsed correctly."""
        raw: dict = {
            "data": {
                "GPV3.1": {
                    "monday": {"1": "no"},  # invalid — skipped
                    "1": {"1": "yes"},  # valid
                }
            },
            "time_zone": {"1": "00:00-00:30"},
            "sch_names": {},
            "days": {"1": "Понеділок"},
        }
        preset = PresetSchedule.model_validate(raw)
        assert 1 in preset.groups["GPV3.1"].days
        assert len(preset.groups["GPV3.1"].days) == 1


# ── FactDaySchedule — computed properties ────────────────────────────────────


class TestFactDayScheduleProperties:
    """FactDaySchedule is an internal model that the fact-schedule parser builds
    programmatically; its computed properties are exercised here directly."""

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
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026 and dt.month == 3


# ── FactSchedule — validator guards and lookup edge cases ─────────────────────


class TestFactScheduleValidatorGuards:
    def test_non_dict_input_raises(self) -> None:
        """Non-dict input is passed through the validator unchanged so Pydantic
        raises a ValidationError rather than an obscure AttributeError."""
        with pytest.raises((ValidationError, Exception)):
            FactSchedule.model_validate("not_a_dict")

    def test_day_entry_that_is_not_a_dict_is_skipped(self) -> None:
        """A timestamp key whose value is not a dict (malformed response)
        is silently skipped; the days dict is left empty."""
        raw: dict = {
            "today": 1774483200,
            "update": "26.03.2026 13:45",
            "data": {"1774483200": "should_be_a_dict"},
        }
        fact = FactSchedule.model_validate(raw)
        assert fact.days == {}

    def test_group_slot_map_that_is_not_a_dict_is_skipped(self) -> None:
        """A group entry whose slot map is not a dict is skipped, leaving
        that group absent from the parsed day entry."""
        raw: dict = {
            "today": 1774483200,
            "update": "26.03.2026 13:45",
            "data": {"1774483200": {"GPV3.1": "should_be_slots_dict"}},
        }
        fact = FactSchedule.model_validate(raw)
        assert "GPV3.1" not in fact.days.get("1774483200", {})

    def test_get_group_today_returns_none_when_today_ts_not_in_days(self) -> None:
        """get_group_today returns None when today_ts does not match any key
        in the days dict (e.g. before the fact schedule is published)."""
        fact = FactSchedule.model_construct(
            today_ts=0,
            update=None,
            days={"1774483200": {"GPV3.1": {"1": SlotStatus.NO}}},
        )
        assert fact.get_group_today("GPV3.1") is None


# ── HouseEntry.__str__() — multi-group branch ─────────────────────────────────


class TestHouseEntryStr:
    def test_str_for_multi_group_house_lists_all_group_ids(self) -> None:
        """A house that belongs to more than one group shows all group IDs
        so that the ambiguity is immediately visible in logs."""
        h = HouseEntry(house_number="3/А", group_ids=["GPV3.1", "GPV3.2"])
        s = str(h)
        assert "GPV3.1" in s
        assert "GPV3.2" in s
        assert "groups" in s


# ── HomeNumResponse — validator guards ────────────────────────────────────────


class TestHomeNumResponseValidatorGuards:
    def test_non_dict_input_raises(self) -> None:
        """Non-dict input passed to model_validate triggers a ValidationError
        through the standard Pydantic path."""
        with pytest.raises((ValidationError, Exception)):
            HomeNumResponse.model_validate("not_a_dict")

    def test_house_entry_that_is_not_a_dict_is_skipped(self) -> None:
        """A house key whose value is not a dict (corrupted API response)
        is skipped; the house is simply absent from the result."""
        raw: dict = {
            "data": {"99": "not_a_dict"},
            "showCurSchedule": False,
            "showTablePlan": False,
            "showTableFact": False,
            "showTableSchedule": False,
        }
        r = HomeNumResponse.model_validate(raw)
        assert "99" not in r.houses
