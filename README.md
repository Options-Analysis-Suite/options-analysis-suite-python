# Options Analysis Suite: Python SDK

[![PyPI version](https://img.shields.io/pypi/v/options-analysis-suite.svg)](https://pypi.org/project/options-analysis-suite/)
[![Python versions](https://img.shields.io/pypi/pyversions/options-analysis-suite.svg)](https://pypi.org/project/options-analysis-suite/)
[![License: MIT](https://img.shields.io/pypi/l/options-analysis-suite.svg)](https://opensource.org/licenses/MIT)

Type-safe Python client for the [Options Analysis Suite API](https://optionsanalysissuite.com).

> **Status: stable (1.0).** Full coverage of every typed `/v1/*`
> operationId, plus a `Calibration` domain helper. Drift-checked against
> the deployed OpenAPI spec. Follows semantic versioning: the public surface
> will not change incompatibly without a major version bump.

## Install

```bash
pip install options-analysis-suite
```

## Quickstart

```python
from oas import OASClient, TradierCredentials

with OASClient(api_key="oas_live_...") as client:
    # Data: cached EOD analytics
    snap = client.snapshot("SPY")
    print(snap.atmIv, snap.netGex, snap.maxPain)

    if snap.maxPainCurve:
        for row in snap.maxPainCurve:
            print(row.strike, row.totalPain)

    # Compute: 17 pricing models, full Greeks, exposure, expected move...
    price = client.price(model="bs", is_call=True, S=650, K=650, r=0.05,
                         q=0.012, sigma=0.15, t=0.25)
    greeks = client.greeks(model="heston", is_call=True, S=650, K=650, r=0.05,
                           q=0.012, sigma=0.15, t=0.25)

    # Calibrate once, persist, reuse: never re-touches the calibrationId TTL.
    cal = client.calibrate(
        "SPY", model="heston",
        broker=TradierCredentials(token="..."),
    )
    cal.save("spy_heston.json")

    # Evaluate the calibrated model anywhere across the chain.
    fair = cal.price(is_call=True, K=655, expiry="2026-06-19")

    # Stream batched metrics without manually paging.
    for m in client.iter_metrics(["SPY", "QQQ", "IWM", "DIA"], batch_size=50):
        print(m.symbol, m.ivRank)
```

## Monte Carlo distributions

When `model="mc"`, pass `detail="distribution"` to receive the full
terminal-price distribution (percentiles + histogram) alongside the scalar
price, or `detail="full"` to additionally receive the (subsampled) raw
paths. `detail="summary"` is the default and matches the byte-identical
shape any older caller already sees, plus an `mcStats` block (stdError +
95% CI + effective path count).

```python
res = client.price(
    model="mc", detail="distribution",
    is_call=True, S=650, K=650, r=0.05, q=0.012, sigma=0.15, t=0.25,
)
print(res.price, res.mcStats.stdError)
print(res.distribution.percentiles.p50, res.distribution.percentiles.p95)
```

## Sensitivity sweeps under Heston

`client.sensitivity(...)` returns the full 17-Greek set per point under
Black-Scholes by default. Pass `model="heston"` together with the fitted
Heston parameters (typically from a recent `client.calibrate(...)` call)
to swap the per-point `price` to the Heston Fourier value and add a
`modelGreeks` block with derivatives w.r.t. the five Heston parameters.

```python
cal = client.calibrate("SPY", model="heston",
                       broker=TradierCredentials(token="..."))
sweep = client.sensitivity(
    is_call=True, S=650, K=650, r=0.05, sigma=0.15, t=0.25,
    axis="spot", model="heston", model_params=cal.params,
)
for row in sweep.data:
    print(row.x, row.delta, row.modelGreeks.dV0, row.modelGreeks.dRho)
```

## Calibration round-trip

A `Calibration` is the durable wrapper around a `/v1/compute/calibrate` result.
The fitted `params` dict survives a JSON round-trip; the 30-second-only
`calibrationId` is intentionally not surfaced.

```python
# Load a saved calibration in another process / hours later.
from oas import Calibration, OASClient

cal = Calibration.from_json("spy_heston.json")
with OASClient(api_key="oas_live_...") as client:
    cal.bind(client)  # attach so cal.price() / cal.greeks() can fire HTTP
    price = cal.price(is_call=True, K=650, S=650, r=0.05, q=0.012,
                      sigma=0.15, t=0.25)
```

## Errors

Every error subclass carries the HTTP status, the server's structured `code`
field (when present), and any extra fields the server returned.

```python
from oas.errors import NotFoundError, RateLimitError, CalibrationQuotaError

try:
    snap = client.snapshot("UNKNOWN")
except NotFoundError as e:
    print(f"warehouse miss: {e}")
except RateLimitError as e:
    print(f"slow down, retry in {e.retry_after}s (bucket: {e.bucket})")
except CalibrationQuotaError as e:
    print(f"calibration quota exhausted; resets at {e.resets_at}")
```

The full hierarchy: `OASError` → `AuthenticationError`, `ValidationError`,
`PermissionDeniedError` (with `.required_scope`), `NotFoundError`,
`RateLimitError` (with `.retry_after`, `.bucket`),
`CalibrationQuotaError` (with `.resets_at`),
`ConcurrencyLimitError` (with `.current`, `.max`), `ServerError`.

## Models

Response objects are typed Pydantic v2 models. Import them from
`oas._generated.models` for type hints. The classes use `extra='ignore'`
so additive server fields (e.g., a new metric in `MetricsResponse`) don't
break older SDK versions; older SDKs simply omit unknown fields.

## License

MIT licensed.
