"""Output fields on the Riddle's worked examples (docs/mode-s-primer.md), cross-checked with
pyModeS in tests only."""

import pyModeS
import pytest

from decoder.fields import (
    ac12_altitude_ft,
    ac13_altitude_ft,
    adsb_fields,
    airborne_position,
    identification,
    squawk,
    velocity,
)
from decoder.frame import Frame

ID_MSG = "8D4840D6202CC371C32CE0576098"
POS_EVEN = "8D40621D58C382D690C8AC2863A7"
POS_ODD = "8D40621D58C386435CC412692AD6"
VEL_GROUND = "8D485020994409940838175B284F"  # subtype 1
VEL_AIR = "8DA05F219B06B6AF189400CBC33F"  # subtype 3


def test_identification_book_example() -> None:
    ident = identification(Frame.from_hex(ID_MSG))
    assert (ident.category, ident.callsign) == (0, "KLM1023")
    assert ident.callsign == pyModeS.decode(ID_MSG)["callsign"]


@pytest.mark.parametrize(
    ("msg", "odd", "lat_cpr", "lon_cpr"),
    [
        (POS_EVEN, False, 93000, 51372),
        (POS_ODD, True, 74158, 50194),
    ],
)
def test_airborne_position_book_example(msg: str, odd: bool, lat_cpr: int, lon_cpr: int) -> None:
    pos = airborne_position(Frame.from_hex(msg))
    assert (pos.altitude_ft, pos.odd, pos.lat_cpr, pos.lon_cpr) == (38000, odd, lat_cpr, lon_cpr)
    ref = pyModeS.decode(msg)
    assert (pos.altitude_ft, int(pos.odd), pos.lat_cpr, pos.lon_cpr) == (
        ref["altitude"],
        ref["cpr_format"],
        ref["cpr_lat"],
        ref["cpr_lon"],
    )


def test_ac12_altitude_needs_the_q_bit() -> None:
    assert ac12_altitude_ft(0b110000111000) == 38000
    assert ac12_altitude_ft(0) is None
    assert ac12_altitude_ft(0b110000101000) is None  # Q = 0: Gillham, not decoded


def test_ground_speed_velocity_book_example() -> None:
    v = velocity(Frame.from_hex(VEL_GROUND))
    assert v.subtype == 1
    assert v.speed_kt == pytest.approx(159.20, abs=0.01)
    assert v.track_deg == pytest.approx(182.88, abs=0.01)
    assert (v.vertical_rate_fpm, v.vertical_rate_source, v.geo_minus_baro_ft) == (-832, "GNSS", 550)
    ref = pyModeS.decode(VEL_GROUND)
    assert abs(v.speed_kt - ref["groundspeed"]) < 1
    assert v.track_deg == pytest.approx(ref["track"])
    assert v.vertical_rate_fpm == ref["vertical_rate"]


def test_airspeed_velocity_book_example() -> None:
    v = velocity(Frame.from_hex(VEL_AIR))
    assert (v.subtype, v.speed_kt, v.airspeed_type) == (3, 375, "TAS")
    assert v.heading_deg == pytest.approx(243.984375)
    assert (v.vertical_rate_fpm, v.vertical_rate_source, v.geo_minus_baro_ft) == (
        -2304,
        "BARO",
        None,
    )
    ref = pyModeS.decode(VEL_AIR)
    assert (v.speed_kt, v.heading_deg) == (ref["airspeed"], pytest.approx(ref["heading"]))


def test_ac13_altitude_and_squawk() -> None:
    assert ac13_altitude_ft(Frame.from_hex("20000f1f684a6c")) == 23375  # golden DF 4
    assert squawk(Frame.from_hex("2A00516D492B80")) == "0356"  # Riddle, "Surveillance reply"
    assert squawk(Frame.from_hex("280010248c796b")) == "0112"  # golden DF 5


def test_adsb_fields_dispatches_by_type_code() -> None:
    assert adsb_fields(Frame.from_hex(ID_MSG)) == identification(Frame.from_hex(ID_MSG))
    assert adsb_fields(Frame.from_hex(POS_EVEN)) == airborne_position(Frame.from_hex(POS_EVEN))
    assert adsb_fields(Frame.from_hex(VEL_AIR)) == velocity(Frame.from_hex(VEL_AIR))
