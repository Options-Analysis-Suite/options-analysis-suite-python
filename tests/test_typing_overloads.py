"""The public methods' overloads type a caller's code, checked by mypy over a caller's snippet.

exposure_eod(): a literal ``typed=`` picks its precise return type, and a dynamic ``bool``
gets the union rather than an overload error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

mypy_api = pytest.importorskip("mypy.api")

CALLER = """
from typing import Any

from typing_extensions import assert_type

from oas import OASClient
from oas._generated.models import EodExposureResponse


def calls(client: OASClient, typed: bool) -> None:
    assert_type(client.exposure_eod("SPY"), dict[str, Any])
    assert_type(client.exposure_eod("SPY", typed=False), dict[str, Any])
    assert_type(client.exposure_eod("SPY", typed=True), EodExposureResponse)
    assert_type(client.exposure_eod("SPY", typed=typed), dict[str, Any] | EodExposureResponse)
"""


def test_exposure_eod_overloads_type_literal_and_dynamic_calls(tmp_path: Path) -> None:
    # its own config: pyproject's names the package's files, and mypy takes one target set. The
    # package ships no py.typed marker (pyproject.toml), so mypy reads this tree's source by path,
    # as pyright reads an unmarked package; the generated module's own annotations are not this
    # test's subject (pyproject excludes it)
    caller = tmp_path / "caller.py"
    caller.write_text(CALLER)
    config = tmp_path / "mypy.ini"
    config.write_text(f"[mypy]\nmypy_path = {Path(__file__).resolve().parents[1] / 'src'}\n")
    stdout, stderr, status = mypy_api.run(
        ["--config-file", str(config), "--strict", "--follow-imports=silent", "--no-error-summary",
         "--cache-dir", str(tmp_path / "cache"), str(caller)],
    )
    assert status == 0, stdout + stderr
