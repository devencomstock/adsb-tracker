"""Phase 1: check the hand-worked Mode S / ADS-B examples against pyModeS 3.x.

scripts/phase1_worked_examples.py re-derives each field from the raw bits using only
the standard library. These tests confirm it agrees with pyModeS and with the numbers
printed in The 1090 MHz Riddle (https://mode-s.org/1090mhz/). pyModeS is a validation
tool only; nothing under src/decoder/ may import it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pyModeS
import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "phase1_worked_examples.py"
_spec = importlib.util.spec_from_file_location("phase1_worked_examples", _SCRIPT)
assert _spec is not None and _spec.loader is not None
study = importlib.util.module_from_spec(_spec)
sys.modules["phase1_worked_examples"] = study
_spec.loader.exec_module(study)


def test_identification_matches_pymodes() -> None:
    f = study.frame_fields(study.ID_MSG)
    category, callsign = study.identification(f["me"])
    ref = pyModeS.decode(study.ID_MSG)
    assert (f["df"], f["icao"], f["tc"]) == (ref["df"], ref["icao"], ref["typecode"])
    assert category == ref["category"] == 0
    assert callsign == ref["callsign"] == "KLM1023"


def test_crc_values_from_the_book() -> None:
    bits = study.to_bits
    assert study.crc_remainder(bits(study.CRC_GOOD)) == 0
    assert study.adsb_parity(study.CRC_GOOD) == 0xAA4BDA
    assert study.crc_remainder(bits(study.CRC_BAD)) == 16
    assert study.crc_remainder(bits(study.ALLCALL)) == 22  # interrogator identifier


def test_crc_agrees_with_pymodes_validity_flag() -> None:
    for msg in (study.ID_MSG, study.POS_EVEN, study.POS_ODD, study.VEL_A, study.VEL_B):
        assert study.crc_remainder(study.to_bits(msg)) == 0
        assert pyModeS.decode(msg)["crc_valid"] is True
    assert pyModeS.decode(study.CRC_BAD)["crc_valid"] is False


def test_single_bit_repair_recovers_every_flipped_bit() -> None:
    original = study.CRC_GOOD
    bits = study.to_bits(original)
    for pos in range(112):
        flipped = bits[:pos] + ("1" if bits[pos] == "0" else "0") + bits[pos + 1 :]
        corrupted = f"{int(flipped, 2):028X}"
        assert study.fix_single_bit(corrupted) == original
    assert len(study.syndrome_table(112)) == 112  # every single-bit error is distinct


def test_single_bit_repair_of_the_book_bad_message_is_crc_valid() -> None:
    fixed = study.fix_single_bit(study.CRC_BAD)
    assert fixed is not None
    assert pyModeS.decode(fixed)["crc_valid"] is True


def test_altitude_and_cpr_fields_match_pymodes() -> None:
    for msg in (study.POS_EVEN, study.POS_ODD):
        me = study.frame_fields(msg)["me"]
        f, lat_cpr, lon_cpr = study.cpr_fields(me)
        ref = pyModeS.decode(msg)
        assert study.barometric_altitude_ft(me) == ref["altitude"] == 38000
        assert (f, lat_cpr, lon_cpr) == (
            ref["cpr_format"],
            ref["cpr_lat"],
            ref["cpr_lon"],
        )


def test_global_position_matches_book_and_pymodes() -> None:
    me_e = study.frame_fields(study.POS_EVEN)["me"]
    me_o = study.frame_fields(study.POS_ODD)["me"]
    _, lat_e, lon_e = study.cpr_fields(me_e)
    _, lat_o, lon_o = study.cpr_fields(me_o)
    steps = study.cpr_global((lat_e, lon_e), (lat_o, lon_o), latest="even")
    assert steps is not None
    assert steps["j"] == 8 and steps["nl"] == 36 and steps["m"] == 0
    assert steps["lat_even"] == pytest.approx(52.2572021484375)
    assert steps["lat_odd"] == pytest.approx(52.26578017412606)
    assert steps["lon"] == pytest.approx(3.91937255859375)

    # pyModeS pairs frames by timestamp; the even frame is the newer one here.
    ref = pyModeS.decode([study.POS_EVEN, study.POS_ODD], timestamps=[1457996402, 1457996400])
    assert steps["lat"] == pytest.approx(ref[0]["latitude"])
    assert steps["lon"] == pytest.approx(ref[0]["longitude"])


def test_local_position_matches_global_and_pymodes() -> None:
    me = study.frame_fields(study.POS_EVEN)["me"]
    f, lat_cpr, lon_cpr = study.cpr_fields(me)
    lat, lon = study.cpr_local(f, lat_cpr, lon_cpr, 52.258, 3.918)
    ref = pyModeS.decode(study.POS_EVEN, reference=(52.258, 3.918))
    assert lat == pytest.approx(ref["latitude"]) == pytest.approx(52.2572021484375)
    assert lon == pytest.approx(ref["longitude"]) == pytest.approx(3.91937255859375)


def test_nl_edge_cases() -> None:
    assert study.nl(0) == 59
    assert study.nl(87) == 2 and study.nl(-87) == 2
    assert study.nl(88) == 1 and study.nl(-88) == 1
    assert study.nl(52.25720214843750) == 36


def test_velocity_subtype_1_ground_speed() -> None:
    v = study.velocity(study.frame_fields(study.VEL_A)["me"])
    ref = pyModeS.decode(study.VEL_A)
    assert (v["vx"], v["vy"]) == (-8, -159)  # the book's printed (-9, -160) is a typo
    assert v["speed_kt"] == pytest.approx(159.20, abs=0.01)
    assert round(v["speed_kt"]) == ref["groundspeed"] == 159
    assert v["track_deg"] == pytest.approx(ref["track"]) == pytest.approx(182.88, abs=0.01)
    assert v["vertical_rate_fpm"] == ref["vertical_rate"] == -832
    assert v["vr_source"] == ref["vr_source"] == "GNSS"
    assert v["geo_minus_baro_ft"] == ref["geo_minus_baro"] == 550


def test_velocity_subtype_3_airspeed() -> None:
    v = study.velocity(study.frame_fields(study.VEL_B)["me"])
    ref = pyModeS.decode(study.VEL_B)
    assert v["airspeed_kt"] == ref["airspeed"] == 375
    assert v["heading_deg"] == pytest.approx(ref["heading"]) == pytest.approx(243.984375)
    assert v["airspeed_type"] == ref["airspeed_type"] == "TAS"
    assert v["vertical_rate_fpm"] == ref["vertical_rate"] == -2304
    assert v["vr_source"] == ref["vr_source"] == "BARO"
    assert v["geo_minus_baro_ft"] is None and ref["geo_minus_baro"] is None
