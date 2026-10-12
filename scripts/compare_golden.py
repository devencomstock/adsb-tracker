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
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from decoder.accept import How, accept  # noqa: E402
from decoder.bits import read_bits, to_frame  # noqa: E402
from decoder.crc import repair_single_bit  # noqa: E402
from decoder.frame import Frame  # noqa: E402
from decoder.pipeline import SIGNAL_FLOOR, Message, decode_magnitudes  # noqa: E402
from decoder.preamble import (  # noqa: E402
    DATA_OFFSET,
    FAR_QUIET,
    FAR_QUIET_LIMIT,
    PULSE_NEIGHBOURS,
    PULSES,
    find_candidates,
)
from decoder.recent import RecentlySeen  # noqa: E402
from decoder.samples import load_iq, magnitude  # noqa: E402
from decoder.timing import hypotheses, offset_estimate, reread_bits  # noqa: E402

GOLDEN = REPO / "tests" / "golden"
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


def our_preamble_failures(mag, j: int) -> str:
    """Which parts of our own preamble test (decision #14) fail at start j."""
    shape = [f"pulse {p} > sample {q}" for p, q in PULSE_NEIGHBOURS if not mag[j + p] > mag[j + q]]
    mean = sum(mag[j + k] for k in PULSES) / len(PULSES)
    gaps = [f"sample {q}" for q in FAR_QUIET if not mag[j + q] < FAR_QUIET_LIMIT * mean]
    weakest = min(mag[j + k] for k in PULSES)
    parts = []
    if shape:
        parts.append("shape fails: " + ", ".join(shape))
    if gaps:
        parts.append("too loud away from pulses: " + ", ".join(gaps))
    if weakest < SIGNAL_FLOOR:
        parts.append(f"weakest pulse {weakest:.1f} below the floor")
    return "; ".join(parts) or "passes"


def explain_miss(
    mag, golden_hex: str, start: int, messages: list[Message], candidates: set[int], fix: bool
) -> str:
    """A plain-English reason a golden line is missing, derived from the evidence."""
    for m in messages:
        if abs(m.start - start) <= MATCH_WINDOW and len(m.accepted.frame.hex) == len(golden_hex):
            diff = m.accepted.frame.value ^ Frame.from_hex(golden_hex).value
            bits = [
                k
                for k in range(m.accepted.frame.n_bits)
                if (diff >> (m.accepted.frame.n_bits - 1 - k)) & 1
            ]
            return (
                f"same transmission read differently: our message at {m.start} differs in bit(s) "
                f"{bits} (stage 4c bit-55 ambiguity if bit 55 of a DF 11)"
            )
    if not any(j in candidates for j in range(start - 3, start + 4)):
        failures = our_preamble_failures(mag, start)
        return f"preamble miss: no candidate within 3 samples; at {start} our test: {failures}"
    for offset in hypotheses(offset_estimate(mag, start)):
        frame = to_frame(reread_bits(mag, start, offset))
        if frame.hex == golden_hex:
            return f"timing re-read at {offset:+.2f} reads it, but another candidate came first"
        repaired = repair_single_bit(frame)
        if repaired is not None and repaired[0].hex == golden_hex:
            note = "no-fix mode doesn't repair" if not fix else "repair should have taken it"
            return (
                f"timing re-read at {offset:+.2f} leaves exactly one wrong bit "
                f"(bit {repaired[1]}); single-bit repair would fix it, but {note}"
            )
    return "not explained automatically; see the evidence"


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
    out += ["", "### Missing (golden line: class; explanation; evidence)", ""]
    explained = 0
    for line in missing:
        why = why_missing(mag, line, golden[line], starts, candidates, messages, fix)
        cls = miss_class(*starts[line], candidates)
        reason = explain_miss(mag, golden[line], starts[line][0], messages, candidates, fix)
        explained += not reason.startswith("not explained")
        out.append(f"- line {line} `{golden[line]}`: **{cls}**. **Explanation:** {reason}.")
        out.append(f"  - Evidence for the plain read: {why}")
    counts["missing_by_class"] = dict(classes)
    counts["missing_explained"] = explained
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
    sections, all_counts = [], {}
    for mode in ("nofix", "default"):
        text, counts = compare(mode, mag, starts)
        print(mode, counts)
        sections.append(text)
        all_counts[mode] = counts
    if args.report:
        level1 = run_level1_tests()
        speed = speed_section()
        header = [
            "# Phase 4 golden comparison",
            "",
            "Generated by `scripts/compare_golden.py --report docs/phase4-golden-report.md`.",
            "The approved golden files cover samples 0-262,143 of `modes1.bin` (decision #13).",
            "The tail after that is a holdout, reported per mode below and never tuned on.",
            "",
            decision8_status(all_counts, level1),
            "",
            speed,
            "",
            "**Observation (not proven):** every extra found by the timing re-read arrives *early* "
            "(offset about -0.3 to -0.4 of a sample), and most extras fail dump1090's preamble "
            'condition "sample 6 below pulse 0". Early arrival spills pulse 7 into sample 6, '
            "so this looks like a systematic dump1090 blind spot for early-arriving frames. "
            "Six frames from one aircraft can't prove it; see `docs/decoder-notes.md` stage 3 and "
            "`tests/golden/known_extras_tail.txt`.",
            "",
        ]
        args.report.write_text(
            "\n".join(header) + "\n" + "\n".join(sections), encoding="utf-8", newline="\n"
        )
        print("wrote", args.report)


def run_level1_tests() -> str:
    """Decision #8 level 1 (bit-level stages on the golden hex) is checked by these tests."""
    files = ["tests/test_golden_bitlevel.py", "tests/test_golden_fields.py"]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *files],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    summary = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "no output"
    return f"`pytest {' '.join(files)}`: {summary}"


def decision8_status(counts: dict[str, dict], level1: str) -> str:
    """Decision #8 (revised) dongle conditions, per mode."""
    rows = ["## Decision #8 dongle conditions", ""]
    rows += [f"- **Level 1, bit-level stages 100% on the golden hex:** {level1}"]
    for mode, c in counts.items():
        ok_missing = c["missing"] <= 10
        ok_explained = c["missing_explained"] == c["missing"]
        ok_extras = c["extra_unexplained_inside_decoded_region"] == 0

        def met(ok: bool) -> str:
            return "met" if ok else "NOT met"

        rows.append(
            f"- **{mode}:** missing {c['missing']} (limit 10: {met(ok_missing)}); "
            f"misses explained {c['missing_explained']}/{c['missing']} ({met(ok_explained)}); "
            f"unexplained extras inside the decoded region "
            f"{c['extra_unexplained_inside_decoded_region']} ({met(ok_extras)}); "
            f"holdout tail: {c['tail_matched']}/{c['tail_padded_golden']} matched, "
            f"{c['tail_extra']} extra (reported only)"
        )
    rows.append("- **Speed measurement reported:** yes, see below.")
    return "\n".join(rows)


def speed_section() -> str:
    """End-to-end speed and a per-stage breakdown (scripts/measure_speed.py)."""
    from measure_speed import RECORDING, best_time, stage_breakdown

    samples = load_iq(RECORDING).size // 2
    rows = ["## Speed", "", f"`modes1.bin`: {samples:,} samples = {samples / 2e6:.3f} s of radio."]
    rows += ["", "| Mode | Timing re-read | Best of 10 | Real-time factor |", "|---|---|---|---|"]
    for fix in (False, True):
        for reread in (False, True):
            seconds, _count = best_time(fix, reread)
            rows.append(
                f"| {'default' if fix else 'no-fix'} | {'on' if reread else 'off'} | "
                f"{seconds * 1000:.1f} ms | {samples / seconds / 2e6:.1f}x |"
            )
    rows += ["", "Per stage, default mode with the re-read on (best of 10):", ""]
    rows += [f"- {name}: {ms:.1f} ms" for name, ms in stage_breakdown().items()]
    rows += [
        "",
        "Caveat: one strong aircraft. Live traffic has many more candidates, and the decode loop",
        "(Python, per candidate) grows with them; measure on my own recordings (ROADMAP Phase 5).",
    ]
    return "\n".join(rows)


if __name__ == "__main__":
    main()
