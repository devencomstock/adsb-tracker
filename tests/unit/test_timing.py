"""Sub-sample timing re-read (docs/pseudocode.md stage 3d), on synthetic signals."""

import numpy as np
import pytest

from decoder.bits import read_bits, to_frame
from decoder.frame import Frame
from decoder.pipeline import decode_magnitudes
from decoder.preamble import DATA_OFFSET, find_candidates
from decoder.timing import hypotheses, offset_estimate, reread_bits

PULSE, NOISE = 40.0, 1.0
LEAD = 20
DF17 = Frame.from_hex("8f4d2023587f345e35837e2218b2")


def shifted(frame: Frame, offset: float) -> np.ndarray:
    """Magnitudes for one frame whose pulses arrive `offset` samples late (+) or early (-)."""
    mag = np.full(LEAD + DATA_OFFSET + 2 * 112 + 300, NOISE)
    pulses = [0, 2, 7, 9] + [
        DATA_OFFSET + 2 * bit + (0 if frame.field(bit, 1) else 1) for bit in range(frame.n_bits)
    ]
    side = 1 if offset >= 0 else -1
    for p in pulses:
        mag[LEAD + p] += (1 - abs(offset)) * PULSE
        mag[LEAD + p + side] += abs(offset) * PULSE
    return mag


@pytest.mark.parametrize("offset", [-0.4, -0.25, 0.0, 0.2, 0.35])
def test_offset_estimate_is_within_a_tenth(offset: float) -> None:
    assert offset_estimate(shifted(DF17, offset), LEAD) == pytest.approx(offset, abs=0.1)


@pytest.mark.parametrize("offset", [-0.4, 0.4])
def test_reread_at_the_estimate_recovers_the_frame(offset: float) -> None:
    mag = shifted(DF17, offset)
    bits = reread_bits(mag, LEAD, offset_estimate(mag, LEAD))
    assert to_frame(bits) == DF17


def test_offset_zero_is_exactly_the_plain_read() -> None:
    rng = np.random.default_rng(7)
    mag = rng.rayleigh(10.0, size=2000)
    for start in (0, 100, 1500):
        plain, _ties = read_bits(mag, start)
        assert np.array_equal(reread_bits(mag, start, 0.0), plain)


def test_hypotheses_start_with_the_estimate_then_nearest_grid_point() -> None:
    assert hypotheses(0.3) == [0.3, 0.25, 0.5, -0.25, -0.5]
    assert hypotheses(-0.4) == [-0.4, -0.5, -0.25, 0.25, 0.5]


def test_pipeline_uses_the_reread_when_the_plain_read_fails() -> None:
    # Bit 7 is a 1 followed by a 0. Make its two halves exactly equal: the plain read rejects the
    # frame (a tie), and the re-read half a window later (+0.25) sees the pulse in the first half.
    mag = shifted(DF17, 0.0)
    x = LEAD + DATA_OFFSET + 2 * 7
    mag[x + 1] = mag[x]
    assert read_bits(mag, LEAD)[1] == 1
    messages = decode_magnitudes(mag, fix=False, signal_floor=9.0)
    assert [(m.start, m.accepted.frame) for m in messages] == [(LEAD, DF17)]
    assert messages[0].timing_offset == pytest.approx(0.25)


def test_frame_with_no_valid_hypothesis_is_rejected() -> None:
    mag = shifted(DF17, 0.0)
    rng = np.random.default_rng(3)
    data = slice(LEAD + DATA_OFFSET, LEAD + DATA_OFFSET + 224)
    mag[data] = rng.uniform(0, PULSE, size=224)  # a good preamble followed by garbage
    assert decode_magnitudes(mag, fix=True, signal_floor=9.0) == []


@pytest.mark.parametrize("fix", [False, True])
def test_pure_noise_candidates_produce_no_acceptance(fix: bool) -> None:
    rng = np.random.default_rng(2026)
    iq = rng.normal(0.0, 10.0, size=(2_000_000, 2))  # one second of noise at 2 MHz
    mag = np.hypot(iq[:, 0], iq[:, 1])
    candidates = find_candidates(mag, signal_floor=9.0)
    assert candidates.size > 1000  # enough noise preambles for this to mean something
    assert decode_magnitudes(mag, fix=fix, signal_floor=9.0) == []
