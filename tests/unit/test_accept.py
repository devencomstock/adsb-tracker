"""Acceptance rules on hand-picked frames (docs/pseudocode.md stage 4)."""

from decoder.accept import How, accept
from decoder.frame import Frame
from decoder.recent import RecentlySeen

DF17_CLEAN = Frame.from_hex("8f4d2023587f345e35837e2218b2")
DF11_CLEAN = Frame.from_hex("5d4d20237a55a6")
DF11_ID_1 = Frame.from_hex("5d4d20237a55a7")  # remainder 1: interrogator ID 1, or bit 55 flipped
DF4_PARITY = Frame.from_hex("20000f1f684a6c")  # remainder 4d2023 = its address


def test_clean_df17_is_accepted_and_listed() -> None:
    recent = RecentlySeen()
    result = accept(DF17_CLEAN, recent, 0.0, fix=False)
    assert result is not None and result.how is How.CLEAN and result.icao == 0x4D2023
    assert recent.seen(0x4D2023, 0.0)


def test_address_parity_needs_a_listed_address() -> None:
    recent = RecentlySeen()
    assert accept(DF4_PARITY, recent, 0.0, fix=False) is None
    accept(DF17_CLEAN, recent, 0.0, fix=False)
    result = accept(DF4_PARITY, recent, 0.0, fix=False)
    assert result is not None and result.how is How.ADDRESS_PARITY and result.icao == 0x4D2023


def test_interrogator_id_needs_a_listed_address() -> None:
    recent = RecentlySeen()
    assert accept(DF11_ID_1, recent, 0.0, fix=False) is None
    accept(DF11_CLEAN, recent, 0.0, fix=False)
    result = accept(DF11_ID_1, recent, 0.0, fix=False)
    assert result is not None and result.how is How.INTERROGATOR_ID and result.interrogator_id == 1


def test_repair_runs_before_the_interrogator_id_rule() -> None:
    recent = RecentlySeen()
    accept(DF11_CLEAN, recent, 0.0, fix=True)
    result = accept(DF11_ID_1, recent, 0.0, fix=True)
    assert result is not None and result.how is How.REPAIRED and result.repaired_bit == 55
    assert result.frame == DF11_CLEAN


def test_repaired_frame_does_not_list_its_address() -> None:
    recent = RecentlySeen()
    broken = DF17_CLEAN.flip(40)
    result = accept(broken, recent, 0.0, fix=True)
    assert result is not None and result.how is How.REPAIRED and result.frame == DF17_CLEAN
    assert not recent.seen(0x4D2023, 0.0)


def test_broken_df17_is_rejected_without_fix() -> None:
    assert accept(DF17_CLEAN.flip(40), RecentlySeen(), 0.0, fix=False) is None


def test_expired_address_is_not_trusted() -> None:
    recent = RecentlySeen()
    accept(DF17_CLEAN, recent, 0.0, fix=False)
    assert accept(DF4_PARITY, recent, 60.5, fix=False) is None
