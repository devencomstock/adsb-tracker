"""CPR position decoding on the Riddle's worked example (docs/mode-s-primer.md section 5),
cross-checked with pyModeS in tests only."""

import math

import pyModeS
import pytest

from decoder.cpr import global_position, local_position, nl
from decoder.fields import airborne_position
from decoder.frame import Frame

EVEN = airborne_position(Frame.from_hex("8D40621D58C382D690C8AC2863A7"))  # newer frame
ODD = airborne_position(Frame.from_hex("8D40621D58C386435CC412692AD6"))


def test_nl_edges_and_book_latitude() -> None:
    assert nl(0) == 59
    assert nl(87) == nl(-87) == 2
    assert nl(88) == nl(-88) == 1
    assert nl(52.2572021484375) == 36
    assert nl(40.43) == 45  # West Lafayette


def test_global_position_book_example() -> None:
    pos = global_position(
        (EVEN.lat_cpr, EVEN.lon_cpr), (ODD.lat_cpr, ODD.lon_cpr), latest_is_odd=False
    )
    assert pos is not None
    lat, lon = pos
    assert lat == pytest.approx(52.2572, abs=1e-4)
    assert lon == pytest.approx(3.9194, abs=1e-4)
    ref = pyModeS.decode(
        ["8D40621D58C382D690C8AC2863A7", "8D40621D58C386435CC412692AD6"],
        timestamps=[1457996402, 1457996400],
    )[0]
    assert (lat, lon) == (pytest.approx(ref["latitude"]), pytest.approx(ref["longitude"]))


def test_global_position_using_the_odd_frame_is_close() -> None:
    pos = global_position(
        (EVEN.lat_cpr, EVEN.lon_cpr), (ODD.lat_cpr, ODD.lon_cpr), latest_is_odd=True
    )
    assert pos is not None
    assert pos[0] == pytest.approx(52.2658, abs=1e-3)
    assert pos[1] == pytest.approx(3.9389, abs=1e-2)


def encode_lat(lat: float, odd: bool) -> int:
    """CPR-encode a latitude (the inverse of the decode; Riddle, "Airborne position")."""
    dlat = 360 / (59 if odd else 60)
    return math.floor(2**17 * (lat % dlat) / dlat + 0.5) % 2**17


def test_pair_straddling_a_zone_boundary_is_rejected() -> None:
    lat = 52.0
    while nl(lat + 0.001) == nl(lat):  # find where NL steps down (36 -> 35 near 52.5)
        lat += 0.001
    below, above = lat - 0.01, lat + 0.01
    assert nl(below) != nl(above)
    pair = ((encode_lat(below, odd=False), 0), (encode_lat(above, odd=True), 0))
    assert global_position(*pair, latest_is_odd=False) is None
    same_side = ((encode_lat(below, odd=False), 0), (encode_lat(below, odd=True), 0))
    assert global_position(*same_side, latest_is_odd=False) is not None


def test_local_position_book_example() -> None:
    lat, lon = local_position(EVEN.odd, EVEN.lat_cpr, EVEN.lon_cpr, 52.258, 3.918)
    assert lat == pytest.approx(52.2572021484375)
    assert lon == pytest.approx(3.91937255859375)
    ref = pyModeS.decode("8D40621D58C382D690C8AC2863A7", reference=(52.258, 3.918))
    assert (lat, lon) == (pytest.approx(ref["latitude"]), pytest.approx(ref["longitude"]))


def test_local_position_of_the_odd_frame_agrees_with_pymodes() -> None:
    lat, lon = local_position(ODD.odd, ODD.lat_cpr, ODD.lon_cpr, 52.258, 3.918)
    ref = pyModeS.decode("8D40621D58C386435CC412692AD6", reference=(52.258, 3.918))
    assert (lat, lon) == (pytest.approx(ref["latitude"]), pytest.approx(ref["longitude"]))
