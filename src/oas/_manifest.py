"""SDK ↔ OpenAPI operationId manifest.

Maps each operationId served by ``/openapi.json`` to the OASClient method that
fulfils it. A drift test in ``tests/test_drift.py`` walks the deployed spec,
collects every operationId, and compares against this dict — keeping the SDK
honest about what it claims to cover.

Source of truth for the operationId set:
``data-api/openapi/operationIds.ts`` (in the main repo). The Python SDK
re-derives coverage from the served spec rather than parsing the TS file.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    """One entry in the SDK ↔ spec manifest."""

    method: str  # HTTP verb
    path: str  # path template, e.g. "/v1/data/snapshot/{symbol}"
    sdk_method: str  # OASClient method name


# operationId → Endpoint. Add new entries here whenever an OASClient method
# is introduced. The drift test will fail if anything in /openapi.json
# (minus SDK_IGNORED_OPERATION_IDS) is missing from this dict.
ENDPOINTS: dict[str, Endpoint] = {
    # Compute
    "compute.price":         Endpoint("POST", "/v1/compute/price", "price"),
    "compute.greeks":        Endpoint("POST", "/v1/compute/greeks", "greeks"),
    "compute.exposure":      Endpoint("POST", "/v1/compute/exposure", "exposure"),
    "compute.scenario":      Endpoint("POST", "/v1/compute/scenario", "scenario"),
    "compute.sensitivity":   Endpoint("POST", "/v1/compute/sensitivity", "sensitivity"),
    "compute.maxPain":       Endpoint("POST", "/v1/compute/max-pain", "max_pain"),
    "compute.expectedMove":  Endpoint("POST", "/v1/compute/expected-move", "expected_move"),
    "compute.probability":   Endpoint("POST", "/v1/compute/probability", "probability"),
    "compute.calibrate":     Endpoint("POST", "/v1/compute/calibrate", "calibrate"),

    # Data — regime
    "data.regime.current":  Endpoint("GET", "/v1/data/regime/current", "regime_current"),
    "data.regime.bySymbol": Endpoint("GET", "/v1/data/regime/{symbol}", "regime"),
    "data.regime.fits":     Endpoint("GET", "/v1/data/regime/fits/{symbol}", "regime_fits"),
    "data.regime.intraday": Endpoint("GET", "/v1/data/regime/intraday/{symbol}", "regime_intraday"),

    # Data — snapshot + metrics
    "data.snapshot.market":   Endpoint("GET", "/v1/data/snapshot/market", "snapshot_market"),
    "data.snapshot.bySymbol": Endpoint("GET", "/v1/data/snapshot/{symbol}", "snapshot"),
    "data.metrics.batch":     Endpoint("GET", "/v1/data/metrics/batch", "metrics_batch"),
    "data.metrics.bySymbol":  Endpoint("GET", "/v1/data/metrics/{symbol}", "metrics"),

    # Data — analytics
    "data.marketTrends":   Endpoint("GET", "/v1/data/market-trends", "market_trends"),
    "data.ivSurface":      Endpoint("GET", "/v1/data/iv-surface/{symbol}", "iv_surface"),
    "data.exposure.bySymbol": Endpoint("GET", "/v1/data/exposure/{symbol}", "exposure_eod"),
    "data.greeksHistory":  Endpoint("GET", "/v1/data/greeks-history/{symbol}", "greeks_history"),
    "data.scanner.ranked": Endpoint("GET", "/v1/data/scanner/ranked", "scanner_ranked"),

    # Data — SEC / FINRA market structure
    "data.failToDeliver":                  Endpoint("GET", "/v1/data/fail-to-deliver/{symbol}", "fail_to_deliver"),
    "data.shortVolume":                    Endpoint("GET", "/v1/data/short-volume/{symbol}", "short_volume"),
    "data.marketStructure.ats":            Endpoint("GET", "/v1/data/market-structure/ats/{symbol}", "market_structure_ats"),
    "data.marketStructure.otc":            Endpoint("GET", "/v1/data/market-structure/otc/{symbol}", "market_structure_otc"),
    "data.marketStructure.atsFirms":       Endpoint("GET", "/v1/data/market-structure/ats/{symbol}/firms", "market_structure_ats_firms"),
    "data.marketStructure.otcFirms":       Endpoint("GET", "/v1/data/market-structure/otc/{symbol}/firms", "market_structure_otc_firms"),
    "data.marketStructure.blocks":         Endpoint("GET", "/v1/data/market-structure/blocks", "market_structure_blocks"),
    "data.marketStructure.blocksByDealer": Endpoint("GET", "/v1/data/market-structure/blocks/dealer/{mpid}", "market_structure_blocks_by_dealer"),
    "data.thresholdHistory":               Endpoint("GET", "/v1/data/threshold-history/{symbol}", "threshold_history"),

    # Data — calendars
    "data.economicCalendar": Endpoint("GET", "/v1/data/economic-calendar", "economic_calendar"),
    "data.ipoCalendar":      Endpoint("GET", "/v1/data/ipo-calendar", "ipo_calendar"),
    "data.dividendCalendar": Endpoint("GET", "/v1/data/dividend-calendar", "dividend_calendar"),
    "data.splitCalendar":    Endpoint("GET", "/v1/data/split-calendar", "split_calendar"),

    # Data — corporate actions / fundamentals
    "data.dividends":      Endpoint("GET", "/v1/data/dividends/{symbol}", "dividends"),
    "data.stockSplits":    Endpoint("GET", "/v1/data/stock-splits/{symbol}", "stock_splits"),
    "data.companyProfile": Endpoint("GET", "/v1/data/company-profile/{symbol}", "company_profile"),
    "data.fundamentals":   Endpoint("GET", "/v1/data/fundamentals/{symbol}", "fundamentals"),
    "data.earnings":       Endpoint("GET", "/v1/data/earnings/{symbol}", "earnings"),
    "data.analysts":       Endpoint("GET", "/v1/data/analysts/{symbol}", "analysts"),
    "data.insiders":       Endpoint("GET", "/v1/data/insiders/{symbol}", "insiders"),
    "data.companyData":    Endpoint("GET", "/v1/data/company-data/{symbol}", "company_data"),
    "data.news":           Endpoint("GET", "/v1/data/news/{symbol}", "news"),
    "data.history":        Endpoint("GET", "/v1/data/history/{symbol}", "history"),

    # Data — macro / bonds
    "data.fred":                Endpoint("GET", "/v1/data/fred/{seriesId}", "fred"),
    "data.treasury.auctions":   Endpoint("GET", "/v1/data/treasury/auctions", "treasury_auctions"),
    "data.bonds.etf":           Endpoint("GET", "/v1/data/bonds/etf/{symbol}", "bond_etf"),
    "data.bonds.traceAggregates": Endpoint("GET", "/v1/data/bonds/trace/aggregates", "trace_aggregates"),
    "data.bonds.traceSentiment":  Endpoint("GET", "/v1/data/bonds/trace/sentiment", "trace_sentiment"),
}


# OperationIds the SDK intentionally does NOT expose as typed client methods.
# - health.check is unauthenticated and lives outside the analytics surface.
# - streaming.websocket has its own WS-client surface, separate from the
#   request/response client.
SDK_IGNORED_OPERATION_IDS: frozenset[str] = frozenset({
    "health.check",
    "streaming.websocket",
})

# OperationIds the SDK intends to expose but hasn't wired up yet. Empty —
# the strict drift gate test_sdk_covers_every_typed_operation_id passes
# only when every typed operationId in the spec has a registered SDK method.
EXPECTED_MISSING_OPERATION_IDS: frozenset[str] = frozenset()
