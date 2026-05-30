# Changelog

All notable changes to the `options-analysis-suite` Python SDK are documented
in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the SDK is in `0.x`, the public surface may change between minor
releases; pin to a specific `0.0.x` if you need stability. Breaking changes
will be called out in this file with **Breaking** at the start of the bullet.

## [Unreleased]

## [0.1.0a9] (2026-05-29)

### Added

- `OASClient.exposure_eod(symbol, *, date=None)` for the new
  `GET /v1/data/exposure/{symbol}` endpoint: symbol-keyed end-of-day dealer
  positioning - gamma magnet, gamma flip, call wall, put wall, dealer regime,
  net GEX/DEX, 30d expected move, and the top contributing strikes - precomputed
  from OAS's own EOD ORATS data (no chain upload required). Pass
  `date="YYYY-MM-DD"` for a historical session; omit for the latest. Returns the
  response dict and is registered in the drift manifest.

## [0.1.0a8] (2026-05-03)

### Fixed

- `ExposureSnapshot.absGamma` is now properly optional. The 0.1.0a7 release
  generated this field with `Field(...)` (required), which raised
  `ValidationError` against API responses or pinned fixtures that omitted
  `absGamma`. Defaulting to `None` restores forward-compatible parsing
  consistent with `callWall`, `putWall`, and `gammaFlip`.

### Changed

- `scripts/gen_models.py` now post-processes regenerated models to default
  every nullable required field (`name: T | None = Field(...)`) to
  `Field(None)`. Mirrors the existing `extra='forbid'` → `extra='ignore'`
  relax pass: the OpenAPI spec stays strict for contract enforcement; the
  SDK is lenient at parse time. Prevents future `make gen` runs from
  silently reintroducing the 0.1.0a7 failure mode.
- `tests/fixtures/openapi.snapshot.json` refreshed from the redeployed
  data-api whose `/openapi.json` now correctly advertises
  `https://data.optionsanalysissuite.com` (the deployment honors
  `X-Forwarded-Proto` from the TLS-terminating proxy instead of the
  proxied `http://` hop).

## [0.1.0a7] (2026-05-03)

Pick up the new `absGamma` anchor on `ExposureSnapshot`.

### Added

- `ExposureSnapshot.absGamma` (`float | None`): the strike with the largest
  absolute net gamma in the wall/flip universe. Mirrors the field the
  data-api now returns alongside `callWall`, `putWall`, and `gammaFlip`.
  Existing snapshots without the field continue to deserialize because the
  SDK relaxes generated models to `extra='ignore'`; deserialized rows from
  the new server emit will populate it.

## [0.1.0a6] (2026-05-03)

Security hardening for Monte Carlo full-paths responses.

### Changed

- **Security:** `client.price(model="mc", detail="full", ...)` now raises
  `ValueError` unless the caller explicitly opts in with
  `allow_full_paths=True`. The `detail="full"` MC response can include
  very large `fullPaths` arrays that are eagerly decoded by the SDK,
  posing a client-side memory-exhaustion risk for callers who request
  it accidentally. The opt-in is scoped to MC only; non-MC models that
  pass `detail="full"` (the API silently ignores it for those) continue
  to work without change.

## [0.1.0a5] (2026-04-29)

Monte Carlo distribution + sensitivity sweep + calibration diagnostics.
Tracks the matching API release. No breaking changes to existing call
sites.

### Added

- `client.price(detail="distribution" | "full", histogram_bins=...)` for
  Monte Carlo (`model="mc"`). Default `detail="summary"` adds an
  `mcStats` block (stdError, 95% CI, effective path count): non-MC
  responses are byte-identical to prior releases.
- `client.price()` MC response now exposes `distribution` (mean / min /
  max, 9 percentiles, equal-width histogram of the simulated terminal
  underlying price) and, when `detail="full"`, `fullPaths` (subsampled
  raw paths) plus `fullPathsTruncated` flag.
- `client.sensitivity()` now returns the full 17-Greek set per point
  (was 5). New `model="heston"` plus `model_params={...}` swaps the
  per-point `price` to the Heston Fourier value and adds a
  `modelGreeks` block (dV0, dKappa, dTheta, dVolOfVol, dRho).
  Per-point `x` field replaces axis-specific keys (`spot` / `days` /
  `volatility`) for a uniform `{ x, ...greeks }` shape.
- `Calibration.fit_diagnostics`: per-moneyness-bucket residual RMSE
  (atm / otm_call / otm_put / deep_otm), per-bucket count, capped
  residual list, and worst-fitting option. Currently emitted by the
  API for `model="heston"` only; round-trips through `Calibration.save`
  / `from_json`.
- Beefed-up docstrings (Args / Returns / Raises) on the high-leverage
  compute methods (`price`, `greeks`, `exposure`, `scenario`,
  `sensitivity`, `calibrate`).

### Changed

- `mcStats.nPaths` reports the *effective* path count, which is up to
  2× requested when antithetic variates are enabled. Aligns with the
  count `distribution.count` is built from.
- `exposure()` docstring now reflects the actual strike-row schema
  (`strike_cents`, `stk_px_cents`, `c_oi`, `p_oi`, `gamma`).

### Fixed

- `oas.__version__` now matches the package metadata version.

## [0.1.0a4] (2026-04-29)

README polish only. No code changes; runtime surface byte-identical to
0.1.0a3.

### Changed

- Dropped the hardcoded version (`0.1.0a2`) from the README status
  callout. PyPI displays the version prominently at the top of the
  project page already; repeating it in the README just drifts on every
  release. Status line is now `**Status: alpha**` and stays correct
  release-over-release.

## [0.1.0a3] (2026-04-29)

Scenario response schema fix. This release updates the generated models to
match the live `/v1/compute/scenario` response.

### Fixed

- `OASClient.scenario(...)` now parses live scenario matrices correctly.
  Matrix cells are structured objects with `spotChange`, `volChange`, `spot`,
  `volatility`, `price`, `pnl`, and `pnlPercent`, not bare floats.
- Added mocked and live regression coverage for the scenario matrix shape.

## [0.1.0a2] (2026-04-29)

Documentation and packaging cleanup. No code changes; the `oas` runtime
surface is byte-identical to `0.1.0a1`.

### Changed

- README slimmed to user-facing content only. Maintainer docs (dev setup,
  drift gate, release process, spec-change matrix) moved to a separate
  `MAINTAINING.md` that does not ship in the wheel/sdist and does not
  render on the PyPI project page.
- `[project.urls]` cleaned: dropped `Repository` and `Changelog` entries
  (both pointed at a private GitHub repo and 404'd for PyPI visitors).
  Added `Pricing` and `SDK Reference` URLs that point at public pages.

## [0.1.0a1] (2026-04-28)

First public alpha. Architecture decided, full surface implemented, drift
checked against the deployed OpenAPI spec.

### Added

- `OASClient` with 49 typed methods covering every typed `/v1/*` operationId
  from the data-api OpenAPI spec.
  - **Compute (9):** `price`, `greeks`, `exposure`, `scenario`, `sensitivity`,
    `max_pain`, `expected_move`, `probability` (+ `probability_simple` /
    `probability_full` typed helpers), `calibrate`.
  - **Data (40):** snapshot, metrics, regime, IV surface, Greeks history,
    scanner, market structure (ATS/OTC/blocks), calendars (economic/IPO/
    dividend/split), corporate actions, news, history, FRED, Treasury
    auctions, bond ETF + TRACE.
- `Calibration` domain helper that wraps a `/v1/compute/calibrate` result.
  - `cal.price(...)` / `cal.greeks(...)` forward `modelParams=cal.params`
    automatically.
  - `cal.save("path.json")` / `Calibration.from_json("path.json", client=...)`
    for durable persistence; the 30-second-only `calibrationId` is
    intentionally not surfaced.
  - `_format_version=1` written to disk; loading newer files raises
    `ValueError`.
  - Symbol forwarding to `/price` / `/greeks` is suppressed only when the
    caller supplies full numeric inputs **including** numeric `t`, so
    compute-only API keys don't trip the server's data-scope check.
- `iter_metrics(symbols, batch_size=50)`: chunks a large symbol list across
  `/v1/data/metrics/batch` calls.
- Typed exceptions: `OASError`, `AuthenticationError`, `ValidationError`,
  `PermissionDeniedError` (with `.required_scope`), `NotFoundError`,
  `RateLimitError` (with `.retry_after`, `.bucket`), `CalibrationQuotaError`
  (with `.resets_at`), `ConcurrencyLimitError` (with `.current`, `.max`),
  `ServerError`.
- `BrokerCredentials` BYOK helpers: `TradierCredentials(token=...)`,
  `TastytradeCredentials(refresh_token=..., client_secret=...)`.
- Generated Pydantic v2 response models in `oas._generated.models`
  (88 classes from the OpenAPI spec). Post-processed to use
  `extra='ignore'` so additive server fields don't break older SDK
  versions.
- Drift-test suite (`tests/test_drift.py`) gates SDK coverage against
  `/openapi.json`. Strict-equality gate enabled.
- Pinned spec fixture at `tests/fixtures/openapi.snapshot.json` for offline
  test runs; `make test-live` checks freshness against deployed prod.

### Notes

- `py.typed` is intentionally **not** shipped in this release: the
  hand-written surface (client/errors/credentials/transport) is mypy-strict
  clean, but the auto-generated module has type-check warnings that won't
  resolve until `datamodel-code-generator` produces fully mypy-clean output.
  Methods still return typed Pydantic models at runtime.
- `Typing :: Typed` classifier withheld for the same reason.
- ListResponse-backed methods return `dict[str, Any]` so server-side
  top-level metadata (date, page, count, direction, etc.) is preserved.
  These will tighten to typed models as endpoint-specific schemas land
  upstream.
- Sync-only client. `AsyncOASClient` deferred until there's a user need.

[Unreleased]: https://github.com/Options-Analysis-Suite/options-analysis-suite-python/compare/v0.1.0a5...HEAD
[0.1.0a5]: https://github.com/Options-Analysis-Suite/options-analysis-suite-python/releases/tag/v0.1.0a5
[0.1.0a4]: https://github.com/Options-Analysis-Suite/options-analysis-suite-python/releases/tag/v0.1.0a4
[0.1.0a3]: https://github.com/Options-Analysis-Suite/options-analysis-suite-python/releases/tag/v0.1.0a3
[0.1.0a2]: https://github.com/Options-Analysis-Suite/options-analysis-suite-python/releases/tag/v0.1.0a2
[0.1.0a1]: https://github.com/Options-Analysis-Suite/options-analysis-suite-python/releases/tag/v0.1.0a1
