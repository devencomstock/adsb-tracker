"""Run the stages in order over a whole recording."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from decoder.accept import Accepted, accept
from decoder.bits import read_bits, to_frame
from decoder.preamble import DATA_OFFSET, find_candidates
from decoder.recent import RecentlySeen, recording_time
from decoder.samples import load_iq, magnitude

# Weakest preamble pulse worth reading, in magnitude units (0 to about 180). Decision #10.
SIGNAL_FLOOR = 9.0


@dataclass(frozen=True)
class Message:
    start: int  # sample index of the preamble's first pulse
    accepted: Accepted


def decode_magnitudes(
    mag: np.ndarray, fix: bool, signal_floor: float = SIGNAL_FLOOR
) -> list[Message]:
    """Accepted messages in sample order. After a message, candidates inside it are skipped."""
    recent = RecentlySeen()
    messages: list[Message] = []
    next_free = 0
    for start in map(int, find_candidates(mag, signal_floor)):
        if start < next_free:
            continue
        bits, ties = read_bits(mag, start)
        if ties:
            continue
        frame = to_frame(bits)
        result = accept(frame, recent, recording_time(start), fix)
        if result is None:
            continue
        messages.append(Message(start, result))
        next_free = start + DATA_OFFSET + 2 * frame.n_bits
    return messages


def decode_file(path: Path, fix: bool, signal_floor: float = SIGNAL_FLOOR) -> list[Message]:
    return decode_magnitudes(magnitude(load_iq(path)), fix, signal_floor)


def raw_line(message: Message) -> str:
    """The message as dump1090 --raw prints it."""
    return f"*{message.accepted.frame.hex};"
