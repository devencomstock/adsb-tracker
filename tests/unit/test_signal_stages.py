"""Samples to magnitude, preamble detection and pulses to bits, on small synthetic signals."""

from pathlib import Path

import numpy as np

from decoder.bits import read_bits, to_frame
from decoder.frame import Frame
from decoder.preamble import DATA_OFFSET, find_candidates
from decoder.samples import load_iq, magnitude

PULSE, QUIET = 40.0, 2.0


def synthetic(frame: Frame, lead: int = 5, tail: int = 300) -> np.ndarray:
    """Magnitudes for one frame: preamble pulses at 0, 2, 7, 9 then one pulse per bit (PPM)."""
    mag = np.full(lead + DATA_OFFSET + 2 * 112 + tail, QUIET)
    for k in (0, 2, 7, 9):
        mag[lead + k] = PULSE
    for bit in range(frame.n_bits):
        one = frame.field(bit, 1) == 1
        mag[lead + DATA_OFFSET + 2 * bit + (0 if one else 1)] = PULSE
    return mag


def test_magnitude_of_hand_computed_pairs() -> None:
    iq = np.array([127, 127, 102, 134, 255, 127], dtype=np.uint8)
    assert np.allclose(magnitude(iq), [0.0, np.sqrt(25**2 + 7**2), 128.0])


def test_load_iq_drops_a_trailing_half_sample(tmp_path: Path) -> None:
    path = tmp_path / "odd.bin"
    path.write_bytes(bytes([127, 127, 130]))
    assert load_iq(path).tolist() == [127, 127]


def test_preamble_is_found_at_its_start() -> None:
    frame = Frame.from_hex("8f4d2023587f345e35837e2218b2")
    assert 5 in find_candidates(synthetic(frame), signal_floor=9.0).tolist()


def test_weak_preamble_is_ignored() -> None:
    frame = Frame.from_hex("8f4d2023587f345e35837e2218b2")
    assert 5 not in find_candidates(synthetic(frame), signal_floor=PULSE + 1).tolist()


def test_loud_quiet_sample_breaks_the_preamble() -> None:
    mag = synthetic(Frame.from_hex("8f4d2023587f345e35837e2218b2"))
    mag[5 + 4] = PULSE + 1
    assert 5 not in find_candidates(mag, signal_floor=9.0).tolist()


def test_too_short_signal_has_no_candidates() -> None:
    assert find_candidates(np.zeros(100), signal_floor=9.0).size == 0


def test_bits_round_trip_for_both_lengths() -> None:
    for text in ("8f4d2023587f345e35837e2218b2", "5d4d20237a55a6", "20000f1f684a6c"):
        frame = Frame.from_hex(text)
        bits, ties = read_bits(synthetic(frame), 5)
        assert ties == 0
        assert to_frame(bits) == frame


def test_equal_halves_are_counted_as_ties() -> None:
    mag = synthetic(Frame.from_hex("5d4d20237a55a6"))
    mag[5 + DATA_OFFSET + 2 * 10] = mag[5 + DATA_OFFSET + 2 * 10 + 1] = PULSE
    assert read_bits(mag, 5)[1] == 1
