"""Rules from CLAUDE.md: pyModeS and the golden files are answer keys, never decoder inputs."""

import re
from pathlib import Path

DECODER = Path(__file__).resolve().parents[1] / "src" / "decoder"


def decoder_sources() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in DECODER.rglob("*.py")}


def test_decoder_sources_exist() -> None:
    assert decoder_sources()


def test_no_pymodes_anywhere_in_the_decoder() -> None:
    # Case-insensitive, so "import pyModeS", "from pyModeS ..." and "pymodes" are all caught.
    offenders = [
        p.name for p, text in decoder_sources().items() if re.search("pymodes", text, re.I)
    ]
    assert offenders == []


def test_decoder_never_reads_the_golden_files_or_fixtures() -> None:
    pattern = re.compile(r"tests[/\\]golden|modes1_raw|modes1_decoded|modes1_starts", re.I)
    offenders = [p.name for p, text in decoder_sources().items() if pattern.search(text)]
    assert offenders == []
