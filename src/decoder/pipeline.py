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
from decoder.timing import hypotheses, offset_estimate, reread_bits

# Weakest preamble pulse worth reading, in magnitude units (0 to about 180). Decision #10.
SIGNAL_FLOOR = 9.0


@dataclass(frozen=True)
class Message:
    start: int  # sample index of the preamble's first pulse
    accepted: Accepted
    timing_offset: float | None = None  # set when found by the timing re-read (stage 3d)


def decode_at(
    mag: np.ndarray, start: int, recent: RecentlySeen, fix: bool, timing_reread: bool
) -> Message | None:
    """Plain read first; if accept() rejects it, re-read at the estimated timing offsets."""
    t = recording_time(start)
    bits, ties = read_bits(mag, start)
    if not ties:
        result = accept(to_frame(bits), recent, t, fix)
        if result is not None:
            return Message(start, result)
    if not timing_reread:
        return None
    for offset in hypotheses(offset_estimate(mag, start)):
        result = accept(to_frame(reread_bits(mag, start, offset)), recent, t, fix)
        if result is not None:
            return Message(start, result, timing_offset=offset)
    return None


def decode_magnitudes(
    mag: np.ndarray, fix: bool, signal_floor: float = SIGNAL_FLOOR, timing_reread: bool = True
) -> list[Message]:
    """Accepted messages in sample order. After a message, candidates inside it are skipped."""
    recent = RecentlySeen()
    messages: list[Message] = []
    next_free = 0
    for start in map(int, find_candidates(mag, signal_floor)):
        if start < next_free:
            continue
        message = decode_at(mag, start, recent, fix, timing_reread)
        if message is None:
            continue
        messages.append(message)
        next_free = start + DATA_OFFSET + 2 * message.accepted.frame.n_bits
    return messages


def decode_file(
    path: Path, fix: bool, signal_floor: float = SIGNAL_FLOOR, timing_reread: bool = True
) -> list[Message]:
    return decode_magnitudes(magnitude(load_iq(path)), fix, signal_floor, timing_reread)


def raw_line(message: Message) -> str:
    """The message as dump1090 --raw prints it."""
    return f"*{message.accepted.frame.hex};"
