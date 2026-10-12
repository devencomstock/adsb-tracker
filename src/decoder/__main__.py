"""Command line: python -m decoder --ifile data/modes1.bin [--no-fix] [--fields]

Prints one raw line per message, like dump1090 --raw; with --fields, also the decoded fields.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from decoder.fields import ac13_altitude_ft, adsb_fields, squawk
from decoder.pipeline import SIGNAL_FLOOR, Message, decode_file, raw_line
from decoder.routing import route


def describe(message: Message) -> str:
    """One line of decoded fields for a message."""
    frame = message.accepted.frame
    parts = [f"DF{frame.df}", f"icao={message.accepted.icao:06x}", route(frame).value]
    if frame.df in (17, 18):
        fields = adsb_fields(frame)
        if fields is not None:
            parts += [f"{k}={v}" for k, v in asdict(fields).items() if k != "raw"]
    elif frame.df in (0, 4, 20):
        parts.append(f"altitude_ft={ac13_altitude_ft(frame)}")
    elif frame.df in (5, 21):
        parts.append(f"squawk={squawk(frame)}")
    elif frame.df == 11 and message.accepted.interrogator_id:
        parts.append(f"interrogator_id={message.accepted.interrogator_id}")
    return " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m decoder", description=__doc__.splitlines()[0])
    parser.add_argument("--ifile", type=Path, required=True, help="8-bit I/Q recording at 2 MHz")
    parser.add_argument("--no-fix", action="store_true", help="disable single-bit repair")
    parser.add_argument("--fields", action="store_true", help="also print decoded fields")
    parser.add_argument("--signal-floor", type=float, default=SIGNAL_FLOOR)
    args = parser.parse_args()
    for message in decode_file(args.ifile, fix=not args.no_fix, signal_floor=args.signal_floor):
        print(raw_line(message) + (f"  {describe(message)}" if args.fields else ""))


if __name__ == "__main__":
    main()
