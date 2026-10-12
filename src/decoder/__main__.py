"""Command line: python -m decoder --ifile data/modes1.bin [--no-fix]

Prints one raw line per message, like dump1090 --raw.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from decoder.pipeline import SIGNAL_FLOOR, decode_file, raw_line


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m decoder", description=__doc__.splitlines()[0])
    parser.add_argument("--ifile", type=Path, required=True, help="8-bit I/Q recording at 2 MHz")
    parser.add_argument("--no-fix", action="store_true", help="disable single-bit repair")
    parser.add_argument("--signal-floor", type=float, default=SIGNAL_FLOOR)
    args = parser.parse_args()
    for message in decode_file(args.ifile, fix=not args.no_fix, signal_floor=args.signal_floor):
        print(raw_line(message))


if __name__ == "__main__":
    main()
