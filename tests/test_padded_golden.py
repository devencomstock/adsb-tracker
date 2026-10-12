"""The supplementary padded golden files must extend the approved ones (decision #13)."""

import re

import pytest
from conftest import GOLDEN, read_raw


def read_padded(mode: str) -> list[str]:
    return re.findall(r"\*([0-9a-f]+);", (GOLDEN / f"modes1_padded_raw_{mode}.txt").read_text())


@pytest.mark.parametrize(("mode", "tail"), [("nofix", 66), ("default", 67)])
def test_padded_file_starts_with_the_approved_file(mode: str, tail: int) -> None:
    approved = read_raw(mode)
    padded = read_padded(mode)
    assert padded[: len(approved)] == approved
    assert len(padded) - len(approved) == tail
