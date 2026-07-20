"""Shared test fixtures for the OAS Python SDK."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# Pinned fixture committed to the repo. Refresh via:
#   curl -s https://data.optionsanalysissuite.com/openapi.json \
#     > tests/fixtures/openapi.snapshot.json
# (or set OAS_OPENAPI_PATH=- to skip the file lookup and fetch live).
SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "openapi.snapshot.json"
LIVE_OPENAPI_URL = "https://data.optionsanalysissuite.com/openapi.json"


@pytest.fixture(scope="session")
def openapi_spec() -> dict[str, Any]:
    """Loads the OpenAPI spec for drift tests.

    Lookup order:
    1. ``OAS_OPENAPI_PATH`` env var (override — file path or ``-`` for live)
    2. ``tests/fixtures/openapi.snapshot.json`` (default — offline, committed)
    3. live fetch of the deployed prod spec (only if (1) is ``-`` or (2) missing)

    The default path is offline so ``make test`` works without network. The
    live integration suite (``make test-live``) is what gates against drift
    between the pinned fixture and prod.
    """
    override = os.environ.get("OAS_OPENAPI_PATH")
    if override and override != "-":
        return json.loads(Path(override).read_text())
    if override != "-" and SNAPSHOT_PATH.is_file():
        return json.loads(SNAPSHOT_PATH.read_text())
    import urllib.request
    with urllib.request.urlopen(LIVE_OPENAPI_URL) as r:
        return json.loads(r.read())


@pytest.fixture(scope="session")
def api_key() -> str:
    """Live API key from env. Skip when unavailable."""
    key = os.environ.get("OAS_API_KEY")
    if not key:
        pytest.skip("OAS_API_KEY not set; skipping live integration test")
    return key
