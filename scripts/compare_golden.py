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
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from decoder.accept import accept  # noqa: E402
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


def golden_lines(mode: str) -> list[str]:
    return re.findall(r"\*([0-9a-f]+);", (GOLDEN / f"modes1_raw_{mode}.txt").read_text())


def fixture() -> dict[int, tuple[int, str, str]]:
    """Golden line -> (start sample, flag, disagreeing bits)."""
    rows = {}
    for text in (GOLDEN / "modes1_starts.txt").read_text().splitlines():
        if not text.startswith("#"):
            line, start, flag, bits, _hex = text.split("\t")
            rows[int(line)] = (int(start), flag, bits)
    return rows


def align(
    golden: list[str], messages: list[Message], starts
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """(matched golden/ours index pairs, missing golden indices, extra our indices).

    A golden line matches one of our messages with the same hex whose start sample is within
    MATCH_WINDOW of the line's fixture start. Matching by hex alone is wrong here: the same
    message is often sent several times, so a copy could be credited to the wrong golden line.
    """
    unused = set(range(len(messages)))
    matched, missing = [], []
    for line, msg_hex in enumerate(golden):
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


def overlapping_golden(start: int, starts) -> str:
    for line, (s, flag, _bits) in starts.items():
        if abs(s - start) <= MATCH_WINDOW:
            return f"near golden line {line} (start {s}, {flag})"
    return "not near any golden line"


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
    out = [f"## {mode}", ""] + [f"- {k.replace('_', ' ')}: **{v}**" for k, v in counts.items()]
    out += ["", "### Missing (golden line: evidence)", ""]
    for line in missing:
        expected = " (expected, decision #8)" if not fix and line in EXPECTED_NOFIX_MISSES else ""
        why = why_missing(mag, line, golden[line], starts, candidates, messages, fix)
        out.append(f"- line {line} `{golden[line]}`{expected}: {why}")
    out += ["", "### Extra inside the region dump1090 decoded (our start: evidence)", ""]
    for i in inside:
        m = messages[i]
        out.append(
            f"- start {m.start} `{m.accepted.frame.hex}` DF{m.accepted.frame.df}, "
            f"{m.accepted.how}; {overlapping_golden(m.start, starts)}"
        )
    out += [
        "",
        f"### Extra beyond sample {DUMP1090_DECODED_SAMPLES:,} (dump1090 never decoded this part)",
        "",
    ]
    for i in tail:
        m = messages[i]
        out.append(
            f"- start {m.start} `{m.accepted.frame.hex}` DF{m.accepted.frame.df}, {m.accepted.how}"
        )
    out.append("")
    return "\n".join(out), counts


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
        header = "# Phase 4 golden comparison\n\nGenerated by `scripts/compare_golden.py`.\n\n"
        args.report.write_text(header + "\n".join(sections), encoding="utf-8", newline="\n")
        print("wrote", args.report)


if __name__ == "__main__":
    main()
