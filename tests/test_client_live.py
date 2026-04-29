"""Integration tests against the deployed data-api.

Skipped unless ``OAS_API_KEY`` is set in the environment. Marked ``live``
so unit-test runs (`make test`) can exclude them.
"""

from __future__ import annotations

import pytest

from oas import OASClient
from oas._generated.models import MaxPainCurveRow

pytestmark = pytest.mark.live


def test_snapshot_against_live_api(api_key: str) -> None:
    with OASClient(api_key=api_key) as client:
        snap = client.snapshot("SPY")
    assert snap.ticker == "SPY"
    # ATM IV may be null on a brand-new symbol but for SPY it's always present.
    assert snap.atmIv is not None and snap.atmIv > 0
    # Typed nested model: maxPainCurve rows are MaxPainCurveRow instances.
    if snap.maxPainCurve:
        assert isinstance(snap.maxPainCurve[0], MaxPainCurveRow)
        assert snap.maxPainCurve[0].strike > 0
