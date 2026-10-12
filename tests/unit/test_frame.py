from decoder.frame import Frame, frame_length


def test_from_hex_accepts_dump1090_raw_form() -> None:
    frame = Frame.from_hex("*8f4d2023587f345e35837e2218b2;")
    assert frame.n_bits == 112 and frame.hex == "8f4d2023587f345e35837e2218b2"


def test_fields_of_the_first_golden_message() -> None:
    frame = Frame.from_hex("8f4d2023587f345e35837e2218b2")
    assert frame.df == 17
    assert frame.field(5, 3) == 7  # CA
    assert frame.field(8, 24) == 0x4D2023  # ICAO
    assert frame.field(88, 24) == 0x2218B2  # parity


def test_frame_length_follows_dump1090() -> None:
    assert [df for df in range(32) if frame_length(df) == 112] == [16, 17, 18, 19, 20, 21]


def test_flip_inverts_one_bit() -> None:
    frame = Frame.from_hex("5d4d20237a55a7")
    assert frame.flip(55).hex == "5d4d20237a55a6"
    assert frame.flip(0).df == 11 ^ 0b10000
