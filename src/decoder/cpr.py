"""Compact Position Reporting: turn CPR fields into latitude/longitude (Riddle, "Airborne
position"; docs/mode-s-primer.md section 5).

Pure functions only. Choosing which even and odd frames belong together (same aircraft, close
in time) is tracking state and belongs to Phase 5.
"""

from __future__ import annotations

import math

NZ = 15  # latitude zones between the equator and a pole
CPR_SCALE = 2**17  # CPR fields are 17-bit fractions of a zone


def nl(lat: float) -> int:
    """Number of longitude zones at this latitude: 59 at the equator, down to 1 near the poles."""
    a = abs(lat)
    if a == 0:
        return 59
    if a == 87:
        return 2
    if a > 87:
        return 1
    x = 1 - (1 - math.cos(math.pi / (2 * NZ))) / math.cos(math.radians(a)) ** 2
    return math.floor(2 * math.pi / math.acos(x))


def global_position(
    even: tuple[int, int], odd: tuple[int, int], latest_is_odd: bool
) -> tuple[float, float] | None:
    """(lat, lon) from one even and one odd frame's (lat_cpr, lon_cpr), using the newer frame.

    Returns None when the two latitudes fall in different longitude-zone counts: the pair
    straddles a zone boundary and a newer pair is needed.
    """
    lat_e, lon_e = even[0] / CPR_SCALE, even[1] / CPR_SCALE
    lat_o, lon_o = odd[0] / CPR_SCALE, odd[1] / CPR_SCALE
    j = math.floor(59 * lat_e - 60 * lat_o + 0.5)  # latitude zone index
    lat_even = 360 / 60 * (j % 60 + lat_e)
    lat_odd = 360 / 59 * (j % 59 + lat_o)
    lat_even -= 360 if lat_even >= 270 else 0  # southern hemisphere
    lat_odd -= 360 if lat_odd >= 270 else 0
    if nl(lat_even) != nl(lat_odd):
        return None
    lat = lat_odd if latest_is_odd else lat_even
    zones = nl(lat)
    m = math.floor(lon_e * (zones - 1) - lon_o * zones + 0.5)  # longitude zone index
    n = max(zones - (1 if latest_is_odd else 0), 1)
    lon = 360 / n * (m % n + (lon_o if latest_is_odd else lon_e))
    lon -= 360 if lon >= 180 else 0
    return lat, lon


def local_position(
    odd: bool, lat_cpr: int, lon_cpr: int, ref_lat: float, ref_lon: float
) -> tuple[float, float]:
    """(lat, lon) from one frame and a reference position within 180 NM of the aircraft."""
    lat_frac, lon_frac = lat_cpr / CPR_SCALE, lon_cpr / CPR_SCALE
    dlat = 360 / (4 * NZ - (1 if odd else 0))
    j = math.floor(ref_lat / dlat) + math.floor((ref_lat % dlat) / dlat - lat_frac + 0.5)
    lat = dlat * (j + lat_frac)
    dlon = 360 / max(nl(lat) - (1 if odd else 0), 1)
    m = math.floor(ref_lon / dlon) + math.floor((ref_lon % dlon) / dlon - lon_frac + 0.5)
    return lat, dlon * (m + lon_frac)
