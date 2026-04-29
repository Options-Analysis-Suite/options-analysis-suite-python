# Options Analysis Suite — Python SDK

Type-safe Python client for the [Options Analysis Suite API](https://optionsanalysissuite.com).

> **Status: alpha (`0.1.0a1`)** — full coverage of every typed `/v1/*`
> operationId, plus a `Calibration` domain helper. Drift-checked against
> the deployed OpenAPI spec.

## Install

```bash
pip install options-analysis-suite
```

> Available on PyPI after the first `v*` tag is published. Until then,
> install from source with `pip install -e .` from a repo checkout.

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

    # Calibrate once, persist, reuse — never re-touches the calibrationId TTL.
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
    print(f"slow down — retry in {e.retry_after}s (bucket: {e.bucket})")
except CalibrationQuotaError as e:
    print(f"calibration quota exhausted; resets at {e.resets_at}")
```

See [`src/oas/errors.py`](src/oas/errors.py) for the full hierarchy.

## Models

Response models live in `oas._generated.models` and are auto-generated from
the OpenAPI spec at build time. The generated classes use `extra='ignore'`
so additive server fields (e.g., a new metric in `MetricsResponse`) don't
break older SDK versions — older SDKs will simply omit unknown fields.

To regenerate against the latest spec:

```bash
make gen
```

## Development

```bash
# Set up dev env
make install

# Lint / typecheck / test
make lint
make typecheck
make test         # unit + drift, no network. Uses tests/fixtures/openapi.snapshot.json
make test-live    # integration (needs OAS_API_KEY env var). Also re-checks the
                  # pinned spec fixture against the deployed /openapi.json.
                  # Refresh the fixture with:
                  #   curl -s https://data.optionsanalysissuite.com/openapi.json \
                  #     > tests/fixtures/openapi.snapshot.json

# Build distribution
make build
```

## Drift gate

The SDK's `_manifest.py` registers every operationId → `OASClient` method
pairing. `tests/test_drift.py` runs four checks against the spec:

1. Every `ENDPOINTS` operationId actually exists in `/openapi.json`
2. Every registered `Endpoint.sdk_method` resolves to a real `OASClient` attr
3. Every registered `Endpoint.path` is a path in the spec
4. **Strict gate**: spec ops − ignored − expected-missing == `ENDPOINTS` keys.
   Catches both unfinished stubs left in the allowlist and surprise spec
   additions.

The `EXPECTED_MISSING_OPERATION_IDS` allowlist is **empty** — the SDK
covers every typed operation. The `live` test suite double-checks that
the pinned `tests/fixtures/openapi.snapshot.json` still matches deployed
prod.

## Updating the SDK when the spec changes

When the upstream OpenAPI spec changes, the SDK reacts as follows:

| Spec change | SDK reaction | Maintainer action |
|---|---|---|
| **New field** on existing schema (e.g., add `vegaWeighted` to `MetricsResponse`) | Old SDK versions silently ignore the unknown field via `extra='ignore'` — users on `0.1.x` don't break. | `make gen` to expose the new field on the response model. Bump version, update CHANGELOG, release. |
| **New endpoint** (new operationId) | `tests/test_drift.py` fails the strict-gate assertion, naming the missing operationId. | Add a method to `src/oas/client.py`, add an entry to `src/oas/_manifest.py`, run `make test` until drift passes, release. |
| **Removed / renamed endpoint** | Drift gate fails the other way — the SDK manifest references an operationId that no longer exists. | Remove the corresponding `client.py` method and `_manifest.py` entry. Bump major if the SDK had shipped that method publicly. |
| **Schema field type change** (e.g., `atmIv: number → string`) | `make gen` regenerates with the new type; `mypy --strict` flags any callers that assumed the old type. | Fix call sites, regen, release. |
| **Spec fixture stale** | `make test-live` fetches the deployed `/openapi.json` and compares against `tests/fixtures/openapi.snapshot.json`. | Refresh the fixture: `curl -s https://data.optionsanalysissuite.com/openapi.json > tests/fixtures/openapi.snapshot.json` and commit. |

The drift gate is the forcing function — you cannot accidentally ship an
SDK that's out of sync with the deployed API surface.

## Release process (maintainers)

Releases are tag-driven via the `publish.yml` GitHub Actions workflow.
The publish job uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC) — no API tokens are stored anywhere.

**One-time setup (on PyPI):**

1. Visit https://pypi.org/manage/account/publishing/
2. Add a pending publisher with:
   - Owner: `Options-Analysis-Suite`
   - Repository: `options-analysis-suite-python`
   - Workflow filename: `publish.yml`
   - Environment: `pypi`
3. (After the first publish, the project will exist on PyPI and the
   pending publisher becomes a regular trusted publisher.)

**One-time setup (on GitHub):**

The publish job runs in a GitHub environment named `pypi` (see
`environment: pypi` in `publish.yml`). Create it under **Settings →
Environments → New environment**. Optional but recommended: require
manual approval, restrict to the `main` branch, and add reviewers so a
stray tag push can't ship to PyPI without a human in the loop.

**Per-release:**

1. Bump `version` in `pyproject.toml` to the new version
   (e.g. `0.1.0a1` → `0.1.0`).
2. Update `CHANGELOG.md` under the new version heading; move
   `[Unreleased]` items into it.
3. Commit (`chore: release vX.Y.Z`).
4. Tag the commit: `git tag vX.Y.Z` (the `v` prefix is required — the
   publish workflow only triggers on tags matching `v*`).
5. Push the tag: `git push origin vX.Y.Z`.

The workflow:
- Verifies the tag's version matches `pyproject.toml`
- Runs lint + typecheck + offline tests
- Builds sdist + wheel via `uv build`
- Publishes to PyPI through the OIDC trusted publisher

If the tag-vs-pyproject guard fails, fix `pyproject.toml`, retag with
`git tag -d` + recreate, and re-push.

## License

MIT — see [LICENSE](LICENSE).
