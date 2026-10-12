"""Checkpoint B: the signal stages on the real recording, against the golden files.

Needs data/modes1.bin (gitignored; see tests/golden/README.md). Skipped when it's absent.
The start-sample fixture tests/golden/modes1_starts.txt is read here, never by src/decoder/.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import read_raw

from decoder.accept import How
from decoder.bits import read_bits, to_frame
from decoder.pipeline import SIGNAL_FLOOR, Message, decode_magnitudes
from decoder.preamble import DATA_OFFSET, find_candidates
from decoder.samples import load_iq, magnitude
from decoder.timing import offset_estimate

REPO = Path(__file__).resolve().parents[1]
RECORDING = REPO / "data" / "modes1.bin"
STARTS = REPO / "tests" / "golden" / "modes1_starts.txt"
# dump1090 never decodes the last, partial 262,144-byte buffer of modes1.bin (see
# scripts/compare_golden.py), so the golden files cover samples 0 to 262,143 only.
DUMP1090_DECODED_SAMPLES = 262_144

pytestmark = pytest.mark.skipif(not RECORDING.exists(), reason="data/modes1.bin not present")


@pytest.fixture(scope="module")
def mag() -> np.ndarray:
    return magnitude(load_iq(RECORDING))


@pytest.fixture(scope="module")
def fixture_rows() -> list[tuple[int, int, str, str]]:
    rows = []
    for text in STARTS.read_text().splitlines():
        if not text.startswith("#"):
            line, start, flag, _bits, msg_hex = text.split("\t")
            rows.append((int(line), int(start), flag, msg_hex))
    return rows


def test_fixture_has_217_lines_with_flags(fixture_rows) -> None:
    assert len(fixture_rows) == 217
    assert {flag for *_, flag, _ in fixture_rows} == {"exact", "approximate"}
    flags = {line: flag for line, _, flag, _ in fixture_rows}
    assert flags[128] == flags[174] == "approximate"


def test_every_exact_start_is_a_preamble_candidate(mag, fixture_rows) -> None:
    candidates = set(find_candidates(mag, SIGNAL_FLOOR).tolist())
    exact = [start for _, start, flag, _ in fixture_rows if flag == "exact"]
    assert len(exact) == 194
    assert [s for s in exact if s not in candidates] == []


def test_bits_at_every_exact_start_equal_the_golden_hex(mag, fixture_rows) -> None:
    for line, start, flag, msg_hex in fixture_rows:
        if flag == "exact":
            bits, ties = read_bits(mag, start)
            assert ties == 0, line
            assert to_frame(bits).hex == msg_hex, line


def compare_with_golden(mag, fixture_rows, mode: str) -> tuple[list[int], list[Message]]:
    """(missing golden lines, extra messages) inside the region dump1090 decoded, matching each
    golden line to one of our messages with the same hex within 16 samples of its fixture start."""
    golden_hex = read_raw(mode)
    messages = [
        m
        for m in decode_magnitudes(mag, fix=mode == "default")
        if m.start + DATA_OFFSET + 2 * m.accepted.frame.n_bits <= DUMP1090_DECODED_SAMPLES
    ]
    unused = set(range(len(messages)))
    missing = []
    for line, start, _flag, _hex in fixture_rows:
        hit = next(
            (
                i
                for i in sorted(unused, key=lambda i: abs(messages[i].start - start))
                if messages[i].accepted.frame.hex == golden_hex[line]
                and abs(messages[i].start - start) <= 16
            ),
            None,
        )
        if hit is None:
            missing.append(line)
        else:
            unused.remove(hit)
    return missing, [messages[i] for i in sorted(unused)]


def known_extras() -> list[tuple[int, str, str, str]]:
    rows = []
    for text in (STARTS.parent / "known_extras.txt").read_text(encoding="utf-8").splitlines():
        if text and not text.startswith("#"):
            start, msg_hex, mode, reason = text.split("\t")
            rows.append((int(start), msg_hex, mode, reason))
    return rows


@pytest.mark.parametrize("mode", ["nofix", "default"])
def test_every_extra_is_explained(mag, fixture_rows, mode: str) -> None:
    # Decision #8 (revised): zero unexplained extras inside the region dump1090 decoded.
    _missing, extras = compare_with_golden(mag, fixture_rows, mode)
    for m in extras:
        listed = [
            reason
            for start, msg_hex, which, reason in known_extras()
            if abs(start - m.start) <= 16
            and msg_hex == m.accepted.frame.hex
            and which in (mode, "both")
        ]
        assert listed and listed[0].strip(), ("(c)/(d) not in known_extras.txt", m.start)
        assert m.accepted.how in (How.CLEAN, How.ADDRESS_PARITY), ("(a)", m.start, m.accepted.how)
        assert all(mag[m.start + k] >= SIGNAL_FLOOR for k in (0, 2, 7, 9)), ("(b)", m.start)


@pytest.mark.parametrize("fix", [False, True])
def test_listed_tail_extras_meet_the_criteria(mag, fix: bool) -> None:
    # Holdout (decision #13): this checks the two classified tail extras still meet decision #8's
    # criteria. It is not a pass rule for the tail, and nothing is tuned on it.
    rows = [
        text.split("\t")
        for text in (STARTS.parent / "known_extras_tail.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if text and not text.startswith("#")
    ]
    decoded = {m.start: m for m in decode_magnitudes(mag, fix)}
    for start, msg_hex, _mode, offset, reason in rows:
        m = decoded[int(start)]
        assert m.accepted.frame.hex == msg_hex and reason.strip()
        assert m.accepted.how in (How.CLEAN, How.ADDRESS_PARITY)
        assert all(mag[m.start + k] >= SIGNAL_FLOOR for k in (0, 2, 7, 9))
        assert offset_estimate(mag, m.start) == pytest.approx(float(offset), abs=0.01)


@pytest.mark.parametrize(
    ("mode", "expected_missing"), [("nofix", [128, 156, 174, 178]), ("default", [174])]
)
def test_measured_misses(mag, fixture_rows, mode: str, expected_missing: list[int]) -> None:
    # Pins the measured result after step a2 (docs/phase4-golden-report.md); both are within
    # decision #8's limit of 10.
    missing, _extras = compare_with_golden(mag, fixture_rows, mode)
    assert missing == expected_missing


@pytest.mark.parametrize(
    ("mode", "fix", "lines", "exact"), [("nofix", False, 66, 62), ("default", True, 67, 62)]
)
def test_holdout_tail_exact_lines_are_decoded_at_their_start(mag, mode, fix, lines, exact) -> None:
    # Holdout (decision #13): checked, never tuned on.
    rows = [
        text.split("\t")
        for text in (STARTS.parent / f"modes1_tail_starts_{mode}.txt").read_text().splitlines()
        if not text.startswith("#")
    ]
    assert len(rows) == lines
    exact_rows = [(int(start), h) for _line, start, flag, _bits, h in rows if flag == "exact"]
    assert len(exact_rows) == exact
    decoded = {(m.start, m.accepted.frame.hex) for m in decode_magnitudes(mag, fix)}
    assert [r for r in exact_rows if r not in decoded] == []


def test_every_exact_line_is_decoded_at_its_start(mag, fixture_rows) -> None:
    decoded = {(m.start, m.accepted.frame.hex) for m in decode_magnitudes(mag, fix=False)}
    missing = [
        line
        for line, start, flag, h in fixture_rows
        if flag == "exact" and (start, h) not in decoded
    ]
    assert missing == []
