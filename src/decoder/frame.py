"""A received Mode S frame: its bits as one integer plus its length.

Bit numbering is 0-based from the first transmitted bit (the most significant bit), so
"bit 0" here is the Riddle's bit 1.
"""

from __future__ import annotations

from dataclasses import dataclass

# Downlink formats sent as 112-bit frames. dump1090.c 746-753 at efe64db; every other DF is 56 bits.
# The Riddle (Introduction) lists DF 24 as 112 bits; we follow dump1090 to match the answer key
# (docs/pseudocode.md stage 3).
LONG_FORMATS = frozenset({16, 17, 18, 19, 20, 21})


def frame_length(df: int) -> int:
    """Number of bits in a frame with this downlink format."""
    return 112 if df in LONG_FORMATS else 56


@dataclass(frozen=True)
class Frame:
    value: int
    n_bits: int

    @classmethod
    def from_hex(cls, text: str) -> Frame:
        """Parse hex digits, also accepting dump1090's raw form `*<hex>;`."""
        digits = text.strip().removeprefix("*").removesuffix(";")
        return cls(int(digits, 16), len(digits) * 4)

    def field(self, first: int, width: int) -> int:
        """The `width` bits starting at bit `first`, as an unsigned integer."""
        return (self.value >> (self.n_bits - first - width)) & ((1 << width) - 1)

    @property
    def df(self) -> int:
        """Downlink format: the first 5 bits."""
        return self.field(0, 5)

    @property
    def hex(self) -> str:
        return f"{self.value:0{self.n_bits // 4}x}"

    def flip(self, bit: int) -> Frame:
        """A copy with one bit inverted."""
        return Frame(self.value ^ (1 << (self.n_bits - 1 - bit)), self.n_bits)
