"""Build tests/golden/modes1_starts.txt: the start sample of every golden no-fix line.

NOT part of the decoder, and nothing under src/decoder/ may read its output.

Input: data/modes1_prefix_nofix.txt from `scripts/dump1090_prefix_search.sh nofix all` (run in
WSL), which gives a start estimate per line from the shortest prefix after which dump1090 outputs
it. The estimate can be early: zero-signal padding still reads correctly as trailing "1" bits, so
dump1090 can output a frame a few samples before all of it is present.

Each estimate is refined by searching starts from estimate-8 to estimate+32 for the one where a
plain half-versus-half comparison of every bit (the Riddle's PPM rule) disagrees least with the
golden hex. Flags:
  exact        the comparison reproduces every golden bit at that start
  approximate  no start in the window reproduces every bit; the closest one is stored, with the
               bits that disagree (dump1090 decoded these with rules beyond plain comparison)

Run:  python scripts/make_start_fixture.py
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
PREFIX_FILE = REPO / "data" / "modes1_prefix_nofix.txt"
RECORDING = REPO / "data" / "modes1.bin"
OUT = REPO / "tests" / "golden" / "modes1_starts.txt"
SEARCH = range(-8, 33)


def magnitudes(path: Path) -> np.ndarray:
    raw = np.fromfile(path, dtype=np.uint8).astype(np.int32) - 127
    return np.sqrt(raw[0::2] ** 2 + raw[1::2] ** 2)


def disagreeing_bits(mag: np.ndarray, start: int, msg_hex: str) -> list[int]:
    n = len(msg_hex) * 4
    want = np.array([c == "1" for c in bin(int(msg_hex, 16))[2:].zfill(n)])
    got = mag[start + 16 : start + 16 + 2 * n : 2] > mag[start + 17 : start + 17 + 2 * n : 2]
    return np.nonzero(got != want)[0].tolist()


def main() -> None:
    mag = magnitudes(RECORDING)
    rows = ["# line\tstart\tflag\tdisagreeing_bits\thex   (see scripts/make_start_fixture.py)"]
    exact = 0
    for text in PREFIX_FILE.read_text().splitlines():
        line = int(re.search(r"line=(\d+)", text).group(1))
        estimate = int(re.search(r"start_estimate=(\d+)", text).group(1))
        msg_hex = re.search(r"\*([0-9a-f]+);", text).group(1)
        candidates = [(disagreeing_bits(mag, estimate + d, msg_hex), estimate + d) for d in SEARCH]
        bits, start = min(candidates, key=lambda c: (len(c[0]), abs(c[1] - estimate)))
        flag = "exact" if not bits else "approximate"
        exact += flag == "exact"
        rows.append(f"{line}\t{start}\t{flag}\t{','.join(map(str, bits)) or '-'}\t{msg_hex}")
    OUT.write_text("\n".join(rows) + "\n", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)}: {len(rows) - 1} lines, {exact} exact")


if __name__ == "__main__":
    main()
