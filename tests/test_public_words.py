"""The SDK's published text names no exposure calculation by number and no "v2".

Exposure has one calculation, the assumed dealer book, so nothing a caller reads (the README,
the CHANGELOG, MAINTAINING.md, every module's docstrings and the generated models' names and
descriptions) numbers it or carries a v2 name. The retired ``methodology`` parameter may be
named, as the CHANGELOG's removal does.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = {
    "a v2 word": re.compile(r"\b[vV]2\b"),
    "a v2 name": re.compile(r"[A-Za-z_]V2|\bV2[A-Za-z_]|[a-z_]v2\b"),
    "a method number": re.compile(r"[Mm]ethodolog(?:y|ies)[ _-]?[0-9]"),
    "a method value": re.compile(r"""["']?methodology["']?\s*[:=]\s*[0-9]"""),
}


def _published() -> list[Path]:
    files = [ROOT / name for name in ("README.md", "CHANGELOG.md", "MAINTAINING.md")]
    files += sorted((ROOT / "src" / "oas").rglob("*.py"))
    return files


def test_published_text_has_no_method_number_or_v2_name() -> None:
    found = []
    for path in _published():
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for what, pattern in FORBIDDEN.items():
                if pattern.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{lineno}: {what}: {line.strip()}")
    assert found == []


def test_the_sweep_reads_every_file_it_names() -> None:
    files = _published()
    assert all(path.is_file() for path in files)
    assert ROOT / "src" / "oas" / "_generated" / "models.py" in files
    assert ROOT / "src" / "oas" / "client.py" in files
    for what, sample in (
        ("a v2 word", "return Pydantic v2 models"),
        ("a v2 name", "snap.exposureV2"),
        ("a v2 name", "ExposureV2Stored"),
        ("a method number", "an available methodology-2 book"),
        ("a method value", '"methodology": 2'),
    ):
        assert FORBIDDEN[what].search(sample), (what, sample)
    removal = "exposure(...) no longer takes `methodology`"
    assert not any(pattern.search(removal) for pattern in FORBIDDEN.values())
