"""Shared helpers for reading the dump1090 answer key in tests/golden/ (tests only)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "golden"


def read_raw(mode: str) -> list[str]:
    """Hex lines of modes1_raw_<mode>.txt, in file order."""
    return re.findall(r"\*([0-9a-f]+);", (GOLDEN / f"modes1_raw_{mode}.txt").read_text())


def read_decoded_blocks(mode: str) -> list[str]:
    """One text block per message of modes1_decoded_<mode>.txt, in file order."""
    text = (GOLDEN / f"modes1_decoded_{mode}.txt").read_text()
    return [block for block in text.split("\n\n") if block.lstrip().startswith("*")]


@pytest.fixture(scope="session")
def nofix_lines() -> list[str]:
    return read_raw("nofix")


@pytest.fixture(scope="session")
def default_lines() -> list[str]:
    return read_raw("default")


@pytest.fixture(scope="session")
def nofix_blocks() -> list[str]:
    return read_decoded_blocks("nofix")
