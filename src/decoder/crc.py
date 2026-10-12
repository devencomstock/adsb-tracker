"""CRC remainder and single-bit repair (docs/pseudocode.md stage 4).

The Mode S CRC divides the frame by the 25-bit generator 0x1FFF409 using XOR instead of
subtraction (Riddle, "Error control"). For an intact DF 17 frame the 24-bit remainder is 0.
"""

from __future__ import annotations

from functools import lru_cache

from decoder.frame import Frame

GENERATOR = 0x1FFF409
PARITY_BITS = 24
# The first 5 bits (the DF) are never repaired: a wrong DF also means a wrong frame length.
# dump1090 excludes them for 112-bit frames only; see decision #9.
FIRST_REPAIRABLE_BIT = 5


def crc_remainder(frame: Frame) -> int:
    """Remainder of the whole frame (data and parity) divided by the generator."""
    n = frame.n_bits
    reg = frame.value
    for i in range(n - PARITY_BITS):
        if (reg >> (n - 1 - i)) & 1:
            reg ^= GENERATOR << (n - PARITY_BITS - 1 - i)
    return reg & 0xFFFFFF


@lru_cache(maxsize=2)
def single_bit_syndromes(n_bits: int) -> dict[int, int]:
    """Remainder caused by one flipped bit -> that bit's position.

    The CRC is linear, so for an otherwise intact frame the remainder depends only on which
    bit flipped. Every position gives a different remainder (checked in the tests).
    """
    return {
        crc_remainder(Frame(1 << (n_bits - 1 - bit), n_bits)): bit
        for bit in range(FIRST_REPAIRABLE_BIT, n_bits)
    }


def repair_single_bit(frame: Frame) -> tuple[Frame, int] | None:
    """If exactly one flipped bit explains the remainder, return the repaired frame and that bit."""
    remainder = crc_remainder(frame)
    if remainder == 0:
        return None
    bit = single_bit_syndromes(frame.n_bits).get(remainder)
    if bit is None:
        return None
    return frame.flip(bit), bit
