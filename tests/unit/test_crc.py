"""CRC and single-bit repair, checked against values from The 1090 MHz Riddle (primer section 4)."""

from decoder.crc import FIRST_REPAIRABLE_BIT, crc_remainder, repair_single_bit, single_bit_syndromes
from decoder.frame import Frame

CRC_GOOD = Frame.from_hex("8D406B902015A678D4D220AA4BDA")  # Riddle, Error control: remainder 0
CRC_BAD = Frame.from_hex("8D4CA251204994B1C36E60A5343D")  # Riddle, Error control: remainder 16
ALL_CALL = Frame.from_hex("5D484FDEA248F5")  # Riddle, All-call reply: interrogator ID 22


def test_remainders_from_the_book() -> None:
    assert crc_remainder(CRC_GOOD) == 0
    assert crc_remainder(CRC_BAD) == 16
    assert crc_remainder(ALL_CALL) == 22


def test_parity_is_remainder_of_data_with_zero_parity() -> None:
    data_only = Frame(CRC_GOOD.value >> 24 << 24, 112)
    assert crc_remainder(data_only) == 0xAA4BDA == CRC_GOOD.field(88, 24)


def test_every_single_bit_syndrome_is_distinct() -> None:
    for n_bits in (56, 112):
        assert len(single_bit_syndromes(n_bits)) == n_bits - FIRST_REPAIRABLE_BIT


def test_repair_recovers_every_repairable_bit() -> None:
    for bit in range(FIRST_REPAIRABLE_BIT, 112):
        assert repair_single_bit(CRC_GOOD.flip(bit)) == (CRC_GOOD, bit)


def test_df_bits_are_never_repaired() -> None:
    for bit in range(FIRST_REPAIRABLE_BIT):
        assert repair_single_bit(CRC_GOOD.flip(bit)) is None


def test_repair_of_the_book_bad_message() -> None:
    repaired = repair_single_bit(CRC_BAD)
    assert repaired is not None
    fixed, bit = repaired
    assert fixed.hex == "8d4ca251204994b1c36e60a5342d" and bit == 107
    assert crc_remainder(fixed) == 0


def test_clean_frame_needs_no_repair() -> None:
    assert repair_single_bit(CRC_GOOD) is None


def test_parity_bit_syndromes_are_powers_of_two() -> None:
    syndromes = single_bit_syndromes(56)
    low = sorted((r, b) for r, b in syndromes.items() if r < 80)
    assert low == [(1, 55), (2, 54), (4, 53), (8, 52), (16, 51), (32, 50), (64, 49)]
