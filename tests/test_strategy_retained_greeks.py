from __future__ import annotations

from pydantic import BaseModel

from oas._generated.models import StrategyLeg


def test_strategy_leg_exposes_typed_retained_estimates() -> None:
    leg = StrategyLeg.model_validate(
        {
            "type": "put",
            "side": "long",
            "quantity": 1,
            "greeks": {},
            "retainedGreeks": {"vomma": "earlier", "ultima": "earlier"},
        }
    )
    retained = getattr(leg, "retainedGreeks", None)
    assert isinstance(retained, BaseModel)
    assert retained.model_dump(mode="json", exclude_none=True) == {
        "vomma": "earlier",
        "ultima": "earlier",
    }


def test_strategy_leg_without_retained_estimates_remains_compatible() -> None:
    leg = StrategyLeg.model_validate(
        {"type": "stock", "side": "long", "quantity": 1, "greeks": {"delta": 1}}
    )
    assert leg.model_dump(mode="json", exclude_none=True) == {
        "type": "stock", "side": "long", "quantity": 1.0, "greeks": {"delta": 1.0}
    }
