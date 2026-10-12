"""scripts/check_coverage.py: distance, altitude bands, snapshot parsing (synthetic data only)."""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_coverage.py"
_spec = importlib.util.spec_from_file_location("check_coverage", _SCRIPT)
assert _spec is not None and _spec.loader is not None
cov = importlib.util.module_from_spec(_spec)
sys.modules["check_coverage"] = cov
_spec.loader.exec_module(cov)


def test_klaf_reference_matches_faa_nfdc_dms() -> None:
    # FAA NFDC: 40-24-44.296 N / 86-56-12.831 W
    assert cov.KLAF_LAT == pytest.approx(40 + 24 / 60 + 44.296 / 3600, abs=1e-6)
    assert cov.KLAF_LON == pytest.approx(-(86 + 56 / 60 + 12.831 / 3600), abs=1e-6)


def test_distance_one_minute_of_latitude_is_one_nm() -> None:
    assert cov.distance_nm(cov.KLAF_LAT, cov.KLAF_LON) == 0
    assert cov.distance_nm(cov.KLAF_LAT + 1 / 60, cov.KLAF_LON) == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize(
    ("on_ground", "alt_ft", "expected"),
    [
        (True, None, "ground"),
        (False, 900, "very low (0-500 ft AGL)"),  # 294 ft AGL
        (False, 1606, "pattern (500-1,500)"),  # the AIM's 1,000 ft AGL pattern at KLAF
        (False, 4000, "low (1,500-5,000)"),  # 3,394 ft AGL
        (False, 5605, "low (1,500-5,000)"),  # 4,999 ft AGL: still low
        (False, 5606, "high (>5,000)"),  # 5,000 ft AGL: band edges go to the higher band
        (False, 31150, "high (>5,000)"),
        (False, None, "no altitude"),
    ],
)
def test_altitude_bands_are_relative_to_field_elevation(
    on_ground: bool, alt_ft: float | None, expected: str
) -> None:
    assert cov.band(on_ground, alt_ft) == expected


def test_adsblol_rows_filters_stale_far_and_positionless_aircraft() -> None:
    snapshot = {
        "now": 1_791_832_887_001,  # milliseconds, as adsb.lol actually sends it
        "ac": [
            {
                "hex": "a2eea2",
                "type": "adsb_icao",
                "lat": 40.4205,
                "lon": -86.9201,
                "alt_baro": 900,
                "seen_pos": 2.8,
            },
            {
                "hex": "aaaaaa",
                "type": "mlat",
                "lat": 40.41,
                "lon": -86.93,
                "alt_baro": "ground",
                "seen_pos": 5,
            },
            {
                "hex": "bbbbbb",
                "type": "adsb_icao",
                "lat": 40.41,
                "lon": -86.93,
                "alt_baro": 900,
                "seen_pos": 90,
            },  # stale
            {
                "hex": "cccccc",
                "type": "adsb_icao",
                "lat": 41.5,
                "lon": -86.93,
                "alt_baro": 900,
                "seen_pos": 1,
            },  # 65 NM away
            {"hex": "dddddd", "type": "mode_s", "alt_baro": 3000},  # no position
        ],
    }
    when, rows = cov.adsblol_rows(snapshot)
    assert when.year == 2026  # the millisecond timestamp was recognized
    assert [(r["hex"], r["kind"], r["band"]) for r in rows] == [
        ("a2eea2", "ADS-B", "very low (0-500 ft AGL)"),
        ("aaaaaa", "MLAT", "ground"),
    ]


def test_seconds_timestamp_is_also_accepted() -> None:
    when, _rows = cov.adsblol_rows({"now": 1_791_832_887.0, "ac": []})
    assert when.year == 2026
