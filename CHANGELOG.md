# Changelog

All notable changes to the `options-analysis-suite` Python SDK are documented
in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the SDK is in `0.x`, the public surface may change between minor
releases — pin to a specific `0.0.x` if you need stability. Breaking changes
will be called out in this file with **Breaking** at the start of the bullet.

## [Unreleased]

## [0.1.0a1] — 2026-04-28

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
- `iter_metrics(symbols, batch_size=50)` — chunks a large symbol list across
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

[Unreleased]: https://github.com/Options-Analysis-Suite/options-analysis-suite-python/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/Options-Analysis-Suite/options-analysis-suite-python/releases/tag/v0.1.0a1
