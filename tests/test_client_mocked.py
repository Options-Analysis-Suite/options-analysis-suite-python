"""Unit tests for OASClient using respx to mock the underlying httpx transport.

These tests don't hit the network; they exercise:
- request shape (path, headers)
- response parsing into typed Pydantic models
- error mapping (status code → typed exception)
"""

from __future__ import annotations

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


@respx.mock
def test_snapshot_parses_response_into_typed_model() -> None:
    fixture = {
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
