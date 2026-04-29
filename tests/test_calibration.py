"""Tests for the Calibration domain helper + the OASClient.calibrate flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from oas import Calibration, OASClient, TradierCredentials


@respx.mock
def test_calibrate_returns_calibration_with_fitted_params() -> None:
    respx.post("https://data.optionsanalysissuite.com/v1/compute/calibrate").mock(
        return_value=Response(200, json={
            "model": "heston",
            "symbol": "SPY",
            "expiration": "2026-06-19",
            "params": {
                "v0": 0.041, "kappa": 1.8, "theta": 0.05,
                "volOfVol": 0.42, "rho": -0.65,
            },
            "fitError": {"rmse": 0.0011, "maxError": 0.004},
            "calibrationTimeMs": 1230,
            "calibrationId": "cal_abc123",
            "provider": "tradier",
        })
    )

    with OASClient(api_key="oas_test_xyz") as client:
        cal = client.calibrate(
            "SPY", model="heston",
            broker=TradierCredentials(token="ttok"),
            expiration="2026-06-19",
        )

    assert isinstance(cal, Calibration)
    assert cal.model == "heston"
    assert cal.symbol == "SPY"
    assert cal.params["kappa"] == 1.8
    assert cal.fit_error == {"rmse": 0.0011, "maxError": 0.004}
    assert cal.calibration_time_ms == 1230
    assert cal.provider == "tradier"


@respx.mock
def test_calibrate_sends_broker_credentials_header() -> None:
    captured: dict[str, str] = {}

    def _handler(request):
        captured["broker_type"] = request.headers.get("X-Broker-Type", "")
        captured["tradier_key"] = request.headers.get("X-Tradier-Key", "")
        return Response(200, json={
            "model": "sabr", "symbol": "SPY",
            "params": {"alpha": 0.2, "beta": 0.5, "rho": -0.3, "nu": 0.4},
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/calibrate").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        client.calibrate(
            "SPY", model="sabr",
            broker=TradierCredentials(token="ttok-secret"),
        )

    assert captured["broker_type"] == "tradier"
    assert captured["tradier_key"] == "ttok-secret"


@respx.mock
def test_calibration_price_uses_fitted_params() -> None:
    """cal.price() forwards modelParams=cal.params to /v1/compute/price."""
    respx.post("https://data.optionsanalysissuite.com/v1/compute/calibrate").mock(
        return_value=Response(200, json={
            "model": "heston", "symbol": "SPY",
            "params": {"v0": 0.04, "kappa": 1.5, "theta": 0.05, "volOfVol": 0.4, "rho": -0.6},
        })
    )

    captured_payload: dict = {}

    def _price_handler(request):
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
        return Response(200, json={
            "price": 12.34,
            "model": "Heston",
            "inputs": {
                "isCall": True, "S": 650.0, "K": 650.0, "r": 0.05,
                "q": 0.012, "sigma": 0.15, "t": 0.25,
                "modelParams": captured_payload.get("modelParams", {}),
            },
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/price").mock(side_effect=_price_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        cal = client.calibrate(
            "SPY", model="heston",
            broker=TradierCredentials(token="ttok"),
        )
        result = cal.price(is_call=True, K=650, S=650, r=0.05, q=0.012, sigma=0.15, t=0.25)

    assert captured_payload["model"] == "heston"
    assert captured_payload["modelParams"] == {
        "v0": 0.04, "kappa": 1.5, "theta": 0.05, "volOfVol": 0.4, "rho": -0.6,
    }
    assert result.price == 12.34


def test_calibration_save_and_from_json_roundtrip(tmp_path: Path) -> None:
    cal = Calibration(
        model="heston", symbol="SPY",
        params={"v0": 0.04, "kappa": 1.5, "theta": 0.05},
        expiration="2026-06-19",
        fit_error={"rmse": 0.001},
        calibration_time_ms=1234,
        provider="tradier",
    )
    path = tmp_path / "spy_heston.json"
    cal.save(path)

    loaded = Calibration.from_json(path)
    assert loaded.model == "heston"
    assert loaded.symbol == "SPY"
    assert loaded.params == {"v0": 0.04, "kappa": 1.5, "theta": 0.05}
    assert loaded.expiration == "2026-06-19"
    assert loaded.fit_error == {"rmse": 0.001}
    assert loaded.calibration_time_ms == 1234
    assert loaded.provider == "tradier"


def test_calibration_from_json_without_client_cannot_price(tmp_path: Path) -> None:
    """Loaded calibration must be bound to a client before .price() works."""
    cal = Calibration(model="heston", symbol="SPY", params={"v0": 0.04})
    path = tmp_path / "c.json"
    cal.save(path)

    loaded = Calibration.from_json(path)
    with pytest.raises(RuntimeError, match="not bound to an OASClient"):
        loaded.price(is_call=True, K=650, S=650, r=0.05, q=0.0, sigma=0.15, t=0.25)


def test_calibration_bind_attaches_client() -> None:
    cal = Calibration(model="heston", symbol="SPY", params={"v0": 0.04})
    with OASClient(api_key="oas_test_xyz") as client:
        bound = cal.bind(client)
    assert bound is cal
    assert cal._client is client  # type: ignore[reportPrivateUsage]


def test_calibration_rejects_future_format_version(tmp_path: Path) -> None:
    """Should refuse to load files written by a newer SDK that bumped the format."""
    path = tmp_path / "future.json"
    path.write_text(json.dumps({
        "_format_version": 999,
        "model": "heston",
        "symbol": "SPY",
        "params": {"v0": 0.04},
    }))
    with pytest.raises(ValueError, match="newer than this SDK supports"):
        Calibration.from_json(path)


@respx.mock
def test_calibration_price_skips_symbol_when_numerics_complete() -> None:
    """cal.price() must NOT forward symbol when caller provides full numerics.

    Sending symbol triggers the server's ticker resolver, which requires both
    compute AND data scopes. A compute-only key would fail. This test pins
    the no-leak behavior.
    """
    respx.post("https://data.optionsanalysissuite.com/v1/compute/calibrate").mock(
        return_value=Response(200, json={
            "model": "heston", "symbol": "SPY",
            "params": {"v0": 0.04, "kappa": 1.5, "theta": 0.05, "volOfVol": 0.4, "rho": -0.6},
        })
    )

    captured: list[dict] = []

    def _handler(request):
        captured.append(json.loads(request.content))
        return Response(200, json={
            "price": 12.0, "model": "Heston",
            "inputs": {"isCall": True, "S": 650.0, "K": 650.0, "r": 0.05,
                       "q": 0.012, "sigma": 0.15, "t": 0.25},
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/price").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        cal = client.calibrate(
            "SPY", model="heston",
            broker=TradierCredentials(token="ttok"),
        )
        # Full numerics → symbol must NOT be forwarded
        cal.price(is_call=True, K=650, S=650, r=0.05, q=0.012, sigma=0.15, t=0.25)

    assert "symbol" not in captured[0], (
        f"calibrated price call leaked symbol={captured[0].get('symbol')!r} despite "
        f"full numeric inputs — would 403 on a compute-only key"
    )


@respx.mock
def test_calibration_price_forwards_symbol_when_only_expiry_no_t() -> None:
    """expiry/expiration alone is NOT sufficient to omit symbol.

    The server only converts expiry→t inside the ticker resolver. With no
    symbol, the resolver doesn't run and the server rejects missing t
    (data-api/routes/compute.ts:283). So a caller passing full numerics
    but using expiry= for tenor still needs symbol forwarded so the
    resolver does the date math.
    """
    respx.post("https://data.optionsanalysissuite.com/v1/compute/calibrate").mock(
        return_value=Response(200, json={
            "model": "heston", "symbol": "SPY",
            "params": {"v0": 0.04, "kappa": 1.5, "theta": 0.05, "volOfVol": 0.4, "rho": -0.6},
        })
    )

    captured: list[dict] = []

    def _handler(request):
        captured.append(json.loads(request.content))
        return Response(200, json={
            "price": 12.0, "model": "Heston",
            "inputs": {"isCall": True, "S": 650.0, "K": 650.0, "r": 0.05,
                       "q": 0.012, "sigma": 0.15, "t": 0.25},
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/price").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        cal = client.calibrate(
            "SPY", model="heston",
            broker=TradierCredentials(token="ttok"),
        )
        # Full S/r/q/sigma but tenor as expiry (string) instead of t (numeric).
        # Symbol must be forwarded so the resolver converts expiry → t.
        cal.price(
            is_call=True, K=650, S=650, r=0.05, q=0.012, sigma=0.15,
            expiry="2026-06-19",
        )

    assert captured[0].get("symbol") == "SPY", (
        "expiry alone (no numeric t) must trigger symbol forwarding so the "
        "resolver can convert expiry → t; otherwise the server 400s on "
        "missing tenor"
    )


@respx.mock
def test_calibration_price_uses_symbol_when_numerics_incomplete() -> None:
    """cal.price() must forward symbol when caller is missing inputs (auto-fill flow)."""
    respx.post("https://data.optionsanalysissuite.com/v1/compute/calibrate").mock(
        return_value=Response(200, json={
            "model": "heston", "symbol": "SPY",
            "params": {"v0": 0.04, "kappa": 1.5, "theta": 0.05, "volOfVol": 0.4, "rho": -0.6},
        })
    )

    captured: list[dict] = []

    def _handler(request):
        captured.append(json.loads(request.content))
        return Response(200, json={
            "price": 12.0, "model": "Heston",
            "inputs": {"isCall": True, "S": 650.0, "K": 650.0, "r": 0.05,
                       "q": 0.012, "sigma": 0.15, "t": 0.25},
        })

    respx.post("https://data.optionsanalysissuite.com/v1/compute/price").mock(side_effect=_handler)

    with OASClient(api_key="oas_test_xyz") as client:
        cal = client.calibrate(
            "SPY", model="heston",
            broker=TradierCredentials(token="ttok"),
        )
        # Only K + tenor — needs ticker auto-fill for S/r/q/sigma
        cal.price(is_call=True, K=650, expiry="2026-06-19")

    assert captured[0].get("symbol") == "SPY"


def test_calibration_repr_is_useful() -> None:
    cal = Calibration(
        model="heston", symbol="SPY",
        params={"v0": 0.04, "kappa": 1.5, "theta": 0.05},
        expiration="2026-06-19",
    )
    r = repr(cal)
    assert "heston" in r and "SPY" in r and "2026-06-19" in r and "3 keys" in r
