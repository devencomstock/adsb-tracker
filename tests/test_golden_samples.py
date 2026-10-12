"""Checkpoint B: the signal stages on the real recording, against the golden files.

Needs data/modes1.bin (gitignored; see tests/golden/README.md). Skipped when it's absent.
The start-sample fixture tests/golden/modes1_starts.txt is read here, never by src/decoder/.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from decoder.bits import read_bits, to_frame
from decoder.pipeline import SIGNAL_FLOOR, decode_magnitudes
from decoder.preamble import DATA_OFFSET, find_candidates
from decoder.samples import load_iq, magnitude

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


@pytest.mark.parametrize("fix", [False, True])
def test_no_extra_messages_where_dump1090_decoded(mag, fixture_rows, fix: bool) -> None:
    golden = {(start, msg_hex) for _, start, _, msg_hex in fixture_rows}
    golden_hex_near = {}
    for start, msg_hex in golden:
        golden_hex_near.setdefault(msg_hex, []).append(start)
    for message in decode_magnitudes(mag, fix):
        end = message.start + DATA_OFFSET + 2 * message.accepted.frame.n_bits
        if end > DUMP1090_DECODED_SAMPLES:
            continue
        near = golden_hex_near.get(message.accepted.frame.hex, [])
        assert any(abs(s - message.start) <= 16 for s in near), (message.start, message.accepted)


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
