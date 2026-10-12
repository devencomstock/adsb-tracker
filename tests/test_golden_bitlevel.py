"""Checkpoint A: the bit-level stages must match the golden hex 100% (decision #8, level 1).

The golden lines are fed in file order. Without sample positions (those arrive at checkpoint B)
every line is given recording time 0.0. modes1.bin lasts 0.178 s, so no recently-seen entry
could expire anyway (decision #7).
"""

from __future__ import annotations

import re
from collections import Counter

from conftest import read_decoded_blocks

from decoder.accept import How, accept
from decoder.frame import Frame
from decoder.recent import RecentlySeen
from decoder.routing import route, type_code


class NeverSeen(RecentlySeen):
    """A recently-seen list with nothing in it, to show which messages depend on the list."""

    def seen(self, icao: int, t: float) -> bool:
        return False


def replay(lines: list[str], fix: bool, recent: RecentlySeen | None = None) -> list:
    recent = RecentlySeen() if recent is None else recent
    return [accept(Frame.from_hex(h), recent, 0.0, fix) for h in lines]


def test_every_nofix_line_is_accepted_without_fix(nofix_lines: list[str]) -> None:
    results = replay(nofix_lines, fix=False)
    assert all(r is not None for r in results)
    assert [r.frame.hex for r in results] == nofix_lines
    hows = Counter((r.frame.df, r.how) for r in results)
    assert hows == {
        (17, How.CLEAN): 120,
        (11, How.CLEAN): 43,
        (11, How.INTERROGATOR_ID): 20,
        (0, How.ADDRESS_PARITY): 10,
        (5, How.ADDRESS_PARITY): 8,
        (20, How.ADDRESS_PARITY): 8,
        (21, How.ADDRESS_PARITY): 5,
        (4, How.ADDRESS_PARITY): 3,
    }
    assert all(r.icao == 0x4D2023 for r in results)


def test_interrogator_ids_are_18_sixties_and_2_ones(nofix_lines: list[str]) -> None:
    ids = Counter(
        r.interrogator_id for r in replay(nofix_lines, False) if r.how is How.INTERROGATOR_ID
    )
    assert ids == {60: 18, 1: 2}


def test_without_the_list_exactly_54_messages_are_rejected(nofix_lines: list[str]) -> None:
    results = replay(nofix_lines, fix=False, recent=NeverSeen())
    assert sum(r is None for r in results) == 54
    assert all(r.how is How.CLEAN for r in results if r is not None)


def test_nofix_lines_plus_repair_equal_the_default_file(
    nofix_lines: list[str], default_lines: list[str]
) -> None:
    results = replay(nofix_lines, fix=True)
    assert [r.frame.hex for r in results] == default_lines
    repaired = {i: r.repaired_bit for i, r in enumerate(results) if r.how is How.REPAIRED}
    assert repaired == {128: 55, 174: 55}


def test_default_lines_are_all_accepted(default_lines: list[str]) -> None:
    results = replay(default_lines, fix=True)
    assert [r.frame.hex for r in results] == default_lines


def test_lengths_follow_the_frame_length_rule(nofix_lines: list[str]) -> None:
    lengths = Counter((Frame.from_hex(h).df, len(h) * 4) for h in nofix_lines)
    assert lengths == {
        (17, 112): 120,
        (11, 56): 63,
        (0, 56): 10,
        (5, 56): 8,
        (20, 112): 8,
        (21, 112): 5,
        (4, 56): 3,
    }


def test_routing_counts(nofix_lines: list[str]) -> None:
    frames = [Frame.from_hex(h) for h in nofix_lines]
    assert Counter(type_code(f) for f in frames if f.df == 17) == {11: 59, 19: 54, 4: 7}
    assert Counter(route(f).value for f in frames) == {
        "airborne position (baro altitude)": 59,
        "airborne velocity": 54,
        "identification": 7,
        "all-call reply": 63,
        "short air-air surveillance": 10,
        "identity reply": 13,
        "altitude reply": 11,
    }


def test_df_and_type_code_match_the_decoded_golden_file(nofix_lines: list[str]) -> None:
    blocks = read_decoded_blocks("nofix")
    assert len(blocks) == len(nofix_lines)
    for hex_line, block in zip(nofix_lines, blocks, strict=True):
        frame = Frame.from_hex(hex_line)
        assert f"*{hex_line};" in block
        assert re.search(rf"^DF {frame.df}:", block, re.MULTILINE)
        if frame.df == 17:
            tc = re.search(r"Extended Squitter\s+Type: (\d+)", block)
            assert tc is not None and int(tc.group(1)) == type_code(frame)
