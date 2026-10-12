"""Tag an accepted frame with what kind of message it is (docs/pseudocode.md stage 5).

DF first, then for ADS-B (DF 17/18) the type code: the first 5 bits of the ME field.
Type-code ranges: Riddle, "ADS-B basics" (docs/mode-s-primer.md section 2).
"""

from __future__ import annotations

from enum import StrEnum

from decoder.frame import Frame


class Kind(StrEnum):
    IDENTIFICATION = "identification"
    SURFACE_POSITION = "surface position"
    AIRBORNE_POSITION_BARO = "airborne position (baro altitude)"
    AIRBORNE_VELOCITY = "airborne velocity"
    AIRBORNE_POSITION_GNSS = "airborne position (GNSS height)"
    OTHER_ADSB = "other ADS-B"
    ALL_CALL_REPLY = "all-call reply"
    ALTITUDE_REPLY = "altitude reply"
    IDENTITY_REPLY = "identity reply"
    SHORT_AIR_AIR = "short air-air surveillance"
    UNHANDLED = "unhandled"


def type_code(frame: Frame) -> int:
    """ADS-B type code: message bits 32-36 (Riddle bits 33-37)."""
    return frame.field(32, 5)


def route(frame: Frame) -> Kind:
    if frame.df in (17, 18):
        return _route_adsb(type_code(frame))
    return {
        11: Kind.ALL_CALL_REPLY,
        4: Kind.ALTITUDE_REPLY,
        20: Kind.ALTITUDE_REPLY,
        5: Kind.IDENTITY_REPLY,
        21: Kind.IDENTITY_REPLY,
        0: Kind.SHORT_AIR_AIR,
    }.get(frame.df, Kind.UNHANDLED)


def _route_adsb(tc: int) -> Kind:
    if 1 <= tc <= 4:
        return Kind.IDENTIFICATION
    if 5 <= tc <= 8:
        return Kind.SURFACE_POSITION
    if 9 <= tc <= 18:
        return Kind.AIRBORNE_POSITION_BARO
    if tc == 19:
        return Kind.AIRBORNE_VELOCITY
    if 20 <= tc <= 22:
        return Kind.AIRBORNE_POSITION_GNSS
    return Kind.OTHER_ADSB
