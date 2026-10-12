"""Measure decoder speed on modes1.bin against the 2,000,000 samples per second live use needs.

NOT part of the decoder. Times the whole pipeline (load, magnitude, candidates, reads, CRC) per
mode, with and without the timing re-read (stage 3d), best of several runs.

Run:  python scripts/measure_speed.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from decoder.pipeline import SIGNAL_FLOOR, decode_file, decode_magnitudes  # noqa: E402
from decoder.preamble import find_candidates  # noqa: E402
from decoder.samples import load_iq, magnitude  # noqa: E402

RECORDING = REPO / "data" / "modes1.bin"
LIVE_SAMPLES_PER_S = 2_000_000
RUNS = 10


def best_time(fix: bool, timing_reread: bool) -> tuple[float, int]:
    times, count = [], 0
    for _ in range(RUNS):
        t0 = time.perf_counter()
        count = len(decode_file(RECORDING, fix=fix, timing_reread=timing_reread))
        times.append(time.perf_counter() - t0)
    return min(times), count


def stage_breakdown(runs: int = RUNS) -> dict[str, float]:
    """Best-of-`runs` milliseconds per stage, default mode with the timing re-read on."""

    def best(fn) -> float:
        times = []
        for _ in range(runs):
            t0 = time.perf_counter()
            fn()
            times.append(time.perf_counter() - t0)
        return min(times) * 1000

    iq = load_iq(RECORDING)
    mag = magnitude(iq)
    load_ms = best(lambda: load_iq(RECORDING))
    magnitude_ms = best(lambda: magnitude(iq))
    candidates_ms = best(lambda: find_candidates(mag, SIGNAL_FLOOR))
    decode_ms = best(lambda: decode_magnitudes(mag, fix=True))  # includes finding candidates
    return {
        "read file (load_iq)": load_ms,
        "samples to magnitude": magnitude_ms,
        "preamble candidates": candidates_ms,
        "bits, timing re-read, CRC, acceptance (per candidate, Python)": decode_ms - candidates_ms,
    }


def main() -> None:
    samples = load_iq(RECORDING).size // 2
    print(f"{RECORDING.name}: {samples:,} samples = {samples / LIVE_SAMPLES_PER_S:.3f} s of radio")
    decode_file(RECORDING, fix=True)  # warm-up: file cache, imports, first-call costs
    for fix in (False, True):
        for timing_reread in (False, True):
            seconds, count = best_time(fix, timing_reread)
            rate = samples / seconds
            mode = "default" if fix else "no-fix"
            reread = "on" if timing_reread else "off"
            print(
                f"  {mode:7s} timing re-read {reread:3s}: {seconds * 1000:6.1f} ms, "
                f"{count} messages, {rate / 1e6:5.2f} M samples/s = "
                f"{rate / LIVE_SAMPLES_PER_S:4.1f}x real time"
            )
    print("  per stage (default, re-read on):")
    for name, ms in stage_breakdown().items():
        print(f"    {name}: {ms:.1f} ms")


if __name__ == "__main__":
    main()
