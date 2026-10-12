"""Output fields of single messages (docs/pseudocode.md stage 6).

Bit positions below are 0-based message bits (the Riddle numbers bits from 1). For ADS-B the
56-bit ME field is message bits 32-87, so ME bit n (Riddle numbering) is message bit 31 + n.
Sources: Riddle chapters "Aircraft identification", "Airborne position", "Airborne velocity" and
"Surveillance reply" (docs/mode-s-primer.md sections 3, 5 and 6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from decoder.frame import Frame
from decoder.routing import type_code

ME = 32  # first message bit of the ADS-B ME field
CHARSET = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######"


@dataclass(frozen=True)
class Identification:
    category: int
    callsign: str


@dataclass(frozen=True)
class AirbornePosition:
    altitude_ft: int | None
    time_flag: int
    odd: bool  # the CPR format flag F: True for an odd frame
    lat_cpr: int  # 17-bit CPR latitude; a position needs a pair or a reference (decoder.cpr)
    lon_cpr: int


@dataclass(frozen=True)
class Velocity:
    subtype: int
    raw: dict[str, int]  # the fields as transmitted, before scaling
    speed_kt: float | None  # ground speed (subtypes 1, 2) or airspeed (3, 4)
    track_deg: float | None  # ground track (subtypes 1, 2)
    heading_deg: float | None  # magnetic heading (subtypes 3, 4)
    airspeed_type: str | None  # "IAS" or "TAS" (subtypes 3, 4)
    vertical_rate_fpm: int | None
    vertical_rate_source: str  # "GNSS" or "BARO"
    geo_minus_baro_ft: int | None


def identification(frame: Frame) -> Identification:
    """TC 1-4: category (3 bits) and 8 six-bit characters (Riddle, "Aircraft identification")."""
    chars = (CHARSET[frame.field(ME + 8 + 6 * k, 6)] for k in range(8))
    return Identification(frame.field(ME + 5, 3), "".join(chars).rstrip())


def ac12_altitude_ft(code: int) -> int | None:
    """12-bit ADS-B altitude: with the Q bit (its 8th bit) set, 25 ft steps from -1000 ft.
    Q = 0 (Gillham, 100 ft steps) is not needed for this recording and returns None."""
    if code == 0 or not (code >> 4) & 1:
        return None
    n = ((code >> 5) << 4) | (code & 0xF)  # drop the Q bit
    return 25 * n - 1000


def airborne_position(frame: Frame) -> AirbornePosition:
    """TC 9-18: altitude, time flag, CPR format and the raw CPR latitude/longitude."""
    return AirbornePosition(
        altitude_ft=ac12_altitude_ft(frame.field(ME + 8, 12)),
        time_flag=frame.field(ME + 20, 1),
        odd=bool(frame.field(ME + 21, 1)),
        lat_cpr=frame.field(ME + 22, 17),
        lon_cpr=frame.field(ME + 39, 17),
    )


def velocity(frame: Frame) -> Velocity:
    """TC 19 (Riddle, "Airborne velocity"; primer section 6)."""
    subtype = frame.field(ME + 5, 3)
    scale = 4 if subtype in (2, 4) else 1  # supersonic subtypes use 4 kt steps
    raw = {
        "flag_a": frame.field(ME + 13, 1),  # E-W sign, or heading status
        "value_a": frame.field(ME + 14, 10),  # E-W speed, or heading
        "flag_b": frame.field(ME + 24, 1),  # N-S sign, or airspeed type
        "value_b": frame.field(ME + 25, 10),  # N-S speed, or airspeed
        "vr_source": frame.field(ME + 35, 1),
        "vr_sign": frame.field(ME + 36, 1),
        "vr": frame.field(ME + 37, 9),
        "geo_sign": frame.field(ME + 48, 1),
        "geo": frame.field(ME + 49, 7),
    }
    speed = track = heading = None
    airspeed_type = None
    if subtype in (1, 2) and raw["value_a"] and raw["value_b"]:
        vx = (-1 if raw["flag_a"] else 1) * scale * (raw["value_a"] - 1)  # + east
        vy = (-1 if raw["flag_b"] else 1) * scale * (raw["value_b"] - 1)  # + north
        speed = math.hypot(vx, vy)
        track = math.degrees(math.atan2(vx, vy)) % 360
    elif subtype in (3, 4):
        heading = raw["value_a"] * 360 / 1024 if raw["flag_a"] else None
        speed = scale * (raw["value_b"] - 1) if raw["value_b"] else None
        airspeed_type = "TAS" if raw["flag_b"] else "IAS"
    vr = None if raw["vr"] == 0 else (-1 if raw["vr_sign"] else 1) * 64 * (raw["vr"] - 1)
    geo = None if raw["geo"] == 0 else (-1 if raw["geo_sign"] else 1) * 25 * (raw["geo"] - 1)
    return Velocity(
        subtype=subtype,
        raw=raw,
        speed_kt=speed,
        track_deg=track,
        heading_deg=heading,
        airspeed_type=airspeed_type,
        vertical_rate_fpm=vr,
        vertical_rate_source="BARO" if raw["vr_source"] else "GNSS",
        geo_minus_baro_ft=geo,
    )


def ac13_altitude_ft(frame: Frame) -> int | None:
    """13-bit altitude code, message bits 19-31 (Riddle bits 20-32, "Surveillance reply").

    The M bit is the field's 7th bit and the Q bit its 9th. M = 0 and Q = 1: drop both, the
    other 11 bits N give 25 x N - 1000 ft. Metric (M = 1) and Gillham (Q = 0) aren't needed for
    this recording and return None. dump1090 decodes DF 0/4/16/20 with this same field
    (dump1090.c 1211-1214 at efe64db); the golden decoded file confirms the values.
    """
    code = frame.field(19, 13)
    m_bit, q_bit = (code >> 6) & 1, (code >> 4) & 1
    if code == 0 or m_bit or not q_bit:
        return None
    n = ((code >> 7) << 5) | (((code >> 5) & 1) << 4) | (code & 0xF)  # drop M and Q
    return 25 * n - 1000


def squawk(frame: Frame) -> str:
    """4-digit octal identity code from message bits 19-31, laid out as
    C1 A1 C2 A2 C4 A4 X B1 D1 B2 D2 B4 D4 (Riddle, "Surveillance reply")."""
    code = frame.field(19, 13)
    layout = ["C1", "A1", "C2", "A2", "C4", "A4", "X", "B1", "D1", "B2", "D2", "B4", "D4"]
    bit = {name: (code >> (12 - i)) & 1 for i, name in enumerate(layout)}

    def digit(letter: str) -> int:
        return 4 * bit[f"{letter}4"] + 2 * bit[f"{letter}2"] + bit[f"{letter}1"]

    return "".join(str(digit(letter)) for letter in "ABCD")


def adsb_fields(frame: Frame) -> Identification | AirbornePosition | Velocity | None:
    """The fields of an ADS-B message (DF 17/18), by type code; None for kinds not decoded yet."""
    tc = type_code(frame)
    if 1 <= tc <= 4:
        return identification(frame)
    if 9 <= tc <= 18:
        return airborne_position(frame)
    if tc == 19:
        return velocity(frame)
    return None
