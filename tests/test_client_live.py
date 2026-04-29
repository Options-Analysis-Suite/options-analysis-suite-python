"""Integration tests against the deployed data-api.

Skipped unless ``OAS_API_KEY`` is set in the environment. Marked ``live``
so unit-test runs (`make test`) can exclude them.
"""

from __future__ import annotations

import pytest

from oas import OASClient
from oas._generated.models import MaxPainCurveRow, ScenarioMatrixEntry

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


def test_scenario_against_live_api(api_key: str) -> None:
    with OASClient(api_key=api_key) as client:
        scenario = client.scenario(
            is_call=True,
            S=100.0,
            K=100.0,
            r=0.05,
            sigma=0.2,
            t=0.25,
            spot_changes=[-0.05, 0.0, 0.05],
            vol_changes=[-0.1, 0.0, 0.1],
        )

    assert scenario.spotChanges == [-0.05, 0.0, 0.05]
    assert scenario.volChanges == [-0.1, 0.0, 0.1]
    assert len(scenario.matrix) == 3
    assert len(scenario.matrix[0]) == 3
    cell = scenario.matrix[0][0]
    assert isinstance(cell, ScenarioMatrixEntry)
    assert cell.spotChange == -0.05
    assert cell.volChange == -0.1
    assert cell.spot == 95.0
    assert cell.volatility == pytest.approx(0.18)
    assert cell.price > 0
