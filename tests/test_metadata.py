"""Package metadata consistency tests."""

from __future__ import annotations

from pathlib import Path

import oas


def _project_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    for line in pyproject.read_text().splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError("project.version missing from pyproject.toml")


def test_exported_version_matches_package_metadata() -> None:
    """Keep `oas.__version__` aligned with pyproject.toml."""
    assert oas.__version__ == _project_version()
