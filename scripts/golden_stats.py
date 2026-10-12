"""Reproduce the golden-file numbers quoted in docs/pseudocode.md and decision #7.

NOT part of the decoder. It reads the dump1090 answer key in tests/golden/ (and, with --trace,
the recording in data/) and prints:
  1. message counts per downlink format, frame length and DF17 type code, for each raw file;
  2. a partition of every frame into exactly one acceptance category, replayed in file order
     under the "seen earlier in the recording" rule (the categories sum to 217);
  3. the frames dump1090 repaired in the default run, compared with the no-fix file;
  4. which DF11 remainders below 80 collide with a single-bit-error remainder;
  5. with --trace: sample-level numbers for the hand trace and for the repaired frames.

Sources for the rules used here (pinned dump1090 commit efe64db, see tests/golden/README.md):
frame length dump1090.c 746-753; single-bit repair for DF11/17/18 before any other check
1112-1127 (positions 5-111 of a 112-bit frame, 806; shifted for 56-bit frames, 874-880);
address-parity formats 947-953; list filled only from clean, unrepaired DF11/17/18 frames
1197-1200; DF11 remainder below 80 accepted as an interrogator ID 1202-1209.

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
IID_LIMIT = 80
TRACE_MSG = "8f4d2023587f345e35837e2218b2"
CRC_EXAMPLES = ("8f4d2023587f345e35837e2218b2", "5d4d20237a55a7", "20000f1f684a6c")

# Start sample of each repaired frame (golden line index -> start sample, how sure).
# Found with scripts/dump1090_prefix_search.sh (shortest prefix after which dump1090 --no-fix
# outputs that line; start = prefix end - 16 - 2 * bits), then checked with --trace below.
REPAIRED_STARTS = {
    112: (123821, "located: prefix gives 123820; plain comparison aligns 1 sample later"),
    128: (144765, "approximate: best plain-comparison alignment, 5 bits differ"),
    174: (198770, "approximate: weak signal, best plain-comparison alignment, 14 bits differ"),
    185: (222008, "confirmed: plain comparison differs only at the repaired bit"),
    188: (229407, "confirmed: plain comparison differs only at the repaired bit"),
    193: (231307, "confirmed: plain comparison differs only at the repaired bit"),
}


def read_raw(path: Path) -> list[str]:
    """Hex messages from a dump1090 --raw file, in file order."""
    return re.findall(r"\*([0-9a-f]+);", path.read_text())


def repaired_bits(decoded: Path) -> dict[int, int]:
    """Message index -> bit position dump1090 reported as 'Single bit error fixed'."""
    index, fixed = -1, {}
    for line in decoded.read_text().splitlines():
        if line.startswith("*"):
            index += 1
        elif m := re.match(r"Single bit error fixed, bit (\d+)", line):
            fixed[index] = int(m.group(1))
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


def is_power_of_two(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0


def print_counts(name: str, msgs: list[str]) -> None:
    by_df = Counter((downlink_format(h), len(h) * 4) for h in msgs)
    tc = Counter(int(h[8:10], 16) >> 3 for h in msgs if downlink_format(h) == 17)
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


def categorize(msgs: list[str], repaired: dict[int, int]) -> list[str]:
    """Put every frame in exactly one category, replaying the recently-seen list in file order."""
    seen: set[str] = set()
    categories = []
    for i, h in enumerate(msgs):
        df, rem = downlink_format(h), crc_remainder(h)
        address = h[2:8] if df in CLEAN_SOURCE_DFS else f"{rem:06x}"
        listed = "seen earlier" if address in seen else "NOT seen earlier"
        if df in CLEAN_SOURCE_DFS and rem == 0 and i in repaired:
            cat = f"DF{df} repaired one bit, then remainder 0 (not a list source)"
        elif df in CLEAN_SOURCE_DFS and rem == 0:
            cat = f"DF{df} remainder 0, no repair (list source)"
            seen.add(h[2:8])
        elif df == 11 and rem < IID_LIMIT:
            cat = f"DF11 interrogator ID, list-dependent, {listed}"
        elif df in ADDRESS_PARITY_DFS:
            cat = f"DF{df} address parity -> {rem:06x}, list-dependent, {listed}"
        else:
            cat = f"DF{df} UNEXPECTED (remainder {rem:06x})"
        categories.append(cat)
    return categories


def print_partition(name: str, msgs: list[str], repaired: dict[int, int]) -> None:
    cats = Counter(categorize(msgs, repaired))
    print(f"{name}: every frame in exactly one category")
    for df in sorted({downlink_format(h) for h in msgs}):
        rows = {k: v for k, v in cats.items() if k.startswith(f"DF{df} ")}
        total = sum(1 for h in msgs if downlink_format(h) == df)
        for key, count in sorted(rows.items()):
            print(f"  {key}: {count}")
        print(f"    = DF{df} total {sum(rows.values())} (file has {total})")
    dependent = sum(v for k, v in cats.items() if "list-dependent" in k)
    exceptions = sum(v for k, v in cats.items() if "NOT seen" in k or "UNEXPECTED" in k)
    print(f"  all categories: {sum(cats.values())} (file has {len(msgs)})")
    print(f"  list-dependent messages: {dependent}; exceptions: {exceptions}")


def print_repaired(nofix: list[str], default: list[str], repaired: dict[int, int]) -> None:
    print("Frames repaired in the default run (lines align: both files list the same 217 frames)")
    for i, bit in sorted(repaired.items()):
        h_nofix, h_default = nofix[i], default[i]
        rem = crc_remainder(h_nofix)
        df = downlink_format(h_default)
        start, how = REPAIRED_STARTS[i]
        power = "yes" if is_power_of_two(rem) else "no"
        same = "same hex" if h_nofix == h_default else "hex differs"
        print(f"  line {i:3d} DF{df} repaired bit {bit:3d}  start sample {start} ({how})")
        print(f"      no-fix  {h_nofix}  remainder {rem:06x}  power of two: {power}")
        print(f"      default {h_default}  ({same})")


def print_iid_collisions(nofix: list[str]) -> None:
    """Remainders below 80 that a single flipped bit in a 56-bit frame can produce."""
    singles = {}
    for pos in range(5, 56):  # dump1090 never repairs bits 0-4 of a 112-bit frame (806)
        singles[crc_remainder(f"{1 << (55 - pos):014x}")] = pos
    low = sorted((s, p) for s, p in singles.items() if s < IID_LIMIT)
    print("Single-bit remainders below 80 in a 56-bit frame (remainder: bit position):")
    print("  " + ", ".join(f"{s}: bit {p}" for s, p in low))
    iids = Counter(
        crc_remainder(h)
        for h in nofix
        if downlink_format(h) == 11 and 0 < crc_remainder(h) < IID_LIMIT
    )
    print("DF11 interrogator-ID remainders in the no-fix file (value: count, * = collides):")
    print(
        "  " + ", ".join(f"{v}{'*' if v in singles else ''}: {n}" for v, n in sorted(iids.items()))
    )


def single_bit_repair(msg_hex: str) -> str:
    """dump1090's default repair: DF11/17/18 with a nonzero remainder that equals the remainder of
    one flipped bit gets that bit flipped back (1112-1127). Eligible positions are 5-111 of a
    112-bit frame (806); a 56-bit frame uses the same positions shifted by 56 (874-880)."""
    df, rem = downlink_format(msg_hex), crc_remainder(msg_hex)
    if df not in CLEAN_SOURCE_DFS or rem == 0:
        return msg_hex
    n = len(msg_hex) * 4
    first_eligible = 5 if n == 112 else 0
    for pos in range(first_eligible, n):
        if crc_remainder(f"{1 << (n - 1 - pos):0{n // 4}x}") == rem:
            return f"{int(msg_hex, 16) ^ (1 << (n - 1 - pos)):0{n // 4}x}"
    return msg_hex


def print_repair_check(nofix: list[str], default: list[str]) -> None:
    repaired = [single_bit_repair(h) for h in nofix]
    changed = [i for i, (a, b) in enumerate(zip(nofix, repaired, strict=True)) if a != b]
    print("No-fix golden hex after dump1090-style single-bit repair:")
    print(f"  lines changed: {changed}; equals modes1_raw_default.txt: {repaired == default}")


def print_crc_examples() -> None:
    print("CRC examples used in stage 4:")
    for h in CRC_EXAMPLES:
        data_only = f"{(int(h, 16) >> 24) << 24:0{len(h)}x}"
        print(
            f"  {h}: DF{downlink_format(h)} remainder={crc_remainder(h):06x} "
            f"crc(data)={crc_remainder(data_only):06x} parity={h[-6:]}"
        )


def trace(recording: Path, nofix: list[str], default: list[str]) -> None:
    """Sample-level numbers (needs NumPy and the recording). Finding answers, not decoding."""
    import numpy as np

    raw = np.fromfile(recording, dtype=np.uint8)
    i = raw[0::2].astype(np.int32) - 127
    q = raw[1::2].astype(np.int32) - 127
    mag = np.sqrt(i * i + q * q)

    def plain_bits(j: int, nbits: int) -> np.ndarray:
        return mag[j + 16 : j + 16 + 2 * nbits : 2] > mag[j + 17 : j + 17 + 2 * nbits : 2]

    def bits_of(h: str) -> np.ndarray:
        return np.array([c == "1" for c in bin(int(h, 16))[2:].zfill(len(h) * 4)])

    nbits = len(TRACE_MSG) * 4
    want = bits_of(TRACE_MSG)
    starts = [
        j for j in range(mag.size - (16 + 2 * nbits)) if np.array_equal(plain_bits(j, nbits), want)
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

    print("  repaired frames: bits where a plain half-vs-half comparison disagrees")
    for line, (start, _) in sorted(REPAIRED_STARTS.items()):
        n = len(nofix[line]) * 4
        got = plain_bits(start, n)
        d_nofix = np.nonzero(got != bits_of(nofix[line]))[0].tolist()
        d_default = np.nonzero(got != bits_of(default[line]))[0].tolist()
        print(f"    line {line} start {start}: vs no-fix {d_nofix}; vs default {d_default}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trace", action="store_true", help="also print the sample-level trace")
    parser.add_argument("--recording", type=Path, default=REPO / "data" / "modes1.bin")
    args = parser.parse_args()

    files = {}
    for mode in ("nofix", "default"):
        msgs = read_raw(GOLDEN / f"modes1_raw_{mode}.txt")
        repaired = repaired_bits(GOLDEN / f"modes1_decoded_{mode}.txt")
        files[mode] = (msgs, repaired)
        print_counts(f"modes1_raw_{mode}.txt", msgs)
        print_partition(f"modes1_raw_{mode}.txt", msgs, repaired)
        print()
    nofix, default = files["nofix"][0], files["default"][0]
    print_repaired(nofix, default, files["default"][1])
    print()
    print_iid_collisions(nofix)
    print()
    print_repair_check(nofix, default)
    print()
    print_crc_examples()
    if args.trace:
        print()
        trace(args.recording, nofix, default)


if __name__ == "__main__":
    main()
