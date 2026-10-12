"""Preamble detection (docs/pseudocode.md stage 2).

The 8 us preamble is 1010000101000000 in half-microsecond chips (Riddle, "Introduction"), so at
2 MHz its four pulses are at sample offsets 0, 2, 7 and 9 and the samples between and after them
(up to offset 15) are quiet. The data starts at offset 16.

When a pulse arrives between two sample instants, part of its energy lands in the samples right
beside it. So a quiet sample next to a pulse is only required to be lower than that pulse, and
the level test uses only the quiet samples well away from any pulse (docs/pseudocode.md stage 2).
"""

from __future__ import annotations

import numpy as np

PULSES = (0, 2, 7, 9)
# (pulse, neighbouring quiet sample) pairs inside the preamble: each pulse must beat its neighbours.
PULSE_NEIGHBOURS = ((0, 1), (2, 1), (2, 3), (7, 6), (7, 8), (9, 8))
# Quiet samples not next to any pulse (offset 15 borders the first data bit).
FAR_QUIET = (4, 5, 11, 12, 13, 14)
FAR_QUIET_LIMIT = 2 / 3  # of the average pulse level
DATA_OFFSET = 16
LONGEST_FRAME_SAMPLES = 2 * 112


def find_candidates(mag: np.ndarray, signal_floor: float) -> np.ndarray:
    """Start samples whose preamble has the right shape, quiet gaps and enough signal."""
    count = mag.size - (DATA_OFFSET + LONGEST_FRAME_SAMPLES) + 1
    if count <= 0:
        return np.empty(0, dtype=np.int64)

    def at(offset: int) -> np.ndarray:
        return mag[offset : offset + count]

    shape = np.logical_and.reduce([at(p) > at(q) for p, q in PULSE_NEIGHBOURS])
    pulse_mean = sum(at(p) for p in PULSES) / len(PULSES)
    gaps = np.maximum.reduce([at(q) for q in FAR_QUIET]) < FAR_QUIET_LIMIT * pulse_mean
    strong = np.minimum.reduce([at(p) for p in PULSES]) >= signal_floor
    return np.nonzero(shape & gaps & strong)[0]
