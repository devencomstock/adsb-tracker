"""Checkpoint C: output fields of every golden message against dump1090's decoded file, message by
message, and against pyModeS (tests only). Fields come from the golden hex, so this checks
stage 6 on its own (decision #8, level 1: 100% expected)."""

from __future__ import annotations

import re
from collections import Counter

import pyModeS
import pytest
from conftest import read_decoded_blocks, read_raw

from decoder.crc import crc_remainder
from decoder.fields import (
    AirbornePosition,
    Identification,
    Velocity,
    ac13_altitude_ft,
    adsb_fields,
    squawk,
)
from decoder.frame import Frame
from decoder.routing import type_code

ALTITUDE_FORMATS = (0, 4, 20)
SQUAWK_FORMATS = (5, 21)


def value(block: str, label: str) -> str:
    """The text after `label ... :` on its line in a dump1090 decoded block."""
    match = re.search(rf"^\s*{re.escape(label)}\s*:\s*(.*?)\s*$", block, re.MULTILINE)
    assert match is not None, (label, block)
    return match.group(1)


def icao_of(frame: Frame) -> int:
    return frame.field(8, 24) if frame.df in (11, 17, 18) else crc_remainder(frame)


@pytest.mark.parametrize("mode", ["nofix", "default"])
def test_fields_match_the_decoded_golden_file(mode: str) -> None:
    lines, blocks = read_raw(mode), read_decoded_blocks(mode)
    assert len(lines) == len(blocks) == 217
    checked: Counter[str] = Counter()
    for hex_line, block in zip(lines, blocks, strict=True):
        frame = Frame.from_hex(hex_line)
        assert int(value(block, "ICAO Address"), 16) == icao_of(frame), hex_line
        if frame.df == 17:
            assert int(value(block, "Capability").split()[0]) == frame.field(5, 3)
            assert int(value(block, "Extended Squitter  Type")) == type_code(frame)
            fields = adsb_fields(frame)
            if isinstance(fields, Identification):
                assert value(block, "Identification") == fields.callsign
                checked["identification"] += 1
            elif isinstance(fields, AirbornePosition):
                assert value(block, "Altitude") == f"{fields.altitude_ft} feet"
                assert value(block, "F flag") == ("odd" if fields.odd else "even")
                assert value(block, "T flag") == ("UTC" if fields.time_flag else "non-UTC")
                assert value(block, "Latitude") == f"{fields.lat_cpr} (not decoded)"
                assert value(block, "Longitude") == f"{fields.lon_cpr} (not decoded)"
                checked["airborne position"] += 1
            elif isinstance(fields, Velocity):
                assert int(value(block, "Extended Squitter  Sub")) == fields.subtype == 1
                raw = fields.raw
                assert int(value(block, "EW direction")) == raw["flag_a"]
                assert int(value(block, "EW velocity")) == raw["value_a"]
                assert int(value(block, "NS direction")) == raw["flag_b"]
                assert int(value(block, "NS velocity")) == raw["value_b"]
                assert int(value(block, "Vertical rate src")) == raw["vr_source"]
                assert int(value(block, "Vertical rate sign")) == raw["vr_sign"]
                assert int(value(block, "Vertical rate")) == raw["vr"]
                checked["velocity"] += 1
        elif frame.df in ALTITUDE_FORMATS:
            assert value(block, "Altitude") == f"{ac13_altitude_ft(frame)} feet"
            checked["altitude reply"] += 1
        elif frame.df in SQUAWK_FORMATS:
            assert int(value(block, "Squawk")) == int(squawk(frame))
            checked["squawk"] += 1
    assert checked == {
        "identification": 7,
        "airborne position": 59,
        "velocity": 54,
        "altitude reply": 21,
        "squawk": 13,
    }


@pytest.mark.parametrize("mode", ["nofix", "default"])
def test_fields_agree_with_pymodes(mode: str) -> None:
    for hex_line in read_raw(mode):
        frame = Frame.from_hex(hex_line)
        ref = pyModeS.decode(hex_line)
        if frame.df == 17:
            fields = adsb_fields(frame)
            if isinstance(fields, Identification):
                assert (fields.callsign, fields.category) == (ref["callsign"], ref["category"])
            elif isinstance(fields, AirbornePosition):
                assert (fields.altitude_ft, int(fields.odd), fields.lat_cpr, fields.lon_cpr) == (
                    ref["altitude"],
                    ref["cpr_format"],
                    ref["cpr_lat"],
                    ref["cpr_lon"],
                )
            elif isinstance(fields, Velocity):
                assert abs(fields.speed_kt - ref["groundspeed"]) < 1, hex_line
                assert fields.track_deg == pytest.approx(ref["track"])
                assert fields.vertical_rate_fpm == ref["vertical_rate"]
                assert fields.vertical_rate_source == ref["vr_source"]
                assert fields.geo_minus_baro_ft == ref["geo_minus_baro"]
        elif frame.df in ALTITUDE_FORMATS:
            assert ac13_altitude_ft(frame) == ref["altitude"]
        elif frame.df in SQUAWK_FORMATS:
            assert squawk(frame) == ref["squawk"]
