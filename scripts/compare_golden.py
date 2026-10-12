"""Compare the decoder's output on modes1.bin with dump1090's golden files (decision #8).

NOT part of the decoder. Runs the decoder in no-fix and default mode, matches its messages to
golden lines by hex and start sample, and reports matched / missing / extra with evidence:
  missing  golden line, its start sample and flag from tests/golden/modes1_starts.txt, and what
           our stages did at that start (candidate? bits? accepted? inside another message?)
  extra    our start sample, hex, how it was accepted, and whether dump1090 decoded that region

Run:  python scripts/compare_golden.py            (summary)
      python scripts/compare_golden.py --report docs/phase4-golden-report.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from decoder.accept import How, accept  # noqa: E402
from decoder.bits import read_bits, to_frame  # noqa: E402
from decoder.pipeline import SIGNAL_FLOOR, Message, decode_magnitudes  # noqa: E402
from decoder.preamble import DATA_OFFSET, find_candidates  # noqa: E402
from decoder.recent import RecentlySeen  # noqa: E402
from decoder.samples import load_iq, magnitude  # noqa: E402

GOLDEN = REPO / "tests" / "golden"
EXPECTED_NOFIX_MISSES = {112, 185, 188, 193}  # decision #8
MATCH_WINDOW = 16  # samples between a golden line's fixture start and our start
# dump1090 at efe64db decodes the file in 262,144-byte buffers and stops before decoding the last,
# partial one: the reader sets Modes.exit at end of file (dump1090.c 496-498) and the decode loop
# checks it right after the previous buffer (2986-2989). So the golden files cover only the first
# 2 x 262,144 bytes = 262,144 samples of modes1.bin.
DUMP1090_DECODED_SAMPLES = 262_144


def golden_lines(mode: str, prefix: str = "modes1_raw") -> list[str]:
    return re.findall(r"\*([0-9a-f]+);", (GOLDEN / f"{prefix}_{mode}.txt").read_text())


def fixture(name: str = "modes1_starts.txt") -> dict[int, tuple[int, str, str]]:
    """Golden line -> (start sample, flag, disagreeing bits)."""
    rows = {}
    for text in (GOLDEN / name).read_text().splitlines():
        if not text.startswith("#"):
            line, start, flag, bits, _hex = text.split("\t")
            rows[int(line)] = (int(start), flag, bits)
    return rows


def align(
    golden: list[str], messages: list[Message], starts
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """(matched golden/ours index pairs, missing golden indices, extra our indices).

    Only golden lines present in `starts` are matched. A golden line matches one of our messages
    with the same hex whose start sample is within MATCH_WINDOW of the line's fixture start.
    Matching by hex alone is wrong here: the same message is often sent several times, so a copy
    could be credited to the wrong golden line.
    """
    unused = set(range(len(messages)))
    matched, missing = [], []
    for line in sorted(starts):
        msg_hex = golden[line]
        start = starts[line][0]
        found = next(
            (
                i
                for i in sorted(unused, key=lambda i: abs(messages[i].start - start))
                if messages[i].accepted.frame.hex == msg_hex
                and abs(messages[i].start - start) <= MATCH_WINDOW
            ),
            None,
        )
        if found is None:
            missing.append(line)
        else:
            matched.append((line, found))
            unused.remove(found)
    return matched, missing, sorted(unused)


def why_missing(
    mag, line: int, golden_hex: str, starts, candidates, messages: list[Message], fix: bool
) -> str:
    start, flag, bad_bits = starts[line]
    if flag == "approximate":
        note = f"start ~{start} (approximate); plain comparison disagrees at bits {bad_bits}"
    else:
        note = f"start {start} (exact)"
    covering = [
        m for m in messages if m.start < start < m.start + DATA_OFFSET + 2 * m.accepted.frame.n_bits
    ]
    if covering:
        m = covering[0]
        return f"{note}; skipped: inside our message at {m.start} ({m.accepted.frame.hex})"
    if start not in candidates:
        return f"{note}; no preamble candidate at this start"
    bits, ties = read_bits(mag, start)
    frame = to_frame(bits)
    if ties:
        return f"{note}; {ties} bit(s) with equal halves"
    recent = RecentlySeen()
    recent.add(int(golden_hex[2:8], 16), 0.0)  # give it every benefit of the doubt
    result = accept(frame, recent, 0.0, fix)
    verdict = "rejected" if result is None else result.how
    return f"{note}; our bits there: {frame.hex}; accept(): {verdict}"


def miss_class(start: int, flag: str, bad_bits: str, candidates: set[int]) -> str:
    """Sort a miss by where it fails: preamble, or how many bits plain comparison gets wrong."""
    if start not in candidates:
        return "preamble miss"
    wrong = [] if bad_bits == "-" else [int(b) for b in bad_bits.split(",")]
    if flag == "exact" or not wrong:
        return "other"
    if all(b < 5 for b in wrong):
        return "DF field only"
    if len(wrong) <= 5:
        return "few wrong bits (1-5)"
    if len(wrong) < 20:
        return "6-19 wrong bits"
    return "many wrong bits (20+)"


def half_sample_wrong_bits(mag, start: int, golden_hex: str) -> int:
    """Diagnostic only: fewest wrong bits when every half-bit is read half a sample earlier or
    later (linear interpolation between neighbouring samples), for starts within 3 samples."""
    n = len(golden_hex) * 4
    want = np.array([c == "1" for c in bin(int(golden_hex, 16))[2:].zfill(n)])
    best = n
    for s in range(start - 3, start + 4):
        x = s + DATA_OFFSET + 2 * np.arange(n)
        for shift in (-1, 1):  # half a sample earlier or later
            first = (mag[x] + mag[x + shift]) / 2
            second = (mag[x + 1] + mag[x + 1 + shift]) / 2
            best = min(best, int(((first > second) != want).sum()))
    return best


def overlapping_golden(start: int, starts) -> str:
    for line, (s, flag, _bits) in starts.items():
        if abs(s - start) <= MATCH_WINDOW:
            return f"near golden line {line} (start {s}, {flag})"
    return "not near any golden line"


def dump1090_preamble_failures(mag, j: int) -> list[str]:
    """Which of dump1090's preamble conditions fail at start j (diagnostic only; the conditions are
    dump1090.c 1602-1611 and 1624-1642 at efe64db, as described in docs/pseudocode.md stage 2)."""
    m = [float(mag[j + k]) for k in range(15)]
    level = (m[0] + m[2] + m[7] + m[9]) / 6
    shape = {
        "sample 0 above 1": m[0] > m[1],
        "sample 1 below 2": m[1] < m[2],
        "sample 2 above 3": m[2] > m[3],
        "sample 3 below pulse 0": m[3] < m[0],
        "sample 4 below pulse 0": m[4] < m[0],
        "sample 5 below pulse 0": m[5] < m[0],
        "sample 6 below pulse 0": m[6] < m[0],
        "sample 7 above 8": m[7] > m[8],
        "sample 8 below 9": m[8] < m[9],
        "sample 9 above 6": m[9] > m[6],
    }
    shape.update(
        {f"sample {k} below 2/3 pulse level": m[k] < level for k in (4, 5, 11, 12, 13, 14)}
    )
    return [name for name, ok in shape.items() if not ok]


def known_extras() -> list[tuple[int, str, str, str]]:
    rows = []
    for text in (GOLDEN / "known_extras.txt").read_text(encoding="utf-8").splitlines():
        if text and not text.startswith("#"):
            start, msg_hex, mode, reason = text.split("\t")
            rows.append((int(start), msg_hex, mode, reason))
    return rows


def explain_extra(mag, m: Message, mode: str) -> tuple[bool, str]:
    """Decision #8 (revised): an extra is explained only if (a) CRC-valid by remainder 0 on DF
    11/17/18 or address parity to a listed address, (b) all four pulses reach the floor,
    (c) a reason is documented, and (d) it's listed in tests/golden/known_extras.txt."""
    a = m.accepted.how in (How.CLEAN, How.ADDRESS_PARITY)
    b = all(mag[m.start + k] >= SIGNAL_FLOOR for k in (0, 2, 7, 9))
    listed = [
        reason
        for start, msg_hex, which, reason in known_extras()
        if abs(start - m.start) <= MATCH_WINDOW
        and msg_hex == m.accepted.frame.hex
        and which in (mode, "both")
    ]
    c = bool(listed and listed[0].strip())
    ok = a and b and c
    fails = dump1090_preamble_failures(mag, m.start)
    note = (
        f"(a) {'yes' if a else 'NO'}, (b) {'yes' if b else 'NO'}, (c)+(d) {'yes' if c else 'NO'}; "
        f"dump1090 preamble conditions failing here: {', '.join(fails) or 'none'}"
    )
    if listed:
        note += f"; known: {listed[0]}"
    return ok, note


def beyond_dump1090(message: Message) -> bool:
    """True if the frame ends past the part of the recording dump1090 decoded."""
    end = message.start + DATA_OFFSET + 2 * message.accepted.frame.n_bits
    return end > DUMP1090_DECODED_SAMPLES


def compare(mode: str, mag, starts) -> tuple[str, dict[str, int]]:
    fix = mode == "default"
    messages = decode_magnitudes(mag, fix)
    golden = golden_lines(mode)
    matched, missing, extra = align(golden, messages, starts)
    tail = [i for i in extra if beyond_dump1090(messages[i])]
    inside = [i for i in extra if not beyond_dump1090(messages[i])]
    candidates = set(map(int, find_candidates(mag, SIGNAL_FLOOR)))
    counts = {
        "ours": len(messages),
        "golden": len(golden),
        "matched": len(matched),
        "missing": len(missing),
        "extra_inside_decoded_region": len(inside),
        "extra_beyond_dump1090_region": len(tail),
    }
    classes = Counter(miss_class(*starts[line], candidates) for line in missing)
    out = [f"## {mode}", ""] + [f"- {k.replace('_', ' ')}: **{v}**" for k, v in counts.items()]
    out += ["", "Missing by class: " + ", ".join(f"{k}: {v}" for k, v in sorted(classes.items()))]
    out += ["", "### Missing (golden line: class; evidence)", ""]
    for line in missing:
        expected = " (expected, decision #8)" if not fix and line in EXPECTED_NOFIX_MISSES else ""
        why = why_missing(mag, line, golden[line], starts, candidates, messages, fix)
        half = half_sample_wrong_bits(mag, starts[line][0], golden[line])
        cls = miss_class(*starts[line], candidates)
        out.append(
            f"- line {line} `{golden[line]}`{expected}: **{cls}**; {why}; "
            f"diagnostic: reading half a sample off gives {half} wrong bits"
        )
    counts["missing_by_class"] = dict(classes)
    out += ["", "### Extra inside the region dump1090 decoded (our start: evidence)", ""]
    unexplained = 0
    for i in inside:
        m = messages[i]
        ok, note = explain_extra(mag, m, mode)
        unexplained += not ok
        timing = "" if m.timing_offset is None else f", timing re-read at {m.timing_offset:+.2f}"
        out.append(
            f"- start {m.start} `{m.accepted.frame.hex}` DF{m.accepted.frame.df}, "
            f"{m.accepted.how}{timing}; {overlapping_golden(m.start, starts)}; "
            f"**{'explained' if ok else 'UNEXPLAINED'}**: {note}"
        )
    counts["extra_unexplained_inside_decoded_region"] = unexplained
    out += [
        "",
        f"### Extra beyond sample {DUMP1090_DECODED_SAMPLES:,} (dump1090 never decoded this part)",
        "",
    ]
    tail_text, tail_counts = compare_tail(
        mode, golden, [messages[i] for i in tail], mag, candidates, fix
    )
    out += [tail_text, ""]
    counts.update(tail_counts)
    return "\n".join(out), counts


def compare_tail(
    mode: str, golden: list[str], tail: list[Message], mag, candidates: set[int], fix: bool
) -> tuple[str, dict[str, int]]:
    """Our messages past sample 262,144 against the supplementary padded golden file (decision
    #13), matched by start sample with tests/golden/modes1_tail_starts_<mode>.txt. This is the
    holdout: nothing is tuned on it."""
    padded = golden_lines(mode, prefix="modes1_padded_raw")
    assert padded[: len(golden)] == golden, "padded golden must extend the approved golden file"
    tail_starts = fixture(f"modes1_tail_starts_{mode}.txt")
    matched, missing, extra = align(padded, tail, tail_starts)
    out = []
    for line in missing:
        why = why_missing(mag, line, padded[line], tail_starts, candidates, tail, fix)
        cls = miss_class(*tail_starts[line], candidates)
        out.append(f"- padded golden line {line} `{padded[line]}`: **{cls}**; {why}")
    for j in extra:
        m = tail[j]
        timing = "" if m.timing_offset is None else f", timing re-read at {m.timing_offset:+.2f}"
        fails = dump1090_preamble_failures(mag, m.start)
        pulses = ", ".join(f"{float(mag[m.start + k]):.1f}" for k in (0, 2, 7, 9))
        out.append(
            f"- **extra** at start {m.start} `{m.accepted.frame.hex}` DF{m.accepted.frame.df}, "
            f"{m.accepted.how}{timing}; {overlapping_golden(m.start, tail_starts)}; "
            f"pulses {pulses}; dump1090 preamble conditions failing: {', '.join(fails) or 'none'}"
        )
    counts = {
        "tail_ours": len(tail),
        "tail_padded_golden": len(tail_starts),
        "tail_matched": len(matched),
        "tail_missing": len(missing),
        "tail_extra": len(extra),
    }
    head = [f"Against `modes1_padded_raw_{mode}.txt` (lines {len(golden)}-{len(padded) - 1}):", ""]
    head += [f"- {k.replace('_', ' ')}: **{v}**" for k, v in counts.items()]
    return "\n".join(head + [""] + out), counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, help="write the full markdown report here")
    args = parser.parse_args()
    mag = magnitude(load_iq(REPO / "data" / "modes1.bin"))
    starts = fixture()
    sections = []
    for mode in ("nofix", "default"):
        text, counts = compare(mode, mag, starts)
        print(mode, counts)
        sections.append(text)
    if args.report:
        header = (
            "# Phase 4 golden comparison\n\nGenerated by `scripts/compare_golden.py`.\n\n"
            "**Observation (not proven):** every extra found by the timing re-read arrives *early* "
            "(offset about -0.3 to -0.4 of a sample), and most extras fail dump1090's preamble "
            'condition "sample 6 below pulse 0". Early arrival spills pulse 7 into sample 6, so this '
            "looks like a systematic dump1090 blind spot for early-arriving frames. Six frames from one "
            "aircraft can't prove it; see `docs/decoder-notes.md` stage 3 and "
            "`tests/golden/known_extras_tail.txt`.\n\n"
        )
        args.report.write_text(header + "\n".join(sections), encoding="utf-8", newline="\n")
        print("wrote", args.report)


if __name__ == "__main__":
    main()
