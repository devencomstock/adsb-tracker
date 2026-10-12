"""Preamble detection (docs/pseudocode.md stage 2).

The 8 us preamble is 1010000101000000 in half-microsecond chips (Riddle, "Introduction"), so at
2 MHz its four pulses are at sample offsets 0, 2, 7 and 9 and every other sample up to offset 15
is quiet. The data starts at offset 16.
"""

from __future__ import annotations

import numpy as np

PULSES = (0, 2, 7, 9)
QUIET = (1, 3, 4, 5, 6, 8, 10, 11, 12, 13, 14, 15)
DATA_OFFSET = 16
LONGEST_FRAME_SAMPLES = 2 * 112


def find_candidates(mag: np.ndarray, signal_floor: float) -> np.ndarray:
    """Start samples where each pulse beats every quiet sample and reaches `signal_floor`."""
    count = mag.size - (DATA_OFFSET + LONGEST_FRAME_SAMPLES) + 1
    if count <= 0:
        return np.empty(0, dtype=np.int64)
    weakest_pulse = np.minimum.reduce([mag[k : k + count] for k in PULSES])
    loudest_quiet = np.maximum.reduce([mag[k : k + count] for k in QUIET])
    ok = (weakest_pulse > loudest_quiet) & (weakest_pulse >= signal_floor)
    return np.nonzero(ok)[0]
