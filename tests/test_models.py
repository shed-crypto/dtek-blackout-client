import pytest
from dtek_client.models import (
    AddressResult,
    SlotStatus,
    StreetSuggestion,
)

def test_slot_status_enum():
    assert SlotStatus("yes") == SlotStatus.YES
    assert SlotStatus("msecond") == SlotStatus.MSECOND
    # Unrecognized values should fallback to UNKNOWN
    assert SlotStatus("some_weird_value") == SlotStatus.UNKNOWN

def test_slot_status_properties():
    assert SlotStatus.NO.has_outage is True
    assert SlotStatus.YES.has_outage is False
    assert SlotStatus.MAYBE.has_outage is False

    assert SlotStatus.NO.may_have_outage is True
    assert SlotStatus.MAYBE.may_have_outage is True
    assert SlotStatus.YES.may_have_outage is False

def test_street_suggestion():
    street = StreetSuggestion(name="Хрещатик")
    assert street.name == "Хрещатик"
    assert str(street) == "Хрещатик"

def test_address_result():
    res = AddressResult(
        site_key="kem",
        city="м. Київ",
        street="вул. Хрещатик",
        house_number="10",
        group_id="GPV1",
        group_display_name="Group 1",
    )
    assert res.site_key == "kem"
    assert "Хрещатик" in str(res)
    assert "Group 1" in str(res)