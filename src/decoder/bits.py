"""Pulses to bits (docs/pseudocode.md stage 3).

Pulse-position modulation (Riddle, "Introduction"): each bit lasts 1 us = 2 samples. A 1 is a
pulse in the first half, a 0 a pulse in the second half, so bit k is decided by comparing samples
start+16+2k and start+17+2k. All 112 bits are read; the DF then says how many are real.
"""

from __future__ import annotations

import numpy as np

from decoder.frame import Frame, frame_length
from decoder.preamble import DATA_OFFSET

MAX_BITS = 112
SHORT_BITS = 56


def read_bits(mag: np.ndarray, start: int) -> tuple[np.ndarray, int]:
    """112 bits for a frame starting at `start`, and how many of the first 56 had equal halves."""
    first = mag[start + DATA_OFFSET : start + DATA_OFFSET + 2 * MAX_BITS : 2]
    second = mag[start + DATA_OFFSET + 1 : start + DATA_OFFSET + 2 * MAX_BITS : 2]
    ties = int(np.count_nonzero(first[:SHORT_BITS] == second[:SHORT_BITS]))
    return first > second, ties


def to_frame(bits: np.ndarray) -> Frame:
    """Keep as many bits as the DF (the first 5 bits) calls for."""
    value = int.from_bytes(np.packbits(bits).tobytes(), "big")
    df = value >> (MAX_BITS - 5)
    n_bits = frame_length(df)
    return Frame(value >> (MAX_BITS - n_bits), n_bits)
