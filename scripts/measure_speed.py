"""Measure decoder speed on modes1.bin against the 2,000,000 samples per second live use needs.

NOT part of the decoder. This is the one speed method for the project; both this script and
scripts/compare_golden.py --report call `measure()`, so every quoted number comes from it.

Method:
  - What is timed: `decode_file()` end to end, which is read file -> magnitude -> preamble
    candidates -> bits (with the timing re-read if on) -> CRC/repair/acceptance. Not timed:
    Python start-up and imports, field decoding (stage 6) and printing.
  - Warm-up: one untimed full decode first (file cache, first-call costs).
  - Runs: RUNS rounds in a single process; each round times all four configurations (no-fix /
    default x re-read off / on) once, interleaved, so changes in machine load hit them alike.
    Reports the best (headline) and the median (to show the spread) per configuration.
    Real-time factor = recording length / best time.
  - Per-stage breakdown: the same warm-up and RUNS, default mode with the re-read on.
  - Sessions: SESSIONS back-to-back runs of all of the above. The machine's speed drifts between
    sessions (one session ran about 50% slower than another), so the quoted figure is the range
    of the per-session best real-time factor. Quote the report, not memory.

Run:  python scripts/measure_speed.py
"""

from __future__ import annotations

import platform
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from decoder.pipeline import SIGNAL_FLOOR, decode_file, decode_magnitudes  # noqa: E402
from decoder.preamble import find_candidates  # noqa: E402
from decoder.samples import load_iq, magnitude  # noqa: E402

RECORDING = REPO / "data" / "modes1.bin"
LIVE_SAMPLES_PER_S = 2_000_000
RUNS = 20


def timed_ms(fn: Callable[[], object], runs: int = RUNS) -> tuple[float, float]:
    """(best, median) milliseconds over `runs` calls."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return min(times), statistics.median(times)


def measure(runs: int = RUNS) -> dict:
    """The project's speed measurement (see the module docstring for the method)."""
    samples = load_iq(RECORDING).size // 2
    radio_ms = samples / LIVE_SAMPLES_PER_S * 1000
    decode_file(RECORDING, fix=True)  # warm-up
    settings = [(fix, reread) for fix in (False, True) for reread in (False, True)]
    times: dict[tuple[bool, bool], list[float]] = {s: [] for s in settings}
    for _ in range(runs):  # interleaved, so a change in machine load hits every setting alike
        for fix, reread in settings:
            t0 = time.perf_counter()
            decode_file(RECORDING, fix=fix, timing_reread=reread)
            times[(fix, reread)].append((time.perf_counter() - t0) * 1000)
    configs = [
        {
            "mode": "default" if fix else "no-fix",
            "timing_reread": reread,
            "best_ms": min(times[(fix, reread)]),
            "median_ms": statistics.median(times[(fix, reread)]),
            "realtime_factor": radio_ms / min(times[(fix, reread)]),
        }
        for fix, reread in settings
    ]
    iq = load_iq(RECORDING)
    mag = magnitude(iq)
    candidates_best, _ = timed_ms(lambda: find_candidates(mag, SIGNAL_FLOOR), runs)
    decode_best, _ = timed_ms(lambda: decode_magnitudes(mag, fix=True), runs)
    stages = {
        "read file (load_iq)": timed_ms(lambda: load_iq(RECORDING), runs)[0],
        "samples to magnitude": timed_ms(lambda: magnitude(iq), runs)[0],
        "preamble candidates": candidates_best,
        "bits, timing re-read, CRC, acceptance (Python loop)": decode_best - candidates_best,
    }
    return {
        "samples": samples,
        "radio_ms": radio_ms,
        "runs": runs,
        "machine": f"{platform.processor()}, Python {platform.python_version()}",
        "configs": configs,
        "stages": stages,
    }


SESSIONS = 3


def join_ms(values) -> str:
    return ", ".join(f"{v:.1f}" for v in values)


def as_markdown(sessions: list[dict]) -> str:
    """Speed section from several sessions of `measure()`: the per-session best real-time
    factor gives the range quoted everywhere; medians show the spread within sessions."""
    first = sessions[0]
    rows = [
        "## Speed",
        "",
        f"Method (`scripts/measure_speed.py`): `decode_file()` end to end (read file, magnitude, "
        f"preamble candidates, bits with the timing re-read, CRC/repair/acceptance; not Python "
        f"start-up, field decoding or printing). Per session: one warm-up run, then "
        f"{first['runs']} rounds, each timing all four configurations once (interleaved). "
        f"{len(sessions)} sessions back to back; the machine's speed drifts between sessions, so "
        f"the range across sessions is the number to quote. Recording: {first['samples']:,} "
        f"samples = {first['radio_ms']:.1f} ms of radio. Machine: {first['machine']}.",
        "",
        "| Mode | Timing re-read | Best per session (ms) | Median per session (ms) "
        "| Real-time factor range |",
        "|---|---|---|---|---|",
    ]
    for i, c in enumerate(first["configs"]):
        per = [s["configs"][i] for s in sessions]
        factors = [p["realtime_factor"] for p in per]
        best = join_ms(p["best_ms"] for p in per)
        median = join_ms(p["median_ms"] for p in per)
        reread = "on" if c["timing_reread"] else "off"
        rows.append(
            f"| {c['mode']} | {reread} | {best} | {median} | "
            f"{min(factors):.1f}x to {max(factors):.1f}x |"
        )
    rows += ["", "Per stage, default mode with the re-read on (best per session, ms):", ""]
    for name in first["stages"]:
        rows.append(f"- {name}: {join_ms(s['stages'][name] for s in sessions)}")
    rows += [
        "",
        "Caveat: one strong aircraft. Live traffic has many more candidates, and the Python loop",
        "grows with them; measure on my own recordings (ROADMAP Phase 5).",
    ]
    return "\n".join(rows)


def main() -> None:
    print(as_markdown([measure() for _ in range(SESSIONS)]))


if __name__ == "__main__":
    main()
