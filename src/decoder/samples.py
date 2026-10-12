"""Samples to magnitude (docs/pseudocode.md stage 1; sample format in docs/decoder-notes.md).

The recording is raw bytes: unsigned 8-bit I, Q, I, Q, ... at 2 MHz, centered on 127
(dump1090 README lines 69-72 and dump1090.c 1462-1463 at efe64db).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

CENTER = 127


def load_iq(path: Path) -> np.ndarray:
    """The recording's bytes, trimmed to a whole number of I/Q pairs."""
    data = np.fromfile(path, dtype=np.uint8)
    return data[: data.size - data.size % 2]


def magnitude(iq: np.ndarray) -> np.ndarray:
    """One magnitude per sample: the distance of (I, Q) from the center. Sample s is s x 0.5 us."""
    centered = iq.astype(np.int32) - CENTER
    i, q = centered[0::2], centered[1::2]
    return np.sqrt(i * i + q * q)
