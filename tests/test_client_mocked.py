"""Unit tests for OASClient using respx to mock the underlying httpx transport.

These tests don't hit the network; they exercise:
- request shape (path, headers)
- response parsing into typed Pydantic models
- error mapping (status code → typed exception)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from oas import OASClient
from oas.errors import (
    AuthenticationError,
    CalibrationQuotaError,
    ConcurrencyLimitError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

SNAPSHOT_FIXTURE: dict[str, Any] = {
    "ticker": "SPY",
    "date": "2026-04-25",
    "spotPrice": 655.89,
    "maxPain": 650,
    "netGex": 12500000,
    "netDex": -8200000,
    "atmIv": 0.142,
    "atmIv7d": 0.158,
    "atmIv30d": 0.146,
    "atmIv90d": 0.151,
    "putCallRatio": 0.91,
    "ivSkew25d": -0.034,
    "dividendYield": 0.0125,
    "totalVolume": 4200000,
    "totalOi": 18500000,
    "callVolume": 2100000,
    "putVolume": 2100000,
    "callOi": 9800000,
    "putOi": 8700000,
    "expectedMovePct": 0.018,
    "ivRank": 22.4,
    "ivPercentile": 31.7,
    "hv20d": 0.121,
    "hv60d": 0.138,
    "maxPainCurve": [
        {"strike": 650, "callPain": 0, "putPain": 7600000000, "totalPain": 7600000000},
    ],
    "gexByStrike": None,
    "dexByStrike": None,
    "vannaByStrike": None,
    "charmByStrike": None,
    "vommaByStrike": None,
    "volSkew": None,
    "probabilityData": None,
    "chainData": None,
    "analyticsExpiry": None,
    "chainExpiry": None,
}


@respx.mock
def test_snapshot_parses_response_into_typed_model() -> None:
    fixture = dict(SNAPSHOT_FIXTURE)
    route = respx.get("https://data.optionsanalysissuite.com/v1/data/snapshot/SPY").mock(
        return_value=Response(200, json=fixture)
    )

    with OASClient(api_key="oas_test_xyz") as client:
        snap = client.snapshot("SPY")

    assert route.called
    assert snap.ticker == "SPY"
    assert snap.atmIv == 0.142
    # Typed nested model — not a raw dict
    assert snap.maxPainCurve is not None
    assert snap.maxPainCurve[0].strike == 650



def _book() -> dict[str, Any]:
    return {"gex": 1.0, "vegaExposure": 2.0, "vanna": 3.0, "charmFlow": 4.0, "vomma": 5.0}


def _side() -> dict[str, Any]:
    return {
        "gex": 1.0, "dex": -0.5, "vega": 2.0, "vanna": 3.0,
        "charmFixedRef": 4.0, "rollBasis": None, "vomma": 5.0,
    }


def _coverage() -> dict[str, Any]:
    metrics = ("gamma", "delta", "vega", "vanna", "charm", "vomma")
    return {m: {"included": 4, "total": 4, "status": "complete"} for m in metrics}


STORED_V2: dict[str, Any] = {
    "available": True,
    "methodology": 2,
    "rollModel": "log-forward-theil-sen-v1",
    "units": {
        m: "USD"
        for m in ("gex", "vegaExposure", "vanna", "charmFlow", "vomma", "putMinusCallDeltaBalance")
    },
    "source": "eod_options_chain",
    "asOf": "2026-10-22",
    "scope": {"expirations": "all"},
    "referenceKind": "spot",
    "charmTimeBasis": "calendar-day",
    "rollStatus": "notApplicable",
    "carry": None,
    "carryFit": None,
    "assumedDealerBook": _book(),
    "longOi": _book(),
    "putMinusCallDeltaBalance": -1.5,
    "bases": {"call": _side(), "put": _side()},
    "coverage": _coverage(),
    "expiryScope": "eod-session-1",
    "provenance": "nightly",
    "definition": "expiry-scoped",
    "expiryQualifier": None,
    "byStrike": [
        {
            "strike": 230, "assumedDealerBook": _book(), "longOi": _book(),
            "putMinusCallDeltaBalance": 0.5, "coverage": _coverage(),
        },
    ],
}


@respx.mock
def test_snapshot_exposure_v2_branches_on_available() -> None:
    """exposureV2 is a union: an available methodology-2 book, or why there is none.

    `available` is a Literal, so a plain truth test takes the right branch (a one-value Enum
    member of False was truthy); an answer without the field, cached
    before the deploy, still parses.
    """
    from oas._generated.models import ExposureV2Stored, ExposureV2Unavailable

    base = "https://data.optionsanalysissuite.com/v1/data/snapshot"
    unavailable = {"available": False, "reason": "publication run mismatch"}
    answers = {
        "SPY": {**SNAPSHOT_FIXTURE, "exposureV2": STORED_V2},
        "QQQ": {**SNAPSHOT_FIXTURE, "ticker": "QQQ", "exposureV2": unavailable},
        "IWM": {**SNAPSHOT_FIXTURE, "ticker": "IWM"},
    }
    for symbol, answer in answers.items():
        respx.get(f"{base}/{symbol}").mock(return_value=Response(200, json=answer))

    with OASClient(api_key="oas_test_xyz") as client:
        spy, qqq, iwm = (client.snapshot(symbol) for symbol in ("SPY", "QQQ", "IWM"))

    seen = []
    for snap in (spy, qqq):
        v2 = snap.exposureV2
        assert v2 is not None
        if v2.available:
            assert isinstance(v2, ExposureV2Stored)
            assert v2.byStrike is not None
            seen.append(("book", v2.assumedDealerBook.gex, v2.byStrike[0].strike))
        else:
            assert isinstance(v2, ExposureV2Unavailable)
            seen.append(("none", v2.reason.value))
    assert seen == [("book", 1.0, 230), ("none", "publication run mismatch")]
    assert spy.exposureV2 is not None and spy.exposureV2.available is True
    assert spy.exposureV2.methodology == 2
    assert qqq.exposureV2 is not None and qqq.exposureV2.available is False
    assert iwm.exposureV2 is None

@respx.mock
def test_snapshot_authenticates_with_bearer_token() -> None:
    captured: dict[str, str] = {}

    def _handler(request):
        captured["authorization"] = request.headers.get("Authorization", "")
        return Response(200, json={"ticker": "SPY", "date": "2026-04-25"} | {
            k: None for k in [
                "spotPrice", "maxPain", "netGex", "netDex", "atmIv",
                "atmIv7d", "atmIv30d", "atmIv90d", "putCallRatio", "ivSkew25d",
                "dividendYield", "totalVolume", "totalOi", "callVolume", "putVolume",
                "callOi", "putOi", "expectedMovePct", "ivRank", "ivPercentile",
                "hv20d", "hv60d",
                "maxPainCurve", "gexByStrike", "dexByStrike", "vannaByStrike",
                "charmByStrike", "vommaByStrike", "volSkew", "probabilityData",
                "chainData", "analyticsExpiry", "chainExpiry",
            ]
        })

    respx.get("https://data.optionsanalysissuite.com/v1/data/snapshot/SPY").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        client.snapshot("SPY")

    assert captured["authorization"] == "Bearer oas_test_xyz"


@respx.mock
def test_snapshot_raises_not_found_on_404() -> None:
    respx.get("https://data.optionsanalysissuite.com/v1/data/snapshot/UNKNOWNTICKER").mock(
        return_value=Response(404, json={"error": "symbol not found"})
    )
    with OASClient(api_key="oas_test_xyz") as client:
        with pytest.raises(NotFoundError) as ei:
            client.snapshot("UNKNOWNTICKER")
    assert ei.value.status == 404


@respx.mock
def test_snapshot_raises_authentication_error_on_401() -> None:
    respx.get("https://data.optionsanalysissuite.com/v1/data/snapshot/SPY").mock(
        return_value=Response(401, json={"error": "missing or invalid api key"})
    )
    with OASClient(api_key="bogus") as client:
        with pytest.raises(AuthenticationError):
            client.snapshot("SPY")


@respx.mock
def test_snapshot_raises_rate_limit_with_retry_after() -> None:
    respx.get("https://data.optionsanalysissuite.com/v1/data/snapshot/SPY").mock(
        return_value=Response(
            429,
            headers={"Retry-After": "30", "X-RateLimit-Bucket": "data"},
            json={"error": "rate limit exceeded"},
        )
    )
    with OASClient(api_key="oas_test_xyz") as client:
        with pytest.raises(RateLimitError) as ei:
            client.snapshot("SPY")
    assert ei.value.retry_after == 30
    assert ei.value.bucket == "data"


def test_snapshot_requires_symbol() -> None:
    with OASClient(api_key="oas_test_xyz") as client:
        with pytest.raises(ValueError):
            client.snapshot("")


def test_oasclient_requires_api_key() -> None:
    with pytest.raises(ValueError):
        OASClient(api_key="")


@respx.mock
def test_snapshot_raises_permission_denied_with_required_scope() -> None:
    respx.get("https://data.optionsanalysissuite.com/v1/data/snapshot/SPY").mock(
        return_value=Response(
            403,
            json={
                "error": "API key missing required scope",
                "code": "INSUFFICIENT_SCOPE",
                "requiredScope": "data",
            },
        )
    )
    with OASClient(api_key="oas_test_xyz") as client:
        with pytest.raises(PermissionDeniedError) as ei:
            client.snapshot("SPY")
    assert ei.value.code == "INSUFFICIENT_SCOPE"
    assert ei.value.required_scope == "data"


@respx.mock
def test_calibration_quota_uses_correct_server_code() -> None:
    """Server emits CALIBRATION_QUOTA_EXCEEDED, not CALIBRATION_QUOTA."""
    respx.get("https://data.optionsanalysissuite.com/v1/data/snapshot/SPY").mock(
        return_value=Response(
            429,
            json={
                "error": "Daily calibration quota exhausted",
                "code": "CALIBRATION_QUOTA_EXCEEDED",
                "resetsAt": "2026-04-29T00:00:00Z",
            },
        )
    )
    with OASClient(api_key="oas_test_xyz") as client:
        with pytest.raises(CalibrationQuotaError) as ei:
            client.snapshot("SPY")
    assert ei.value.resets_at == "2026-04-29T00:00:00Z"


@respx.mock
def test_concurrency_limit_exceeded_maps_to_concurrency_error() -> None:
    """The calibration pool emits CONCURRENCY_LIMIT_EXCEEDED (not COMPUTE_*)."""
    respx.get("https://data.optionsanalysissuite.com/v1/data/snapshot/SPY").mock(
        return_value=Response(
            429,
            json={
                "error": "calibration concurrent limit",
                "code": "CONCURRENCY_LIMIT_EXCEEDED",
                "current": 1,
                "max": 1,
            },
        )
    )
    with OASClient(api_key="oas_test_xyz") as client:
        with pytest.raises(ConcurrencyLimitError) as ei:
            client.snapshot("SPY")
    assert ei.value.current == 1
    assert ei.value.max == 1


def test_path_param_url_encodes_dot_share_classes() -> None:
    """Symbols like BRK.B must round-trip through path interpolation safely."""
    from oas.client import _path_param

    assert _path_param("SPY") == "SPY"
    assert _path_param("BRK.B") == "BRK.B"  # quote(safe="") leaves dots alone
    assert _path_param("foo/bar") == "foo%2Fbar"
    assert _path_param("a b") == "a%20b"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


@respx.mock
def test_exposure_union_is_flat_and_parses_every_methodology() -> None:
    """The three answer shapes of POST /v1/compute/exposure, recorded from the engine, parse.

    ExposureResponse is one RootModel over a flat union (design R3-1: a nested oneOf would
    have made it response.root.root): .root.netGamma on a methodology-1 snapshot,
    .root.snapshot on a methodology-1 full result, .root.exposureV2 on a methodology-2 answer.
    The methodology is a Literal, so a client may branch on it.
    """
    from pydantic import BaseModel, RootModel

    from oas._generated.models import ExposureFullResult, ExposureResponseV2, ExposureSnapshot

    url = "https://data.optionsanalysissuite.com/v1/compute/exposure"
    answers = ["exposure_v1_snapshot.json", "exposure_v1_full.json", "exposure_v2.json"]
    respx.post(url).mock(side_effect=[Response(200, json=_fixture(name)) for name in answers])
    row = {"strike_cents": 500000, "stk_px_cents": 500000, "c_oi": 1, "p_oi": 1, "gamma": 0.001}
    strikes = [row]
    with OASClient(api_key="oas_test_xyz") as client:
        snap, full, v2 = (client.exposure(strikes=strikes, spot_price=5000.0) for _ in answers)

    for response in (snap, full, v2):
        assert isinstance(response.root, BaseModel) and not isinstance(response.root, RootModel)
    assert isinstance(snap.root, ExposureSnapshot)
    assert snap.root.netGamma == _fixture("exposure_v1_snapshot.json")["netGamma"]
    assert snap.root.methodology == 1
    assert isinstance(full.root, ExposureFullResult)
    assert full.root.snapshot.netGamma == _fixture("exposure_v1_full.json")["snapshot"]["netGamma"]
    assert isinstance(v2.root, ExposureResponseV2)
    assert v2.root.methodology == 2
    recorded = _fixture("exposure_v2.json")["exposureV2"]
    assert v2.root.exposureV2.assumedDealerBook.gex == recorded["assumedDealerBook"]["gex"]
    assert v2.root.exposureV2.byStrike is not None
    assert [s.strike for s in v2.root.exposureV2.byStrike] == [4950, 5050]


@respx.mock
def test_exposure_sends_methodology_symbol_and_as_of_and_leaves_unsent_inputs_out() -> None:
    """exposure() names the methodology, the symbol and asOf; an unset input is never sent.

    The server never assumes spot, rate or yield (it resolves them from ``symbol`` or answers
    422), so the SDK must not send a placeholder either.
    """
    url = "https://data.optionsanalysissuite.com/v1/compute/exposure"
    route = respx.post(url).mock(return_value=Response(200, json=_fixture("exposure_v2.json")))
    row = {"strike_cents": 500000, "stk_px_cents": 500000, "c_oi": 1, "p_oi": 1, "gamma": 0.001}
    with OASClient(api_key="oas_test_xyz") as client:
        client.exposure(strikes=[row], risk_free_rate=0.04, methodology=2, symbol="SPX",
                        as_of="2026-10-23T15:00:00Z", detail="snapshot")
        client.exposure(strikes=[row], spot_price=5000.0, risk_free_rate=0.04, dividend_yield=0.013)
    sent = [json.loads(call.request.content) for call in route.calls]
    assert sent[0] == {"strikes": [row], "riskFreeRate": 0.04, "methodology": 2, "symbol": "SPX",
                       "asOf": "2026-10-23T15:00:00Z"}
    assert route.calls[0].request.url.params["detail"] == "snapshot"
    assert sent[1] == {"strikes": [row], "spotPrice": 5000.0, "riskFreeRate": 0.04,
                       "dividendYield": 0.013}


@respx.mock
def test_exposure_eod_stays_a_dict_and_typed_returns_the_model() -> None:
    """exposure_eod() stays a dict; typed=True returns EodExposureResponse with exposureV2.

    The answer is the published example (the spec's, from the SDK's fixture), whose
    exposureV2 the data API's tests pin to what the route serves.
    """
    from oas._generated.models import EodExposureResponse, ExposureV2Stored

    spec = _fixture("openapi.snapshot.json")
    operation = spec["paths"]["/v1/data/exposure/{symbol}"]["get"]
    content = operation["responses"]["200"]["content"]["application/json"]
    example = content["examples"]["example"]["value"]
    url = "https://data.optionsanalysissuite.com/v1/data/exposure/TSLA"
    respx.get(url).mock(return_value=Response(200, json=example))
    with OASClient(api_key="oas_test_xyz") as client:
        plain = client.exposure_eod("TSLA")
        typed = client.exposure_eod("TSLA", typed=True)

    assert isinstance(plain, dict)
    assert plain["exposureV2"]["available"] is True
    assert isinstance(typed, EodExposureResponse)
    assert typed.gammaFlip == example["gammaFlip"]
    assert typed.exposureV2 is not None
    stored = typed.exposureV2
    assert isinstance(stored, ExposureV2Stored)
    assert stored.available is True
    assert stored.assumedDealerBook.gex == example["exposureV2"]["assumedDealerBook"]["gex"]
    assert stored.source == "eod_options_chain"


def test_regime_exposure_meta_reads_a_regime_rows_blocks() -> None:
    """RegimeExposureMeta (the regime rows' vector._meta, documented) reads both blocks.

    The rows themselves stay dicts (regime(), regime_intraday() and regime_current().daily), so
    a caller validates ``row["vector"]["_meta"]`` itself; its other fields are kept.
    """
    from oas._generated.models import ExposureV2Block, RegimeExposureMeta, RegimeExposureV1

    spec = _fixture("openapi.snapshot.json")
    v2 = spec["paths"]["/v1/data/exposure/{symbol}"]["get"]["responses"]["200"]["content"][
        "application/json"]["examples"]["example"]["value"]["exposureV2"]
    block = {k: v for k, v in v2.items()
             if k not in ("available", "provenance", "definition", "expiryQualifier", "byStrike",
                          "byStrikeUnavailable")}
    v1 = {"spotPrice": 231.4, "netGamma": 1.2e9, "netDelta": -2e9, "netVega": 3e7, "netVanna": 1e6,
          "netCharm": -2e5, "netVomma": 1e4, "callWall": 240, "putWall": 220, "gammaFlip": 225,
          "absGamma": 230, "gammaConcentration": 0.4, "regime": "positive", "topStrikes": [],
          "availability": {"gammaRows": 6, "deltaRows": 6, "vegaRows": 6, "higherOrderRows": 6},
          "methodology": 1}
    meta = RegimeExposureMeta.model_validate({"gex": v1, "gexV2": block, "fitWindow": 252})
    assert isinstance(meta.gex, RegimeExposureV1)
    assert meta.gex.availability is not None and meta.gex.availability.higherOrderRows == 6
    assert isinstance(meta.gexV2, ExposureV2Block)
    assert meta.gexV2.source == "eod_options_chain"
    assert meta.model_extra == {"fitWindow": 252}
