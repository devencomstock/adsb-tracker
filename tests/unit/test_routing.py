from decoder.frame import Frame
from decoder.routing import Kind, route, type_code


def test_first_golden_message_is_airborne_position() -> None:
    frame = Frame.from_hex("8f4d2023587f345e35837e2218b2")
    assert type_code(frame) == 11
    assert route(frame) is Kind.AIRBORNE_POSITION_BARO


def test_type_code_ranges() -> None:
    def adsb_with_tc(tc: int) -> Frame:
        return Frame((17 << 107) | (tc << 75), 112)

    expected = {
        1: Kind.IDENTIFICATION,
        4: Kind.IDENTIFICATION,
        5: Kind.SURFACE_POSITION,
        9: Kind.AIRBORNE_POSITION_BARO,
        18: Kind.AIRBORNE_POSITION_BARO,
        19: Kind.AIRBORNE_VELOCITY,
        20: Kind.AIRBORNE_POSITION_GNSS,
        22: Kind.AIRBORNE_POSITION_GNSS,
        0: Kind.OTHER_ADSB,
        28: Kind.OTHER_ADSB,
    }
    for tc, kind in expected.items():
        assert type_code(adsb_with_tc(tc)) == tc
        assert route(adsb_with_tc(tc)) is kind


def test_mode_s_formats() -> None:
    assert route(Frame.from_hex("5d4d20237a55a6")) is Kind.ALL_CALL_REPLY
    assert route(Frame.from_hex("20000f1f684a6c")) is Kind.ALTITUDE_REPLY
