"""Reproduce the golden-file numbers quoted in docs/pseudocode.md and decision #7.

NOT part of the decoder. It reads the dump1090 answer key in tests/golden/ (and, with --trace,
the recording in data/) and prints:
  1. message counts per downlink format, frame length and DF17 type code, for each raw file;
  2. a replay of each file under the "seen earlier in the recording" rule: which messages depend
     on the recently-seen list (DF11 with an interrogator ID, address-parity formats) and whether
     their address was already listed;
  3. with --trace: the sample-level numbers for the hand trace of the first golden message.

Sources for the rules used here (pinned dump1090 commit efe64db, see tests/golden/README.md):
frame length dump1090.c 746-753; address-parity formats 947-953; list filled only from clean,
unrepaired DF11/17/18 frames 1197-1200; DF11 remainder below 80 accepted 1202-1209.

Run:  python scripts/golden_stats.py            (golden files only)
      python scripts/golden_stats.py --trace    (also needs data/modes1.bin)
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden"
GENERATOR = 0x1FFF409
LONG_DFS = {16, 17, 18, 19, 20, 21}
ADDRESS_PARITY_DFS = {0, 4, 5, 16, 20, 21, 24}
CLEAN_SOURCE_DFS = {11, 17, 18}
TRACE_MSG = "8f4d2023587f345e35837e2218b2"
CRC_EXAMPLES = ("8f4d2023587f345e35837e2218b2", "5d4d20237a55a7", "20000f1f684a6c")


def read_raw(path: Path) -> list[str]:
    """Hex messages from a dump1090 --raw file, in file order."""
    return re.findall(r"\*([0-9a-f]+);", path.read_text())


def fixed_indices(decoded: Path) -> set[int]:
    """Indices (message order) that dump1090 reported as single-bit fixed."""
    index, fixed = -1, set()
    for line in decoded.read_text().splitlines():
        if line.startswith("*"):
            index += 1
        elif line.startswith("Single bit error fixed"):
            fixed.add(index)
    return fixed


def crc_remainder(msg_hex: str) -> int:
    """24-bit remainder of the whole message divided by the generator (XOR long division)."""
    n = len(msg_hex) * 4
    reg = int(msg_hex, 16)
    for i in range(n - 24):
        if (reg >> (n - 1 - i)) & 1:
            reg ^= GENERATOR << (n - 25 - i)
    return reg & 0xFFFFFF


def downlink_format(msg_hex: str) -> int:
    return int(msg_hex[:2], 16) >> 3


def print_counts(name: str, msgs: list[str]) -> None:
    by_df = Counter((downlink_format(h), len(h) * 4) for h in msgs)
    df17 = [h for h in msgs if downlink_format(h) == 17]
    tc = Counter(int(h[8:10], 16) >> 3 for h in df17)
    print(f"{name}: {len(msgs)} messages")
    for (df, bits), count in sorted(by_df.items(), key=lambda kv: -kv[1]):
        rule = 112 if df in LONG_DFS else 56
        note = "" if bits == rule else f"  MISMATCH: length rule says {rule}"
        print(f"  DF{df:<2} {bits:>3} bits: {count}{note}")
    print("  DF17 by type code:", ", ".join(f"TC{k}={v}" for k, v in sorted(tc.items())))
    print(
        "  ICAO addresses (DF11/17/18):",
        sorted({h[2:8] for h in msgs if downlink_format(h) in CLEAN_SOURCE_DFS}),
    )


def replay(name: str, msgs: list[str], fixed: set[int]) -> None:
    """Replay in file order with the 'seen earlier in the recording' rule."""
    seen: set[str] = set()
    stats: Counter[str] = Counter()
    for i, h in enumerate(msgs):
        df, rem = downlink_format(h), crc_remainder(h)
        if df in CLEAN_SOURCE_DFS:
            icao = h[2:8]
            if rem == 0:
                stats[f"DF{df} clean"] += 1
                if i in fixed:
                    stats[f"DF{df} clean only after a fix (not added to list)"] += 1
                else:
                    seen.add(icao)
            elif df == 11 and rem < 80:
                stats[
                    "list-dependent: DF11 interrogator ID, "
                    + ("seen earlier" if icao in seen else "NOT seen earlier")
                ] += 1
            else:
                stats[f"DF{df} unexpected remainder {rem:06x}"] += 1
        elif df in ADDRESS_PARITY_DFS:
            addr = f"{rem:06x}"
            stats[
                f"list-dependent: address parity DF{df} -> {addr}, "
                + ("seen earlier" if addr in seen else "NOT seen earlier")
            ] += 1
        else:
            stats[f"DF{df} not handled"] += 1
    dependent = sum(v for k, v in stats.items() if k.startswith("list-dependent"))
    unexplained = sum(
        v for k, v in stats.items() if "NOT seen" in k or "unexpected" in k or "not handled" in k
    )
    print(f"{name}: replay with 'seen earlier in the recording'")
    for key, count in sorted(stats.items()):
        print(f"  {key}: {count}")
    print(f"  total list-dependent messages: {dependent}; exceptions: {unexplained}")


def trace(recording: Path) -> None:
    """Sample-level numbers for the hand trace (needs NumPy and the recording)."""
    import numpy as np

    raw = np.fromfile(recording, dtype=np.uint8)
    i = raw[0::2].astype(np.int32) - 127
    q = raw[1::2].astype(np.int32) - 127
    mag = np.sqrt(i * i + q * q)
    nbits = len(TRACE_MSG) * 4
    want = np.array([int(b) for b in bin(int(TRACE_MSG, 16))[2:].zfill(nbits)], dtype=np.int8)
    # Template match against the KNOWN bits (finding the answer, not decoding).
    starts = [
        j
        for j in range(mag.size - (16 + 2 * nbits))
        if np.array_equal(
            (mag[j + 16 : j + 16 + 2 * nbits : 2] > mag[j + 17 : j + 17 + 2 * nbits : 2]), want
        )
    ]
    print(f"trace: {raw.size} bytes, {mag.size} samples, median magnitude {np.median(mag):.1f}")
    print(f"  {TRACE_MSG} starts at samples {starts}")
    j = starts[0]
    print("  preamble offset: I Q -> magnitude")
    for k in range(16):
        s = j + k
        print(f"    {k:2d}: {int(raw[2 * s]):3d} {int(raw[2 * s + 1]):3d} -> {mag[s]:.1f}")
    print("  first 8 bits: first half, second half -> bit")
    for b in range(8):
        a, c = mag[j + 16 + 2 * b], mag[j + 17 + 2 * b]
        print(f"    bit {b}: {a:.1f}, {c:.1f} -> {int(a > c)}")


def print_crc_examples() -> None:
    print("CRC examples used in stage 4:")
    for h in CRC_EXAMPLES:
        data_only = f"{(int(h, 16) >> 24) << 24:0{len(h)}x}"
        print(
            f"  {h}: DF{downlink_format(h)} remainder={crc_remainder(h):06x} "
            f"crc(data)={crc_remainder(data_only):06x} parity={h[-6:]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trace", action="store_true", help="also print the sample-level trace")
    parser.add_argument("--recording", type=Path, default=REPO / "data" / "modes1.bin")
    args = parser.parse_args()

    for mode in ("nofix", "default"):
        msgs = read_raw(GOLDEN / f"modes1_raw_{mode}.txt")
        print_counts(f"modes1_raw_{mode}.txt", msgs)
        replay(f"modes1_raw_{mode}.txt", msgs, fixed_indices(GOLDEN / f"modes1_decoded_{mode}.txt"))
        print()
    print_crc_examples()
    if args.trace:
        print()
        trace(args.recording)


if __name__ == "__main__":
    main()
