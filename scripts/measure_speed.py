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

from decoder.pipeline import decode_file  # noqa: E402
from decoder.samples import load_iq  # noqa: E402

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


if __name__ == "__main__":
    main()
