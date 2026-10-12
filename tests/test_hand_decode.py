"""Confirm the hand-decode in docs/decoder-notes.md against pyModeS (answer key only)."""

import pyModeS

MSG = "8D4840D6202CC371C32CE0576098"


def test_hand_decode_matches_pymodes() -> None:
    decoded = pyModeS.decode(MSG)

    assert decoded["df"] == 17
    assert decoded["icao"] == "4840D6"
    assert decoded["typecode"] == 4
    assert decoded["category"] == 0
    assert decoded["callsign"] == "KLM1023"
    assert decoded["crc_valid"] is True
