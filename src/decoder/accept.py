"""Decide whether a frame is a real message (docs/pseudocode.md stage 4).

Rules, with dump1090.c lines at efe64db for the behavior the golden files encode:
- DF 11/17/18 carry the plain CRC. With `fix`, a one-bit error is repaired first (1112-1127).
  A frame that is clean without repair adds its ICAO address to the recently-seen list (1197-1200).
- DF 11 whose remainder is below 80 is accepted as an interrogator ID if its address was recently
  seen (1202-1209). This runs after repair, so with `fix` a remainder of 1, 2, 4 ... 64 is repaired
  instead (docs/pseudocode.md stage 4c).
- DF 0/4/5/16/20/21/24 carry address parity: the remainder is the ICAO address itself, accepted
  only if recently seen (947-983; Riddle, "Mode S basics", Parity).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from decoder.crc import crc_remainder, repair_single_bit
from decoder.frame import Frame
from decoder.recent import RecentlySeen

PLAIN_CRC_FORMATS = frozenset({11, 17, 18})
ADDRESS_PARITY_FORMATS = frozenset({0, 4, 5, 16, 20, 21, 24})
INTERROGATOR_ID_LIMIT = 80  # dump1090's choice, not a protocol fact (docs/pseudocode.md 4b)


class How(StrEnum):
    CLEAN = "clean"
    REPAIRED = "repaired one bit"
    INTERROGATOR_ID = "DF 11 interrogator ID"
    ADDRESS_PARITY = "address parity"


@dataclass(frozen=True)
class Accepted:
    frame: Frame  # repaired, if a bit was repaired
    icao: int
    how: How
    interrogator_id: int = 0
    repaired_bit: int | None = None


def accept(frame: Frame, recent: RecentlySeen, t: float, fix: bool) -> Accepted | None:
    """Accept or reject one frame at recording time `t`; updates `recent` for clean frames."""
    if frame.df in PLAIN_CRC_FORMATS:
        return _accept_plain_crc(frame, recent, t, fix)
    if frame.df in ADDRESS_PARITY_FORMATS:
        address = crc_remainder(frame)
        if recent.seen(address, t):
            return Accepted(frame, address, How.ADDRESS_PARITY)
    return None


def _accept_plain_crc(frame: Frame, recent: RecentlySeen, t: float, fix: bool) -> Accepted | None:
    remainder = crc_remainder(frame)
    icao = frame.field(8, 24)
    if remainder == 0:
        recent.add(icao, t)
        return Accepted(frame, icao, How.CLEAN)
    if fix and (repaired := repair_single_bit(frame)) is not None:
        fixed, bit = repaired
        return Accepted(fixed, fixed.field(8, 24), How.REPAIRED, repaired_bit=bit)
    if frame.df == 11 and remainder < INTERROGATOR_ID_LIMIT and recent.seen(icao, t):
        return Accepted(frame, icao, How.INTERROGATOR_ID, interrogator_id=remainder)
    return None
