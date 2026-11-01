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
    "exposure": {"available": False, "reason": "no stored book"},
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


STORED: dict[str, Any] = {
    "available": True,
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
def test_snapshot_exposure_branches_on_available() -> None:
    """exposure is a union: the stored assumed dealer book, or why there is none.

    `available` is a Literal, so a plain truth test takes the right branch (a one-value Enum
    member of False was truthy). Every answer carries the field, so one without it is refused,
    and no number or retired name rides along.
    """
    from pydantic import ValidationError

    from oas._generated.models import ExposureStored, ExposureUnavailable

    base = "https://data.optionsanalysissuite.com/v1/data/snapshot"
    unavailable = {"available": False, "reason": "publication run mismatch"}
    answers = {
        "SPY": {**SNAPSHOT_FIXTURE, "exposure": STORED},
        "QQQ": {**SNAPSHOT_FIXTURE, "ticker": "QQQ", "exposure": unavailable},
        "DIA": {**SNAPSHOT_FIXTURE, "ticker": "DIA"},
        "IWM": {k: v for k, v in SNAPSHOT_FIXTURE.items() if k != "exposure"} | {"ticker": "IWM"},
    }
    for symbol, answer in answers.items():
        respx.get(f"{base}/{symbol}").mock(return_value=Response(200, json=answer))

    with OASClient(api_key="oas_test_xyz") as client:
        spy, qqq, dia = (client.snapshot(symbol) for symbol in ("SPY", "QQQ", "DIA"))
        with pytest.raises(ValidationError):
            client.snapshot("IWM")

    seen = []
    for snap in (spy, qqq, dia):
        exposure = snap.exposure
        if exposure.available:
            assert isinstance(exposure, ExposureStored)
            assert exposure.byStrike is not None
            seen.append(("book", exposure.assumedDealerBook.gex, exposure.byStrike[0].strike))
        else:
            assert isinstance(exposure, ExposureUnavailable)
            seen.append(("none", exposure.reason.value))
    assert seen == [("book", 1.0, 230), ("none", "publication run mismatch"),
                    ("none", "no stored book")]
    assert not hasattr(spy, "exposureV2") and "methodology" not in spy.exposure.model_dump()

@respx.mock
def test_snapshot_authenticates_with_bearer_token() -> None:
    captured: dict[str, str] = {}

    def _handler(request):
        captured["authorization"] = request.headers.get("Authorization", "")
        return Response(200, json={"ticker": "SPY", "date": "2026-04-25"} | {
            k: None for k in [
                "spotPrice", "maxPain", "atmIv",
                "atmIv7d", "atmIv30d", "atmIv90d", "putCallRatio", "ivSkew25d",
                "dividendYield", "totalVolume", "totalOi", "callVolume", "putVolume",
                "callOi", "putOi", "expectedMovePct", "ivRank", "ivPercentile",
                "hv20d", "hv60d",
                "maxPainCurve", "gexByStrike", "dexByStrike", "vannaByStrike",
                "charmByStrike", "vommaByStrike", "volSkew", "probabilityData",
                "chainData", "analyticsExpiry", "chainExpiry",
            ]
        } | {"exposure": {"available": False, "reason": "no stored book"}})

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
def test_exposure_parses_the_computed_book() -> None:
    """POST /v1/compute/exposure answers { exposure, resolved? }, recorded from the engine.

    ``.exposure`` is the assumed dealer book over the submitted chain (an ExposureComputed),
    with its expiry census; the answer carries no method field and no legacy result.
    """
    from oas._generated.models import ExposureComputed, ExposureComputeResponse

    url = "https://data.optionsanalysissuite.com/v1/compute/exposure"
    respx.post(url).mock(return_value=Response(200, json=_fixture("exposure.json")))
    row = {"strike_cents": 500000, "stk_px_cents": 500000, "c_oi": 1, "p_oi": 1, "gamma": 0.001}
    with OASClient(api_key="oas_test_xyz") as client:
        response = client.exposure(strikes=[row], spot_price=5000.0)

    assert isinstance(response, ExposureComputeResponse)
    assert isinstance(response.exposure, ExposureComputed)
    recorded = _fixture("exposure.json")["exposure"]
    assert response.exposure.assumedDealerBook.gex == recorded["assumedDealerBook"]["gex"]
    assert response.exposure.byStrike is not None
    assert [s.strike for s in response.exposure.byStrike] == [4950, 5050]
    assert response.exposure.expiryCensus.inScope == recorded["expiryCensus"]["inScope"]
    assert response.resolved is None
    assert "methodology" not in response.model_dump(exclude_none=True)["exposure"]


@respx.mock
def test_exposure_sends_symbol_and_as_of_and_leaves_unsent_inputs_out() -> None:
    """exposure() names the symbol and asOf; an unset input is never sent.

    The server never assumes spot, rate or yield (it resolves them from ``symbol`` or answers
    422), so the SDK must not send a placeholder either. The book is the only calculation, so
    the retired ``methodology`` and ``wall_max_dte`` keywords are gone (a TypeError, nothing
    sent), and no call sends either field.
    """
    url = "https://data.optionsanalysissuite.com/v1/compute/exposure"
    route = respx.post(url).mock(return_value=Response(200, json=_fixture("exposure.json")))
    row = {"strike_cents": 500000, "stk_px_cents": 500000, "c_oi": 1, "p_oi": 1, "gamma": 0.001}
    with OASClient(api_key="oas_test_xyz") as client:
        client.exposure(strikes=[row], risk_free_rate=0.04, symbol="SPX",
                        as_of="2026-10-23T15:00:00Z", detail="snapshot")
        client.exposure(strikes=[row], spot_price=5000.0, risk_free_rate=0.04, dividend_yield=0.013)
        retired: list[dict[str, Any]] = [{"methodology": 2}, {"wall_max_dte": 60}]
        for kwargs in retired:
            with pytest.raises(TypeError):
                client.exposure(strikes=[row], spot_price=5000.0, **kwargs)
    assert len(route.calls) == 2
    sent = [json.loads(call.request.content) for call in route.calls]
    assert sent[0] == {"strikes": [row], "riskFreeRate": 0.04, "symbol": "SPX",
                       "asOf": "2026-10-23T15:00:00Z"}
    assert route.calls[0].request.url.params["detail"] == "snapshot"
    assert sent[1] == {"strikes": [row], "spotPrice": 5000.0, "riskFreeRate": 0.04,
                       "dividendYield": 0.013}


@respx.mock
def test_exposure_eod_stays_a_dict_and_typed_returns_the_model() -> None:
    """exposure_eod() stays a dict; typed=True returns EodExposureResponse with ``exposure``.

    The answer is the published example (the spec's, from the SDK's fixture), whose
    ``exposure`` the data API's tests pin to what the route serves; its strikes are ranked.
    """
    from oas._generated.models import EodExposureResponse, ExposureStored

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
    assert plain["exposure"]["available"] is True
    assert isinstance(typed, EodExposureResponse)
    assert typed.schemaVersion == 2 and plain["schemaVersion"] == 2
    assert typed.gammaFlip == example["gammaFlip"]
    stored = typed.exposure
    assert isinstance(stored, ExposureStored)
    assert stored.available is True
    assert stored.assumedDealerBook.gex == example["exposure"]["assumedDealerBook"]["gex"]
    assert stored.source == "eod_options_chain"
    assert [(s.strike, s.rank) for s in typed.topContributingStrikes] == [
        (s["strike"], s["rank"]) for s in example["topContributingStrikes"]]
    assert [s.rank for s in typed.topContributingStrikes] == [1, 2, 3]


def test_regime_exposure_meta_reads_a_regime_rows_blocks() -> None:
    """RegimeExposureMeta (the regime rows' vector._meta, documented) reads both blocks.

    ``levels`` holds the walls, flip and ranked top strikes; ``exposure`` the stored book. The
    rows themselves stay dicts (regime(), regime_intraday() and regime_current().daily), so a
    caller validates ``row["vector"]["_meta"]`` itself; its other fields are kept.
    """
    from oas._generated.models import ExposureBlock, RegimeExposureMeta, RegimeLevels

    spec = _fixture("openapi.snapshot.json")
    stored = spec["paths"]["/v1/data/exposure/{symbol}"]["get"]["responses"]["200"]["content"][
        "application/json"]["examples"]["example"]["value"]["exposure"]
    block = {k: v for k, v in stored.items()
             if k not in ("available", "provenance", "definition", "expiryQualifier", "byStrike",
                          "byStrikeUnavailable")}
    levels = {"spotPrice": 231.4, "callWall": 240, "putWall": 220, "gammaFlip": 225,
              "absGamma": 230, "regime": "positive",
              "topStrikes": [{"strike": 230, "rank": 1}, {"strike": 240, "rank": 2}],
              "availability": {"gammaRows": 6}}
    row_meta = {"levels": levels, "exposure": block, "fitWindow": 252}
    meta = RegimeExposureMeta.model_validate(row_meta)
    assert isinstance(meta.levels, RegimeLevels)
    assert meta.levels.availability is not None and meta.levels.availability.gammaRows == 6
    assert [(s.strike, s.rank) for s in meta.levels.topStrikes] == [(230, 1), (240, 2)]
    assert isinstance(meta.exposure, ExposureBlock)
    assert meta.exposure.source == "eod_options_chain"
    assert meta.model_extra == {"fitWindow": 252}
