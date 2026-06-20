"""High-level Python client for the Options Analysis Suite API.

The :class:`OASClient` is a thin, hand-written ergonomic surface over the
auto-generated Pydantic response models in :mod:`oas._generated.models`.
Every typed operationId in the data-api OpenAPI spec is exposed as a
snake_case method here.

Compute methods accept snake_case keyword arguments mirroring the JSON-schema
fields; the SDK builds the camelCase payload internally. Data methods take
the URL parameters directly.

Return types: methods backed by tightened response schemas (snapshot,
metrics, price, greeks, exposure, calibrate, history, IV surface, expected
move, max pain, scenario, sensitivity, probability, regime/current) return
Pydantic v2 models from :mod:`oas._generated.models`. Methods backed by
loose schemas — the generic ``ListResponse`` wrapper and several
vendor-passthrough endpoints (company_profile, fundamentals, earnings,
analysts, insiders, company_data, fred, fail_to_deliver, threshold_history,
snapshot_market) — return ``dict[str, Any]`` so callers see the full
server payload (including top-level metadata like ``date``/``page``/``count``
that ``ListResponse`` would have dropped). These will tighten to typed
models as the OpenAPI spec firms up.

Typical usage::

    from oas import OASClient, TradierCredentials

    with OASClient(api_key="oas_live_...") as client:
        snap = client.snapshot("SPY")
        print(snap.atmIv, snap.netGex)

        cal = client.calibrate(
            "SPY", model="heston",
            broker=TradierCredentials(token="..."),
        )
        cal.save("spy_heston.json")
        price = cal.price(is_call=True, K=650, expiry="2026-06-19")
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

from oas._generated.models import (
    ExpectedMoveResponse,
    ExposureResponse,
    GreeksResponse,
    HistoryResponse,
    IVSurfaceResponse,
    MaxPainResponse,
    MetricsBatchResponse,
    MetricsResponse,
    PriceResponse,
    ProbabilityResponse,
    RegimeResponse,
    ScenarioResponse,
    SensitivityResponse,
    SnapshotResponse,
)
from oas._transport import Transport
from oas.calibration import Calibration
from oas.credentials import BrokerCredentials

DEFAULT_BASE_URL = "https://data.optionsanalysissuite.com"
MAX_METRICS_BATCH_SYMBOLS = 50


def _path_param(value: str) -> str:
    """URL-encode a path-segment parameter.

    Forces ``safe=""`` so dots, slashes, and reserved characters in symbols
    (e.g. ``BRK.B``) and MPIDs round-trip correctly. Used by every
    ``OASClient`` method that interpolates user input into a path template.
    """
    return quote(value, safe="")


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    """Build a payload/query dict, omitting None values.

    Compute-method bodies and query-param dicts contain many optional fields;
    sending ``None`` would either confuse the server or get rejected as an
    invalid type. This filters them out cleanly.
    """
    return {k: v for k, v in d.items() if v is not None}


def _ensure_dict(body: Any) -> dict[str, Any]:
    """Validate a transport response body is a JSON object before returning it.

    Used by methods whose response schema is loose (vendor passthroughs and
    list-style endpoints whose top-level metadata varies per route). Raises
    ``TypeError`` rather than asserting so the check survives ``python -O``.
    """
    if not isinstance(body, dict):
        raise TypeError(
            f"OAS endpoint returned a non-object response: {type(body).__name__}"
        )
    return body


class OASClient:
    """Synchronous client for the Options Analysis Suite API.

    :param api_key: Your OAS API key (``oas_live_...``).
    :param base_url: Override the API base URL (defaults to production).
    :param timeout: Per-request timeout in seconds (default 30s).

    Use as a context manager (or call :meth:`close`) to release the underlying
    httpx connection pool.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self._transport = Transport(api_key=api_key, base_url=base_url, timeout=timeout)

    # ════════════════════════════════════════════════════════════════════
    # Compute
    # ════════════════════════════════════════════════════════════════════

    def price(
        self,
        *,
        is_call: bool,
        K: float,
        model: str = "bs",
        S: float | None = None,
        r: float | None = None,
        q: float | None = None,
        sigma: float | None = None,
        t: float | None = None,
        symbol: str | None = None,
        expiry: str | None = None,
        expiration: str | None = None,
        resolve: dict[str, Any] | None = None,
        model_params: dict[str, Any] | None = None,
        calibration_id: str | None = None,
        steps: int | None = None,
        is_american: bool | None = None,
        broker: BrokerCredentials | None = None,
        detail: str | None = None,
        histogram_bins: int | None = None,
        allow_full_paths: bool = False,
    ) -> PriceResponse:
        """Price an option (operationId ``compute.price``).

        Provide explicit pricing inputs (S, K, r, q, sigma, t) OR pass
        ``symbol`` (plus tenor as ``t`` or ``expiry``) to let the API
        auto-fill from cached market data. ``broker`` is required when
        ``resolve={"calibration": True}``.

        ``detail`` is honored only for ``model="mc"``:

        * ``"summary"`` (default): scalar price + ``mcStats`` (stdError,
          95% CI, effective path count).
        * ``"distribution"``: adds a ``distribution`` block with
          mean / min / max, 9 percentiles (p1, p5, p10, p25, p50, p75,
          p90, p95, p99), and an equal-width histogram of the simulated
          terminal underlying price.
        * ``"full"``: adds ``fullPaths`` — the (subsampled) raw paths
          matrix. Server enforces caps on path count and total points
          serialized; ``fullPathsTruncated: True`` flags subsampling.

        ``histogram_bins`` controls the bin count for ``detail="distribution"``
        and ``detail="full"``; clamped to ``[2, 200]``, default 50.

        ``detail="full"`` (Monte Carlo only) can produce very large
        responses. To prevent accidental memory pressure, MC callers must
        explicitly set ``allow_full_paths=True`` to request full raw
        paths. ``detail`` is ignored by the API for non-MC models, so the
        guard is scoped to MC and does not block other models.
        """
        is_mc = isinstance(model, str) and model.strip().lower() in {
            "mc", "monte_carlo", "montecarlo", "monte-carlo",
        }
        if is_mc and detail == "full" and not allow_full_paths:
            raise ValueError(
                'model="mc" with detail="full" is disabled by default because it can '
                "return very large responses; pass allow_full_paths=True to opt in."
            )
        payload = _drop_none({
            "model": model, "isCall": is_call, "K": K,
            "S": S, "r": r, "q": q, "sigma": sigma, "t": t,
            "symbol": symbol, "expiry": expiry, "expiration": expiration,
            "resolve": resolve, "modelParams": model_params,
            "calibrationId": calibration_id, "steps": steps,
            "isAmerican": is_american,
            "detail": detail,
            "histogramBins": histogram_bins,
        })
        headers = dict(broker.headers()) if broker else None
        body = self._transport.request(
            "POST", "/v1/compute/price", json=payload, headers=headers,
        )
        return PriceResponse.model_validate(body)

    def greeks(
        self,
        *,
        is_call: bool,
        K: float,
        model: str = "bs",
        S: float | None = None,
        r: float | None = None,
        q: float | None = None,
        sigma: float | None = None,
        t: float | None = None,
        symbol: str | None = None,
        expiry: str | None = None,
        expiration: str | None = None,
        resolve: dict[str, Any] | None = None,
        model_params: dict[str, Any] | None = None,
        calibration_id: str | None = None,
        include_insight: bool | None = None,
        steps: int | None = None,
        is_american: bool | None = None,
        broker: BrokerCredentials | None = None,
    ) -> GreeksResponse:
        """Compute the full 17-Greek response (operationId ``compute.greeks``).

        All 17 models compute all 17 Greeks (Delta, Gamma, Vega, Theta, Rho,
        Epsilon, Vanna, Charm, Vomma, Veta, Speed, Zomma, Color, Ultima,
        Lambda, Phi, DcharmDvol). Analytical / native Greeks are used where
        available; finite-difference bump-and-reprice fills the rest.

        Args:
            is_call: True for a call, False for a put.
            K: Strike price (dollars).
            model: One of ``"bs"``, ``"heston"``, ``"sabr"``, ``"jd"``,
                ``"vg"``, ``"binomial"``, ``"pde"``, ``"fft"``, ``"mc"``,
                ``"localvol"``, or one of the seven exotic codes
                (``"barrier"``, ``"asian"``, ``"lookback"``, ``"digital"``,
                ``"compound"``, ``"chooser"``, ``"multiasset"``).
            S, r, q, sigma, t: Pricing inputs. Pass these explicitly OR
                supply ``symbol`` (with ``t`` or ``expiry``) and let the API
                auto-fill them from cached market data.
            include_insight: Set True for exotic models to receive an
                ``exoticInsight`` strategy card alongside the Greeks.
            broker: BYOK credentials when ``resolve={"calibration": True}``.

        Returns:
            :class:`GreeksResponse` with every Greek typed at the top level.

        Raises:
            ValidationError: bad inputs.
            AuthenticationError / PermissionDeniedError: API key / scope.
            RateLimitError: per-minute or per-day bucket exhausted.
        """
        payload = _drop_none({
            "model": model, "isCall": is_call, "K": K,
            "S": S, "r": r, "q": q, "sigma": sigma, "t": t,
            "symbol": symbol, "expiry": expiry, "expiration": expiration,
            "resolve": resolve, "modelParams": model_params,
            "calibrationId": calibration_id, "includeInsight": include_insight,
            "steps": steps, "isAmerican": is_american,
        })
        headers = dict(broker.headers()) if broker else None
        body = self._transport.request(
            "POST", "/v1/compute/greeks", json=payload, headers=headers,
        )
        return GreeksResponse.model_validate(body)

    def exposure(
        self,
        *,
        strikes: list[dict[str, Any]],
        spot_price: float,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
        wall_max_dte: float | None = None,
        detail: str | None = None,
    ) -> ExposureResponse:
        """Compute Greek exposure profile (operationId ``compute.exposure``).

        Aggregates per-strike option exposure (GEX, DEX, VEX, Vanna, Charm,
        Vomma) under the standard dealer-hedging convention: retail is
        assumed net long calls and net short puts; dealers take the
        offsetting position.

        Args:
            strikes: List of per-strike rows. Required keys: ``strike_cents``,
                ``stk_px_cents``, ``c_oi``, ``p_oi``, ``gamma``. Optional:
                ``delta``, ``vega``, ``smooth_smv_vol``, ``c_mid_iv``,
                ``p_mid_iv``, ``yte``, ``expir_date``.
            spot_price: Current spot price for the underlying (in dollars).
            risk_free_rate: Annual rate (decimal). Server defaults to 0.05.
            dividend_yield: Annual yield (decimal). Server defaults to 0.
            wall_max_dte: Cap (days) for considering a strike a "wall"
                candidate. Server-side default if omitted.
            detail: ``"snapshot"`` for the flat :class:`ExposureSnapshot`
                shape; omit (or any other value) for the full
                ``{snapshot, byStrike}`` wrapper.

        Returns:
            :class:`ExposureResponse` — a ``oneOf`` union. Access
            ``.root`` to dispatch on the variant.

        Raises:
            ValidationError: malformed strike rows.
            AuthenticationError / PermissionDeniedError: API key / scope.
        """
        payload = _drop_none({
            "strikes": strikes, "spotPrice": spot_price,
            "riskFreeRate": risk_free_rate, "dividendYield": dividend_yield,
            "wallMaxDte": wall_max_dte,
        })
        params = {"detail": detail} if detail else None
        body = self._transport.request(
            "POST", "/v1/compute/exposure", json=payload, params=params,
        )
        return ExposureResponse.model_validate(body)

    def scenario(
        self,
        *,
        is_call: bool,
        S: float,
        K: float,
        r: float,
        sigma: float,
        t: float,
        spot_changes: list[float],
        vol_changes: list[float],
        q: float | None = None,
    ) -> ScenarioResponse:
        """Compute a 2D spot × volatility price matrix (operationId ``compute.scenario``).

        Each cell of the returned matrix is a structured object — not a bare
        float — with ``spotChange``, ``volChange``, ``spot``, ``volatility``,
        ``price``, ``pnl``, and ``pnlPercent``. Useful for stress-test grids
        across spot and vol shocks at a fixed expiry.

        Args:
            is_call, S, K, r, sigma, t, q: Pricing inputs at the base of the
                matrix.
            spot_changes: Decimal spot-shift list (e.g. ``[-0.10, -0.05, 0,
                0.05, 0.10]``).
            vol_changes: Decimal vol-shift list (e.g. ``[-0.05, 0, 0.05]``).

        Returns:
            :class:`ScenarioResponse` with ``matrix[i][j]`` indexed by
            ``[spotChange][volChange]``.
        """
        payload = _drop_none({
            "isCall": is_call, "S": S, "K": K, "r": r, "q": q,
            "sigma": sigma, "t": t,
            "spotChanges": spot_changes, "volChanges": vol_changes,
        })
        body = self._transport.request("POST", "/v1/compute/scenario", json=payload)
        return ScenarioResponse.model_validate(body)

    def sensitivity(
        self,
        *,
        is_call: bool,
        S: float,
        K: float,
        r: float,
        sigma: float,
        t: float,
        axis: str,
        q: float | None = None,
        points: int | None = None,
        spot_min: float | None = None,
        spot_max: float | None = None,
        days_to_expiry: float | None = None,
        vol_min: float | None = None,
        vol_max: float | None = None,
        model: str | None = None,
        model_params: dict[str, Any] | None = None,
        greeks: list[str] | None = None,
    ) -> SensitivityResponse:
        """Generate a 1D sensitivity grid (operationId ``compute.sensitivity``).

        ``axis`` ∈ {``"spot"``, ``"time"``, ``"volatility"``} chooses the sweep
        dimension. Matching bounds are optional; the API uses sensible defaults
        when they are omitted.

        ``model`` defaults to ``"bs"`` (all 17 Black-Scholes Greeks per point).
        Pass ``model="heston"`` together with ``model_params={"v0", "kappa",
        "theta", "volOfVol" (or "sigma"), "rho"}`` to swap the per-point
        ``price`` to the Heston Fourier value and add a ``modelGreeks`` block
        with derivatives w.r.t. the five Heston parameters. ``greeks`` filters
        the standard Greeks returned at each point — omit to receive all 17.
        """
        payload = _drop_none({
            "isCall": is_call, "S": S, "K": K, "r": r, "q": q,
            "sigma": sigma, "t": t,
            "axis": axis, "points": points,
            "spotMin": spot_min, "spotMax": spot_max,
            "daysToExpiry": days_to_expiry,
            "volMin": vol_min, "volMax": vol_max,
            "model": model,
            "modelParams": model_params,
            "greeks": greeks,
        })
        body = self._transport.request("POST", "/v1/compute/sensitivity", json=payload)
        return SensitivityResponse.model_validate(body)

    def max_pain(self, *, strikes: list[dict[str, Any]]) -> MaxPainResponse:
        """Compute the max-pain strike from per-strike OI (operationId ``compute.maxPain``)."""
        body = self._transport.request(
            "POST", "/v1/compute/max-pain", json={"strikes": strikes},
        )
        return MaxPainResponse.model_validate(body)

    def expected_move(
        self,
        *,
        spot_price: float,
        days_to_expiry: float,
        strike_price: float | None = None,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
        atm_iv: float | None = None,
        atm_call_price: float | None = None,
        atm_put_price: float | None = None,
    ) -> ExpectedMoveResponse:
        """Compute expected move via market-straddle or BS lognormal.

        operationId ``compute.expectedMove``. Pass ``atm_call_price`` +
        ``atm_put_price`` for the market-straddle method; otherwise pass
        ``atm_iv`` for the Black-Scholes lognormal approximation.
        """
        payload = _drop_none({
            "spotPrice": spot_price,
            "strikePrice": strike_price,
            "riskFreeRate": risk_free_rate,
            "dividendYield": dividend_yield,
            "atmIV": atm_iv,
            "daysToExpiry": days_to_expiry,
            "atmCallPrice": atm_call_price,
            "atmPutPrice": atm_put_price,
        })
        body = self._transport.request(
            "POST", "/v1/compute/expected-move", json=payload,
        )
        return ExpectedMoveResponse.model_validate(body)

    def probability(
        self,
        *,
        body: dict[str, Any] | None = None,
        broker: BrokerCredentials | None = None,
    ) -> ProbabilityResponse:
        """Compute risk-neutral probability distribution (operationId ``compute.probability``).

        Low-level escape hatch — pass the full request body as a dict. Prefer
        :meth:`probability_simple` (lognormal Black-Scholes from a strike grid)
        or :meth:`probability_full` (live chain + eSSVI fit + Breeden-Litzenberger,
        BYOK) for typed inputs.

        ``broker`` is required when ``body["mode"] == "full"``.
        """
        headers = dict(broker.headers()) if broker else None
        resp = self._transport.request(
            "POST", "/v1/compute/probability", json=body or {}, headers=headers,
        )
        return ProbabilityResponse.model_validate(resp)

    def probability_simple(
        self,
        *,
        spot_price: float,
        strikes: list[float],
        ivs: list[float],
        time_to_expiry: float,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
    ) -> ProbabilityResponse:
        """Risk-neutral probability via Black-Scholes lognormal (``mode='simple'``).

        Cheap path — closed-form lognormal density from a user-supplied strike
        grid + IV grid. Doesn't require broker credentials. ``strikes`` and
        ``ivs`` must be the same length, 3-500 entries each.
        """
        body = _drop_none({
            "mode": "simple",
            "spotPrice": spot_price,
            "strikes": strikes,
            "ivs": ivs,
            "timeToExpiry": time_to_expiry,
            "riskFreeRate": risk_free_rate,
            "dividendYield": dividend_yield,
        })
        resp = self._transport.request("POST", "/v1/compute/probability", json=body)
        return ProbabilityResponse.model_validate(resp)

    def probability_full(
        self,
        symbol: str,
        *,
        broker: BrokerCredentials,
        expiration: str | None = None,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
    ) -> ProbabilityResponse:
        """Risk-neutral probability via live chain + eSSVI fit (``mode='full'``).

        Expensive path — fetches the live chain via your broker credentials,
        fits the eSSVI surface, and applies Breeden-Litzenberger to recover
        the risk-neutral density. Requires ``broker`` for BYOK.
        """
        if not symbol:
            raise ValueError("symbol is required")
        body = _drop_none({
            "mode": "full",
            "symbol": symbol,
            "expiration": expiration,
            "riskFreeRate": risk_free_rate,
            "dividendYield": dividend_yield,
        })
        headers = dict(broker.headers())
        resp = self._transport.request(
            "POST", "/v1/compute/probability", json=body, headers=headers,
        )
        return ProbabilityResponse.model_validate(resp)

    def calibrate(
        self,
        symbol: str,
        *,
        model: str,
        broker: BrokerCredentials,
        expiration: str | None = None,
        model_params: dict[str, Any] | None = None,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
    ) -> Calibration:
        """Calibrate a model against live broker chain data (operationId ``compute.calibrate``).

        Returns a :class:`Calibration` domain object that wraps the fitted
        ``params``. Subsequent ``cal.price()`` / ``cal.greeks()`` calls use
        ``modelParams=params`` for durable reuse — the 30-second-only
        ``calibrationId`` is intentionally not surfaced.

        Args:
            symbol: Underlying ticker (e.g. ``"SPY"``).
            model: One of ``"heston"``, ``"sabr"``, ``"vg"``, ``"jd"``, ``"localvol"``.
            broker: BYOK credentials. The platform never persists broker tokens —
                they live only on the inbound request.
            expiration: Optional ``YYYY-MM-DD`` expiration. Omit to let the
                server pick the nearest monthly.
            model_params: Optional model-specific calibration knobs (e.g.
                ``{"accuracyMode": "balanced"}`` for Heston).
            risk_free_rate: Optional risk-free rate assumption used during
                calibration. Server default is ``0.05`` when omitted.
            dividend_yield: Optional continuous dividend-yield assumption used
                during calibration. Server default is ``0`` when omitted.

        Returns:
            A :class:`Calibration` already bound to this client. For Heston
            calibrations the ``Calibration`` also carries ``fit_diagnostics``
            (per-moneyness-bucket residual RMSE + worst-fitting option) when
            the server emits it; for other models that field is ``None``.

        Raises:
            ValueError: ``symbol`` or ``model`` is empty.
            AuthenticationError / PermissionDeniedError: API key or scope
                problem.
            CalibrationQuotaError: tier-level calibration budget exhausted —
                inspect ``e.resets_at`` for retry timing.
            ValidationError: malformed inputs (bad model name, bad expiration).
        """
        if not symbol:
            raise ValueError("symbol is required")
        if not model:
            raise ValueError("model is required")
        payload = _drop_none({
            "model": model, "symbol": symbol,
            "expiration": expiration, "modelParams": model_params,
            "riskFreeRate": risk_free_rate,
            "dividendYield": dividend_yield,
        })
        headers = dict(broker.headers())
        resp = self._transport.request(
            "POST", "/v1/compute/calibrate", json=payload, headers=headers,
        )
        return Calibration(
            model=resp.get("model", model),
            symbol=resp.get("symbol", symbol),
            params=resp.get("params", {}),
            expiration=resp.get("expiration") or expiration,
            fit_error=resp.get("fitError"),
            fit_diagnostics=resp.get("fitDiagnostics"),
            calibration_time_ms=resp.get("calibrationTimeMs"),
            provider=resp.get("provider"),
            client=self,
        )

    # ════════════════════════════════════════════════════════════════════
    # Data — regime
    # ════════════════════════════════════════════════════════════════════

    def regime_current(self) -> RegimeResponse:
        """Latest market-wide regime (operationId ``data.regime.current``)."""
        body = self._transport.request("GET", "/v1/data/regime/current")
        return RegimeResponse.model_validate(body)

    def regime(self, symbol: str, *, days: int | None = None) -> dict[str, Any]:
        """Per-symbol regime history (operationId ``data.regime.bySymbol``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"days": days})
        body = self._transport.request(
            "GET", f"/v1/data/regime/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def regime_fits(self, symbol: str, *, days: int | None = None) -> dict[str, Any]:
        """Per-symbol regime model fits (operationId ``data.regime.fits``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"days": days})
        body = self._transport.request(
            "GET", f"/v1/data/regime/fits/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def regime_intraday(self, symbol: str, *, limit: int | None = None) -> dict[str, Any]:
        """Intraday regime fingerprints (operationId ``data.regime.intraday``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"limit": limit})
        body = self._transport.request(
            "GET", f"/v1/data/regime/intraday/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    # ════════════════════════════════════════════════════════════════════
    # Data — snapshot + metrics
    # ════════════════════════════════════════════════════════════════════

    def snapshot_market(self) -> dict[str, Any]:
        """Market-wide options snapshot (operationId ``data.snapshot.market``).

        Untyped — the server returns a free-form dict here. Treat as raw payload.
        """
        body = self._transport.request("GET", "/v1/data/snapshot/market")
        return _ensure_dict(body)

    def snapshot(self, symbol: str) -> SnapshotResponse:
        """Latest EOD options snapshot for a symbol (operationId ``data.snapshot.bySymbol``)."""
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request("GET", f"/v1/data/snapshot/{_path_param(symbol)}")
        return SnapshotResponse.model_validate(body)

    def metrics_batch(self, symbols: list[str]) -> MetricsBatchResponse:
        """Latest metrics for multiple symbols (operationId ``data.metrics.batch``).

        ``symbols`` is a list of tickers. The server accepts at most 50 symbols
        per request; the SDK chunks larger lists automatically and merges the
        returned rows into one ``MetricsBatchResponse``.
        """
        if not symbols:
            raise ValueError("symbols list is required")
        rows: list[Any] = []
        total = 0
        for i in range(0, len(symbols), MAX_METRICS_BATCH_SYMBOLS):
            chunk = symbols[i:i + MAX_METRICS_BATCH_SYMBOLS]
            body = self._transport.request(
                "GET", "/v1/data/metrics/batch", params={"symbols": ",".join(chunk)},
            )
            parsed = MetricsBatchResponse.model_validate(body)
            total += int(parsed.count or 0)
            rows.extend(parsed.data or [])
        return MetricsBatchResponse.model_validate({"count": total, "data": rows})

    def iter_metrics(
        self,
        symbols: list[str],
        *,
        batch_size: int = 50,
    ) -> Iterator[MetricsResponse]:
        """Stream per-symbol metrics from /v1/data/metrics/batch in chunks.

        Use this rather than looping single-symbol :meth:`metrics` calls — the
        server amortizes the lookup across the batch and you stay well under
        the data rate-limit bucket. Yields :class:`MetricsResponse` items as
        they arrive, batch by batch.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")
        effective_batch_size = min(batch_size, MAX_METRICS_BATCH_SYMBOLS)
        for i in range(0, len(symbols), effective_batch_size):
            chunk = symbols[i:i + effective_batch_size]
            if not chunk:
                continue
            yield from self.metrics_batch(chunk).data or []

    def metrics(self, symbol: str) -> MetricsResponse:
        """Latest metrics for a single symbol (operationId ``data.metrics.bySymbol``)."""
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request("GET", f"/v1/data/metrics/{_path_param(symbol)}")
        return MetricsResponse.model_validate(body)

    # ════════════════════════════════════════════════════════════════════
    # Data — analytics
    # ════════════════════════════════════════════════════════════════════

    def market_trends(
        self,
        *,
        metric: str | None = None,
        direction: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Top movers across cached metrics (operationId ``data.marketTrends``)."""
        params = _drop_none({"metric": metric, "direction": direction, "limit": limit})
        body = self._transport.request(
            "GET", "/v1/data/market-trends", params=params or None,
        )
        return _ensure_dict(body)

    def iv_surface(self, symbol: str, *, date: str | None = None) -> IVSurfaceResponse:
        """Per-symbol implied-vol surface (operationId ``data.ivSurface``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"date": date})
        body = self._transport.request(
            "GET", f"/v1/data/iv-surface/{_path_param(symbol)}", params=params or None,
        )
        return IVSurfaceResponse.model_validate(body)

    def exposure_eod(self, symbol: str, *, date: str | None = None) -> dict[str, Any]:
        """End-of-day dealer-positioning levels for a symbol (operationId
        ``data.exposure.bySymbol``).

        A compact set of exposure levels computed over a single 0-60 DTE universe
        (so every field agrees): ``gammaMagnet``, ``gammaFlip``, ``callWall``,
        ``putWall``, ``dealerRegime``, net GEX/DEX, the 30-day expected move, and
        the top contributing strikes. One row per (symbol, date) — the symbol-keyed
        EOD counterpart to :meth:`exposure`, which computes from a caller-supplied
        live chain.

        Args:
            symbol: Underlying ticker (e.g. ``"TSLA"``).
            date: Optional ``YYYY-MM-DD`` session; defaults to the latest close.

        Returns:
            The exposure payload as a ``dict`` (see the ``EodExposureResponse``
            schema in the OpenAPI spec). ``gammaMagnet`` / ``gammaFlip`` /
            ``callWall`` / ``putWall`` may be ``None`` for thinly-traded names;
            ``netGex`` / ``netDex`` units are spelled out in the ``units`` block.

        Raises:
            ValueError: empty ``symbol``.
            NotFoundError: no usable EOD option data for the symbol/date.

        >>> levels = client.exposure_eod("TSLA")
        >>> levels["gammaFlip"], levels["dealerRegime"]
        """
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"date": date})
        body = self._transport.request(
            "GET", f"/v1/data/exposure/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def greeks_history(self, symbol: str, *, days: int | None = None) -> dict[str, Any]:
        """Historical Greeks-by-strike (operationId ``data.greeksHistory``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"days": days})
        body = self._transport.request(
            "GET", f"/v1/data/greeks-history/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def scanner_ranked(
        self,
        *,
        category: str | None = None,
        index: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Pre-ranked scanner results (operationId ``data.scanner.ranked``)."""
        params = _drop_none({"category": category, "index": index, "limit": limit})
        body = self._transport.request(
            "GET", "/v1/data/scanner/ranked", params=params or None,
        )
        return _ensure_dict(body)

    # ════════════════════════════════════════════════════════════════════
    # Data — SEC / FINRA market structure
    # ════════════════════════════════════════════════════════════════════

    def fail_to_deliver(self, symbol: str, *, limit: int | None = None) -> dict[str, Any]:
        """SEC failure-to-deliver records + threshold-list flags.

        operationId ``data.failToDeliver``. Untyped — returns a free-form
        dict per the spec.
        """
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"limit": limit})
        body = self._transport.request(
            "GET", f"/v1/data/fail-to-deliver/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def short_volume(self, symbol: str, *, limit: int | None = None) -> dict[str, Any]:
        """FINRA short-volume history (operationId ``data.shortVolume``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"limit": limit})
        body = self._transport.request(
            "GET", f"/v1/data/short-volume/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def market_structure_ats(self, symbol: str, *, limit: int | None = None) -> dict[str, Any]:
        """Weekly ATS volume per symbol (operationId ``data.marketStructure.ats``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"limit": limit})
        body = self._transport.request(
            "GET", f"/v1/data/market-structure/ats/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def market_structure_otc(self, symbol: str, *, limit: int | None = None) -> dict[str, Any]:
        """Weekly OTC volume per symbol (operationId ``data.marketStructure.otc``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"limit": limit})
        body = self._transport.request(
            "GET", f"/v1/data/market-structure/otc/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def market_structure_ats_firms(
        self,
        symbol: str,
        *,
        week_ending: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """ATS firm-level breakdown (operationId ``data.marketStructure.atsFirms``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"week_ending": week_ending, "limit": limit})
        body = self._transport.request(
            "GET", f"/v1/data/market-structure/ats/{_path_param(symbol)}/firms",
            params=params or None,
        )
        return _ensure_dict(body)

    def market_structure_otc_firms(
        self,
        symbol: str,
        *,
        week_ending: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """OTC firm-level breakdown (operationId ``data.marketStructure.otcFirms``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"week_ending": week_ending, "limit": limit})
        body = self._transport.request(
            "GET", f"/v1/data/market-structure/otc/{_path_param(symbol)}/firms",
            params=params or None,
        )
        return _ensure_dict(body)

    def market_structure_blocks(
        self,
        *,
        month: str | None = None,
        mpid: str | None = None,
        summary_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Monthly block-trade summaries (operationId ``data.marketStructure.blocks``)."""
        params = _drop_none({
            "month": month, "mpid": mpid,
            "summary_type": summary_type, "limit": limit,
        })
        body = self._transport.request(
            "GET", "/v1/data/market-structure/blocks", params=params or None,
        )
        return _ensure_dict(body)

    def market_structure_blocks_by_dealer(
        self,
        mpid: str,
        *,
        summary_type: str | None = None,
        months: int | None = None,
    ) -> dict[str, Any]:
        """Per-dealer block-trade history (operationId ``data.marketStructure.blocksByDealer``)."""
        if not mpid:
            raise ValueError("mpid is required")
        params = _drop_none({"summary_type": summary_type, "months": months})
        body = self._transport.request(
            "GET", f"/v1/data/market-structure/blocks/dealer/{_path_param(mpid)}",
            params=params or None,
        )
        return _ensure_dict(body)

    def threshold_history(self, symbol: str, *, dates: str) -> dict[str, Any]:
        """Threshold-list membership history (operationId ``data.thresholdHistory``).

        ``dates`` is a comma-separated list of ISO dates the server queries.
        Untyped — returns a free-form dict per the spec.
        """
        if not symbol:
            raise ValueError("symbol is required")
        if not dates:
            raise ValueError("dates is required")
        body = self._transport.request(
            "GET", f"/v1/data/threshold-history/{_path_param(symbol)}",
            params={"dates": dates},
        )
        return _ensure_dict(body)

    # ════════════════════════════════════════════════════════════════════
    # Data — calendars
    # ════════════════════════════════════════════════════════════════════

    def economic_calendar(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
        country: str | None = None,
    ) -> dict[str, Any]:
        """Macro economic-calendar events (operationId ``data.economicCalendar``).

        ``from_date`` / ``to_date`` map to the server's ``from`` / ``to`` query params
        (renamed in Python because ``from`` is a keyword).
        """
        params = _drop_none({"from": from_date, "to": to_date, "country": country})
        body = self._transport.request(
            "GET", "/v1/data/economic-calendar", params=params or None,
        )
        return _ensure_dict(body)

    def ipo_calendar(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        """Upcoming IPOs (operationId ``data.ipoCalendar``)."""
        params = _drop_none({"from": from_date, "to": to_date})
        body = self._transport.request(
            "GET", "/v1/data/ipo-calendar", params=params or None,
        )
        return _ensure_dict(body)

    def dividend_calendar(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        """Upcoming dividend ex-dates (operationId ``data.dividendCalendar``)."""
        params = _drop_none({"from": from_date, "to": to_date})
        body = self._transport.request(
            "GET", "/v1/data/dividend-calendar", params=params or None,
        )
        return _ensure_dict(body)

    def split_calendar(
        self,
        *,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict[str, Any]:
        """Upcoming stock splits (operationId ``data.splitCalendar``)."""
        params = _drop_none({"from": from_date, "to": to_date})
        body = self._transport.request(
            "GET", "/v1/data/split-calendar", params=params or None,
        )
        return _ensure_dict(body)

    # ════════════════════════════════════════════════════════════════════
    # Data — corporate actions / fundamentals
    # ════════════════════════════════════════════════════════════════════

    def dividends(self, symbol: str) -> dict[str, Any]:
        """Dividend history for a symbol (operationId ``data.dividends``)."""
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request("GET", f"/v1/data/dividends/{_path_param(symbol)}")
        return _ensure_dict(body)

    def stock_splits(self, symbol: str) -> dict[str, Any]:
        """Split history for a symbol (operationId ``data.stockSplits``)."""
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request("GET", f"/v1/data/stock-splits/{_path_param(symbol)}")
        return _ensure_dict(body)

    def company_profile(self, symbol: str) -> dict[str, Any]:
        """Vendor-passthrough company profile (operationId ``data.companyProfile``).

        Untyped — vendor data shape varies per provider.
        """
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request(
            "GET", f"/v1/data/company-profile/{_path_param(symbol)}",
        )
        return _ensure_dict(body)

    def fundamentals(self, symbol: str) -> dict[str, Any]:
        """Financial statements (operationId ``data.fundamentals``).

        Untyped — vendor data shape varies per provider.
        """
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request("GET", f"/v1/data/fundamentals/{_path_param(symbol)}")
        return _ensure_dict(body)

    def earnings(
        self,
        symbol: str,
        *,
        include_options_analytics: bool | None = None,
    ) -> dict[str, Any]:
        """Earnings history + optional options analytics (operationId ``data.earnings``).

        Untyped — passthrough of vendor + on-the-fly analytics blob.
        """
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"includeOptionsAnalytics": include_options_analytics})
        body = self._transport.request(
            "GET", f"/v1/data/earnings/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def analysts(self, symbol: str) -> dict[str, Any]:
        """Analyst ratings + price targets (operationId ``data.analysts``).

        Untyped — vendor data shape varies per provider.
        """
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request("GET", f"/v1/data/analysts/{_path_param(symbol)}")
        return _ensure_dict(body)

    def insiders(self, symbol: str) -> dict[str, Any]:
        """Insider trading filings (operationId ``data.insiders``).

        Untyped — vendor data shape varies per provider.
        """
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request("GET", f"/v1/data/insiders/{_path_param(symbol)}")
        return _ensure_dict(body)

    def company_data(self, symbol: str) -> dict[str, Any]:
        """Extended company metadata (operationId ``data.companyData``).

        Untyped — vendor data shape varies per provider.
        """
        if not symbol:
            raise ValueError("symbol is required")
        body = self._transport.request(
            "GET", f"/v1/data/company-data/{_path_param(symbol)}",
        )
        return _ensure_dict(body)

    def news(
        self,
        symbol: str,
        *,
        limit: int | None = None,
        page: int | None = None,
    ) -> dict[str, Any]:
        """Stock news for a symbol (operationId ``data.news``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"limit": limit, "page": page})
        body = self._transport.request(
            "GET", f"/v1/data/news/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def history(
        self,
        symbol: str,
        *,
        days: int | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> HistoryResponse:
        """Daily OHLC + scanner ticker history (operationId ``data.history``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"days": days, "start": start, "end": end})
        body = self._transport.request(
            "GET", f"/v1/data/history/{_path_param(symbol)}", params=params or None,
        )
        return HistoryResponse.model_validate(body)

    # ════════════════════════════════════════════════════════════════════
    # Data — macro / bonds
    # ════════════════════════════════════════════════════════════════════

    def fred(self, series_id: str, *, days: int | None = None) -> dict[str, Any]:
        """FRED macro series (operationId ``data.fred``).

        Untyped — passthrough of FRED observation list.
        """
        if not series_id:
            raise ValueError("series_id is required")
        params = _drop_none({"days": days})
        body = self._transport.request(
            "GET", f"/v1/data/fred/{_path_param(series_id)}", params=params or None,
        )
        return _ensure_dict(body)

    def treasury_auctions(
        self,
        *,
        days: int | None = None,
        type: str | None = None,
    ) -> dict[str, Any]:
        """U.S. Treasury auction calendar (operationId ``data.treasury.auctions``)."""
        params = _drop_none({"days": days, "type": type})
        body = self._transport.request(
            "GET", "/v1/data/treasury/auctions", params=params or None,
        )
        return _ensure_dict(body)

    def bond_etf(self, symbol: str, *, limit: int | None = None) -> dict[str, Any]:
        """Bond ETF price/yield history (operationId ``data.bonds.etf``)."""
        if not symbol:
            raise ValueError("symbol is required")
        params = _drop_none({"limit": limit})
        body = self._transport.request(
            "GET", f"/v1/data/bonds/etf/{_path_param(symbol)}", params=params or None,
        )
        return _ensure_dict(body)

    def trace_aggregates(self, *, days: int | None = None) -> dict[str, Any]:
        """TRACE corporate-bond trading aggregates (operationId ``data.bonds.traceAggregates``)."""
        params = _drop_none({"days": days})
        body = self._transport.request(
            "GET", "/v1/data/bonds/trace/aggregates", params=params or None,
        )
        return _ensure_dict(body)

    def trace_sentiment(self, *, days: int | None = None) -> dict[str, Any]:
        """TRACE bond-market sentiment (operationId ``data.bonds.traceSentiment``)."""
        params = _drop_none({"days": days})
        body = self._transport.request(
            "GET", "/v1/data/bonds/trace/sentiment", params=params or None,
        )
        return _ensure_dict(body)

    # ════════════════════════════════════════════════════════════════════
    # Lifecycle
    # ════════════════════════════════════════════════════════════════════

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._transport.close()

    def __enter__(self) -> OASClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
