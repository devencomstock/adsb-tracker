"""Rejection behavior: frames that must NOT be accepted (checkpoint A review).

The golden files only hold frames dump1090 accepted, so they can't show false accepts. These
tests corrupt known-good frames and check that `accept` says no. They back decision #8's
"zero extra messages" rule once real, noisy samples arrive in checkpoint B.

Why two flipped bits can never pass as clean or repairable: the CRC is linear, so a corrupted
frame's remainder is the XOR of the remainders of its flipped bits.
`test_two_bit_errors_never_look_like_one_bit_errors` checks over every pair that this is never 0
(looks clean) and never equals a single-bit remainder (looks repairable), for both frame lengths.
"""

from __future__ import annotations

import random
from itertools import combinations

import pytest

from decoder.accept import INTERROGATOR_ID_LIMIT, How, accept
from decoder.crc import crc_remainder, repair_single_bit, single_bit_syndromes
from decoder.frame import Frame
from decoder.recent import RecentlySeen

ICAO = 0x4D2023
DF17_CLEAN = Frame.from_hex("8f4d2023587f345e35837e2218b2")
DF11_CLEAN = Frame.from_hex("5d4d20237a55a6")
DF4_PARITY = Frame.from_hex("20000f1f684a6c")  # remainder 4d2023 = its address


def _listed(icao: int = ICAO, t: float = 0.0) -> RecentlySeen:
    recent = RecentlySeen()
    recent.add(icao, t)
    return recent


def _flip_all(frame: Frame, bits: tuple[int, ...]) -> Frame:
    for bit in bits:
        frame = frame.flip(bit)
    return frame


@pytest.mark.parametrize("n_bits", [112, 56])
def test_two_bit_errors_never_look_like_one_bit_errors(n_bits: int) -> None:
    single = [crc_remainder(Frame(1 << (n_bits - 1 - bit), n_bits)) for bit in range(n_bits)]
    table = single_bit_syndromes(n_bits)
    for i, j in combinations(range(n_bits), 2):
        remainder = single[i] ^ single[j]
        assert remainder != 0, (i, j)
        assert remainder not in table, (i, j)


@pytest.mark.parametrize("fix", [False, True])
def test_every_two_bit_error_in_a_df17_is_rejected(fix: bool) -> None:
    # The remainder depends only on which bits flipped (linearity), so one frame covers all.
    for bits in combinations(range(112), 2):
        broken = _flip_all(DF17_CLEAN, bits)
        assert accept(broken, _listed(), 0.0, fix) is None, bits


@pytest.mark.parametrize("fix", [False, True])
def test_two_bit_errors_in_every_golden_df17_are_rejected(
    nofix_lines: list[str], fix: bool
) -> None:
    rng = random.Random(4)  # fixed seed: the same sample every run
    frames = [f for f in map(Frame.from_hex, nofix_lines) if f.df == 17]
    assert len(frames) == 120
    for frame in frames:
        for bits in rng.sample(list(combinations(range(112), 2)), 20):
            assert accept(_flip_all(frame, bits), _listed(), 0.0, fix) is None, (frame.hex, bits)


@pytest.mark.parametrize("fix", [False, True])
def test_two_bit_errors_in_a_df11_pass_only_as_a_small_interrogator_id(fix: bool) -> None:
    # A DF 11 with a listed address and remainder below 80 is read as an interrogator ID, so a
    # two-bit error inside the parity field (remainder 3, 5, 6 ...) legitimately gets through.
    # That is dump1090's rule, and the reason it also requires the address to be recently seen.
    # Everything else must be rejected, and the frame is never "repaired" or called clean.
    passed = 0
    for bits in combinations(range(56), 2):
        broken = _flip_all(DF11_CLEAN, bits)
        result = accept(broken, _listed(), 0.0, fix)
        if result is not None:
            assert result.how is How.INTERROGATOR_ID, bits
            assert crc_remainder(broken) < INTERROGATOR_ID_LIMIT, bits
            passed += 1
    assert passed < 30  # a few parity-field pairs only, out of 1540 pairs


def _df11_with_remainder(remainder: int) -> Frame:
    # The parity field is the low 24 bits, so XORing it changes the remainder by the same amount.
    return Frame(DF11_CLEAN.value ^ remainder, DF11_CLEAN.n_bits)


def test_interrogator_id_limit_is_79_accepted_80_rejected() -> None:
    below = _df11_with_remainder(INTERROGATOR_ID_LIMIT - 1)
    at_limit = _df11_with_remainder(INTERROGATOR_ID_LIMIT)
    assert crc_remainder(below) == 79 and crc_remainder(at_limit) == 80
    accepted = accept(below, _listed(), 0.0, fix=False)
    assert accepted is not None and accepted.interrogator_id == 79
    assert accept(at_limit, _listed(), 0.0, fix=False) is None


def test_large_df11_remainder_is_rejected_in_both_modes() -> None:
    frame = _df11_with_remainder(0x123456)
    assert 0x123456 not in single_bit_syndromes(56)
    for fix in (False, True):
        assert accept(frame, _listed(), 0.0, fix) is None


def test_interrogator_id_for_an_unlisted_address_is_rejected() -> None:
    frame = _df11_with_remainder(60)
    assert accept(frame, RecentlySeen(), 0.0, fix=False) is None
    assert accept(frame, _listed(0x123456), 0.0, fix=False) is None  # a different aircraft


def test_address_parity_with_a_different_listed_address_is_rejected() -> None:
    assert accept(DF4_PARITY, _listed(0x123456), 0.0, fix=False) is None
    assert accept(DF4_PARITY, _listed(ICAO), 0.0, fix=False) is not None  # control


def test_address_parity_is_rejected_after_the_window_expires() -> None:
    recent = _listed(ICAO, t=0.0)
    assert accept(DF4_PARITY, recent, 60.0, fix=False) is not None  # exactly 60 s: still in
    assert accept(DF4_PARITY, recent, 60.001, fix=False) is None


def test_golden_address_parity_frames_are_rejected_for_a_wrong_address(
    nofix_lines: list[str],
) -> None:
    address_parity = [
        f for f in map(Frame.from_hex, nofix_lines) if f.df in (0, 4, 5, 16, 20, 21, 24)
    ]
    assert len(address_parity) == 34
    for frame in address_parity:
        assert accept(frame, _listed(0x123456), 0.0, fix=False) is None
        assert accept(frame, _listed(0x123456), 0.0, fix=True) is None


@pytest.mark.parametrize("frame", [DF17_CLEAN, DF11_CLEAN])
def test_the_first_five_bits_are_never_repaired(frame: Frame) -> None:
    # Decision #9: a wrong DF bit also means a wrong frame length, so we never repair bits 0-4.
    # (dump1090 can, for 56-bit frames; it can't matter for this recording.)
    for bit in range(5):
        broken = frame.flip(bit)
        assert repair_single_bit(broken) is None, bit
        assert accept(broken, _listed(), 0.0, fix=True) is None, bit
