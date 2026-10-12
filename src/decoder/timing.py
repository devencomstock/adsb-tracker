"""Sub-sample timing re-read (docs/pseudocode.md stage 3d, step a2).

At 2 MHz a 0.5 us pulse lasts one sample. If a message's pulses arrive a fraction d of a sample
late, each puts about (1 - |d|) of its energy in its own sample and |d| in the next one (the
previous one if early). The known preamble shows how much spilled over, which gives d; the bits
are then re-read with windows that follow the pulses instead of the sample grid.
"""

from __future__ import annotations

import numpy as np

from decoder.bits import MAX_BITS
from decoder.preamble import DATA_OFFSET

GRID = (0.25, -0.25, 0.5, -0.5)


def offset_estimate(mag: np.ndarray, start: int) -> float:
    """Fraction of a sample by which the preamble pulses arrive late (+) or early (-).

    Samples 3 and 10 sit just after pulses 2 and 9, and samples -1 and 6 just before pulses 0
    and 7; each is otherwise quiet, so whatever energy is there spilled over from that pulse.
    """
    peak = (mag[start] + mag[start + 2] + mag[start + 7] + mag[start + 9]) / 4
    late = (mag[start + 3] + mag[start + 10]) / 2
    early = (mag[start + 6] + (mag[start - 1] if start > 0 else mag[start + 6])) / 2
    total = peak + late + early
    return float((late - early) / total) if total > 0 else 0.0


def hypotheses(estimate: float) -> list[float]:
    """The estimate first, then the fixed grid, nearest to the estimate first."""
    return [estimate, *sorted(GRID, key=lambda d: abs(d - estimate))]


def reread_bits(mag: np.ndarray, start: int, offset: float) -> np.ndarray:
    """112 bits read with each half-bit window shifted by `offset` samples.

    The energy of a pulse in a half-bit is (1 - |offset|) of its own sample plus |offset| of the
    sample it spills into. With offset 0 this is exactly the plain read of stage 3.
    """
    x = start + DATA_OFFSET + 2 * np.arange(MAX_BITS)
    w = abs(offset)
    side = 1 if offset >= 0 else -1

    def energy(index: np.ndarray) -> np.ndarray:
        return (1 - w) * mag.take(index, mode="clip") + w * mag.take(index + side, mode="clip")

    return energy(x) > energy(x + 1)
