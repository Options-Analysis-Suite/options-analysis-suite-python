"""Mocked tests for a representative slice of OASClient methods.

We don't need 49 method-by-method tests — the wiring is mechanical and the
drift suite already proves coverage. These tests pin a few high-leverage
behaviors:
- iter_metrics chunks symbols correctly (regression risk for the batch API)
- exposure dispatches the oneOf union shape correctly
- price/greeks send camelCase JSON (the snake_case → camelCase rename
  is the one place a typo would silently break things)
- query-string params for ``from`` / ``to`` etc. send the renamed value
- path-param URL encoding actually fires for symbols with reserved chars
"""

from __future__ import annotations

import json
from typing import Any

import respx
from httpx import Response

from oas import OASClient


@respx.mock
def test_iter_metrics_chunks_symbols_at_batch_size() -> None:
    calls: list[str] = []

    def _handler(request):
        calls.append(request.url.params["symbols"])
        # Echo each symbol back as a minimal MetricsResponse row.
        symbols = request.url.params["symbols"].split(",")
        data = [{
            "symbol": s, "date": "2026-04-25",
            "atmIv": 0.15, "ivRank": 25.0, "ivPercentile": 30.0,
            "hv20d": None, "hv60d": None, "putCallRatio": 0.9,
            "totalVolume": 1000, "totalOi": 5000,
            "callVolume": 600, "putVolume": 400,
            "callOi": 3000, "putOi": 2000, "maxPain": 100, "expectedMovePct": 0.02,
        } for s in symbols]
        return Response(200, json={"count": len(data), "data": data})

    respx.get("https://data.optionsanalysissuite.com/v1/data/metrics/batch").mock(side_effect=_handler)

    syms = [f"S{i}" for i in range(7)]
    with OASClient(api_key="oas_test_xyz") as client:
        results = list(client.iter_metrics(syms, batch_size=3))

    assert len(results) == 7
    # 3 + 3 + 1 chunks
    assert calls == ["S0,S1,S2", "S3,S4,S5", "S6"]
    assert {r.symbol for r in results} == set(syms)


@respx.mock
def test_exposure_full_returns_oneof_full_result() -> None:
    """Default exposure response is the {snapshot, byStrike} union member."""
    fixture = {
        "snapshot": {
            "spotPrice": 650.0,
            "netGamma": 1000, "netDelta": -500, "netVega": 100,
            "netVanna": 10, "netCharm": -5, "netVomma": 8,
            "callWall": 660, "putWall": 640, "gammaFlip": 655,
            "gammaConcentration": 0.3, "regime": "positive",
            "topStrikes": [],
        },
        "byStrike": [],
    }
    respx.post("https://data.optionsanalysissuite.com/v1/compute/exposure").mock(
        return_value=Response(200, json=fixture)
    )

    with OASClient(api_key="oas_test_xyz") as client:
        result = client.exposure(strikes=[], spot_price=650.0)

    # ExposureResponse is RootModel[ExposureFullResult | ExposureSnapshot].
    assert hasattr(result, "root")
    assert hasattr(result.root, "snapshot")
    assert result.root.snapshot.spotPrice == 650.0


@respx.mock
def test_scenario_matrix_returns_typed_cells() -> None:
    """Scenario matrix cells are structured objects, not bare floats."""
    respx.post("https://data.optionsanalysissuite.com/v1/compute/scenario").mock(
        return_value=Response(200, json={
            "spotChanges": [-0.05, 0.0, 0.05],
            "volChanges": [-0.1, 0.0, 0.1],
            "matrix": [[{
                "spotChange": -0.05,
                "volChange": -0.1,
                "spot": 95.0,
                "volatility": 0.18,
                "price": 5.25,
                "pnl": -1.0,
                "pnlPercent": -16.0,
            }]],
        })
    )

    with OASClient(api_key="oas_test_xyz") as client:
        result = client.scenario(
            is_call=True,
            S=100.0,
            K=100.0,
            r=0.05,
            sigma=0.2,
            t=0.25,
            spot_changes=[-0.05, 0.0, 0.05],
            vol_changes=[-0.1, 0.0, 0.1],
        )

    assert result.matrix is not None
    cell = result.matrix[0][0]
    assert cell.spotChange == -0.05
    assert cell.volChange == -0.1
    assert cell.price == 5.25
    assert cell.pnlPercent == -16.0


@respx.mock
def test_price_sends_snake_case_kwargs_as_camelcase_json() -> None:
    """The single most likely place for a typo bug is the snake→camel mapping."""
    captured: dict[str, Any] = {}

    def _handler(request):
        nonlocal captured
        captured = json.loads(request.content)
        return Response(200, json={
            "price": 12.0, "model": "Black-Scholes-Merton",
            "inputs": captured,
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/price").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        client.price(
            model="bs", is_call=True, K=100, S=100, r=0.05, q=0.0,
            sigma=0.2, t=0.25, model_params={"foo": 1},
            calibration_id="cal_xyz", is_american=False, steps=200,
        )

    assert captured["isCall"] is True
    assert captured["K"] == 100
    assert captured["modelParams"] == {"foo": 1}
    assert captured["calibrationId"] == "cal_xyz"
    assert captured["isAmerican"] is False
    assert "is_call" not in captured
    assert "model_params" not in captured


@respx.mock
def test_greeks_sends_include_insight_as_camelcase() -> None:
    captured: dict[str, Any] = {}

    def _handler(request):
        nonlocal captured
        captured = json.loads(request.content)
        return Response(200, json={
            "model": "Heston", "price": 12.0,
            "inputs": {"isCall": True, "S": 100, "K": 100,
                       "r": 0.05, "q": 0, "sigma": 0.2, "t": 0.25},
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/greeks").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        client.greeks(
            model="barrier", is_call=True, K=100, S=100, r=0.05, q=0.0,
            sigma=0.2, t=0.25, include_insight=True,
        )

    assert captured["includeInsight"] is True


@respx.mock
def test_price_blocks_full_detail_unless_opted_in() -> None:
    route = respx.post("https://data.optionsanalysissuite.com/v1/compute/price").mock(
        return_value=Response(200, json={"price": 1.0, "model": "Monte Carlo", "inputs": {}})
    )

    with OASClient(api_key="oas_test_xyz") as client:
        with pytest.raises(ValueError, match='detail="full" is disabled by default'):
            client.price(model="mc", is_call=True, K=100, S=100, r=0.05, sigma=0.2, t=0.25, detail="full")

        client.price(
            model="mc",
            is_call=True,
            K=100,
            S=100,
            r=0.05,
            sigma=0.2,
            t=0.25,
            detail="full",
            allow_full_paths=True,
        )

    assert route.call_count == 1


@respx.mock
def test_calendar_renames_from_date_to_from() -> None:
    """from_date is a Python-side rename to avoid the `from` keyword conflict."""
    route = respx.get("https://data.optionsanalysissuite.com/v1/data/economic-calendar").mock(
        return_value=Response(200, json={"count": 0, "data": []})
    )

    with OASClient(api_key="oas_test_xyz") as client:
        client.economic_calendar(from_date="2026-04-01", to_date="2026-04-30")

    request = route.calls[0].request
    assert request.url.params["from"] == "2026-04-01"
    assert request.url.params["to"] == "2026-04-30"


@respx.mock
def test_market_trends_preserves_loose_top_level_metadata() -> None:
    """ListResponse-style endpoints return raw dict so server metadata
    (date, metric, direction, page, etc.) isn't silently dropped."""
    respx.get("https://data.optionsanalysissuite.com/v1/data/market-trends").mock(
        return_value=Response(200, json={
            "date": "2026-04-25",
            "metric": "iv_rank",
            "direction": "desc",
            "count": 2,
            "data": [
                {"symbol": "AAPL", "ivRank": 95.0},
                {"symbol": "TSLA", "ivRank": 92.0},
            ],
        })
    )

    with OASClient(api_key="oas_test_xyz") as client:
        result = client.market_trends(metric="iv_rank", direction="desc", limit=2)

    assert isinstance(result, dict)
    # Top-level metadata that ListResponse used to drop
    assert result["date"] == "2026-04-25"
    assert result["metric"] == "iv_rank"
    assert result["direction"] == "desc"
    assert result["count"] == 2
    assert result["data"][0]["symbol"] == "AAPL"


@respx.mock
def test_news_preserves_pagination_metadata() -> None:
    respx.get("https://data.optionsanalysissuite.com/v1/data/news/SPY").mock(
        return_value=Response(200, json={
            "symbol": "SPY", "page": 2, "limit": 25,
            "count": 25, "data": [],
        })
    )
    with OASClient(api_key="oas_test_xyz") as client:
        result = client.news("SPY", page=2, limit=25)
    assert result["symbol"] == "SPY"
    assert result["page"] == 2
    assert result["limit"] == 25


@respx.mock
def test_probability_simple_sends_typed_body_no_broker_required() -> None:
    captured: dict[str, Any] = {}

    def _handler(request):
        nonlocal captured
        captured = json.loads(request.content)
        return Response(200, json={
            "riskNeutral": {
                "pdf": [], "cdf": [],
                "stats": {"impliedMove": 0.05},
                "method": "essvi",
            },
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/probability").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        client.probability_simple(
            spot_price=650.0,
            strikes=[640, 645, 650, 655, 660],
            ivs=[0.18, 0.16, 0.15, 0.14, 0.16],
            time_to_expiry=0.25,
            risk_free_rate=0.05,
        )

    assert captured["mode"] == "simple"
    assert captured["spotPrice"] == 650.0
    assert captured["strikes"] == [640, 645, 650, 655, 660]
    assert captured["timeToExpiry"] == 0.25
    assert captured["riskFreeRate"] == 0.05


@respx.mock
def test_probability_full_requires_and_sends_broker_headers() -> None:
    from oas import TradierCredentials
    captured_headers: dict[str, str] = {}
    captured_body: dict[str, Any] = {}

    def _handler(request):
        nonlocal captured_headers, captured_body
        captured_headers = dict(request.headers)
        captured_body = json.loads(request.content)
        return Response(200, json={
            "riskNeutral": {"pdf": [], "cdf": [], "method": "essvi"},
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/probability").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        client.probability_full(
            "SPY", broker=TradierCredentials(token="ttok"),
            expiration="2026-06-19",
        )

    assert captured_body["mode"] == "full"
    assert captured_body["symbol"] == "SPY"
    assert captured_headers["x-broker-type"] == "tradier"
    assert captured_headers["x-tradier-key"] == "ttok"


@respx.mock
def test_blocks_by_dealer_url_encodes_mpid() -> None:
    """MPIDs like A/B-style codes need URL-safe path interpolation."""
    captured_url: list[str] = []

    def _handler(request):
        captured_url.append(str(request.url))
        return Response(200, json={"count": 0, "data": []})

    respx.get(url__regex=r".*/dealer/.*").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        client.market_structure_blocks_by_dealer("UBS/X", summary_type="2K")

    # quote(safe="") must encode the slash
    assert "/dealer/UBS%2FX" in captured_url[0]
    assert "summary_type=2K" in captured_url[0]
