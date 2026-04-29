"""Verify the pinned ``tests/fixtures/openapi.snapshot.json`` matches the
deployed spec's operationId set.

Marked ``live`` so it only runs when ``make test-live`` opts in. If this
fails, the data-api spec has drifted from the pinned fixture — refresh via:

    curl -s https://data.optionsanalysissuite.com/openapi.json \\
      > tests/fixtures/openapi.snapshot.json
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

LIVE_URL = "https://data.optionsanalysissuite.com/openapi.json"
SNAPSHOT = Path(__file__).parent / "fixtures" / "openapi.snapshot.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def _ops(spec: dict) -> set[str]:
    out: set[str] = set()
    for methods in spec.get("paths", {}).values():
        for method, op in methods.items():
            if method.lower() not in HTTP_METHODS:
                continue
            opid = op.get("operationId") if isinstance(op, dict) else None
            if opid:
                out.add(opid)
    return out


@pytest.mark.live
def test_pinned_fixture_matches_live_spec() -> None:
    pinned = _ops(json.loads(SNAPSHOT.read_text()))
    with urllib.request.urlopen(LIVE_URL) as r:
        live = _ops(json.loads(r.read()))
    drifted_in_live = live - pinned
    drifted_in_pinned = pinned - live
    assert not drifted_in_live, (
        f"Live spec has new operationIds not in the pinned fixture: "
        f"{sorted(drifted_in_live)} — refresh tests/fixtures/openapi.snapshot.json"
    )
    assert not drifted_in_pinned, (
        f"Pinned fixture has operationIds the live spec no longer serves: "
        f"{sorted(drifted_in_pinned)} — refresh tests/fixtures/openapi.snapshot.json"
    )
