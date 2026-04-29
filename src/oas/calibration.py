"""``Calibration`` domain object — durable wrapper around a ``/v1/compute/calibrate``
result that exposes ``.price()``, ``.greeks()``, ``.save()``, and ``.from_json()``.

The OAS API returns a 30-second-only ``calibrationId`` plus the actual fitted
``params`` dict when you call ``/v1/compute/calibrate``. The ``Calibration``
class persists the fitted ``params`` (durable) and forwards them as
``modelParams`` on subsequent ``/price`` and ``/greeks`` calls — so users
never have to think about the calibrationId TTL.

Typical flow::

    with OASClient(api_key="...") as client:
        cal = client.calibrate("SPY", model="heston", broker=TradierCredentials(token="..."))
        cal.save("spy_heston.json")

        price = cal.price(is_call=True, K=650, expiry="2026-06-19")
        greeks = cal.greeks(is_call=True, K=650, expiry="2026-06-19")

    # Hours later, in another process:
    with OASClient(api_key="...") as client:
        cal = Calibration.from_json("spy_heston.json", client=client)
        price = cal.price(is_call=True, K=650, S=655, r=0.05,
                          q=0.012, sigma=0.15, t=0.25)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from oas._generated.models import GreeksResponse, PriceResponse
    from oas.client import OASClient


_FILE_FORMAT_VERSION = 1


class Calibration:
    """A persisted calibration result.

    Holds the fitted ``params`` dict for one of the calibratable models
    (``heston``, ``sabr``, ``vg``, ``jd``, ``localvol``). Use
    :meth:`save` / :meth:`from_json` to round-trip via disk; use
    :meth:`price` / :meth:`greeks` to evaluate the calibrated model
    without re-running calibration.
    """

    def __init__(
        self,
        *,
        model: str,
        symbol: str,
        params: dict[str, Any],
        expiration: str | None = None,
        fit_error: dict[str, Any] | None = None,
        calibration_time_ms: float | None = None,
        provider: str | None = None,
        client: OASClient | None = None,
    ) -> None:
        if not model:
            raise ValueError("model is required")
        if not symbol:
            raise ValueError("symbol is required")
        if not isinstance(params, dict):
            raise TypeError("params must be a dict")
        self.model = model
        self.symbol = symbol
        self.params = params
        self.expiration = expiration
        self.fit_error = fit_error
        self.calibration_time_ms = calibration_time_ms
        self.provider = provider
        # Bound client lets cal.price() / cal.greeks() work without re-passing it.
        # Calibration loaded via from_json() has _client=None until bind() is called.
        self._client = client

    # ── Convenience evaluators ──────────────────────────────────────────

    def price(
        self,
        *,
        is_call: bool,
        K: float,
        S: float | None = None,
        r: float | None = None,
        q: float | None = None,
        sigma: float | None = None,
        t: float | None = None,
        symbol: str | None = None,
        expiry: str | None = None,
        expiration: str | None = None,
        resolve: dict[str, Any] | None = None,
    ) -> PriceResponse:
        """Price an option using this calibration's fitted params.

        Forwards to ``/v1/compute/price`` with ``model=self.model`` and
        ``modelParams=self.params``. Other inputs (S, K, r, q, sigma, t)
        can be passed explicitly or auto-filled via ticker resolution.

        Symbol forwarding is suppressed only when the caller supplies
        ``S``, ``r``, ``q``, ``sigma``, **and numeric ``t``** — that's the
        compute-only fast path. Passing tenor as ``expiry``/``expiration``
        (string) instead of ``t`` still forwards :attr:`symbol` so the
        server's resolver can convert the date to ``t`` (the resolver runs
        only when symbol is present, so omitting it with expiry-only
        results in a 400 on missing tenor). Pass ``symbol=`` explicitly
        to force ticker resolution regardless.
        """
        client = self._require_client()
        return client.price(
            model=self.model,
            is_call=is_call,
            K=K,
            S=S,
            r=r,
            q=q,
            sigma=sigma,
            t=t,
            symbol=self._resolve_symbol(symbol, S, r, q, sigma, t, expiry, expiration),
            expiry=expiry,
            expiration=expiration,
            resolve=resolve,
            model_params=self.params,
        )

    def greeks(
        self,
        *,
        is_call: bool,
        K: float,
        S: float | None = None,
        r: float | None = None,
        q: float | None = None,
        sigma: float | None = None,
        t: float | None = None,
        symbol: str | None = None,
        expiry: str | None = None,
        expiration: str | None = None,
        resolve: dict[str, Any] | None = None,
        include_insight: bool | None = None,
    ) -> GreeksResponse:
        """Compute Greeks using this calibration's fitted params.

        Same ticker-resolution rules as :meth:`price`: ``symbol`` is only
        forwarded when explicit numerics are incomplete.
        """
        client = self._require_client()
        return client.greeks(
            model=self.model,
            is_call=is_call,
            K=K,
            S=S,
            r=r,
            q=q,
            sigma=sigma,
            t=t,
            symbol=self._resolve_symbol(symbol, S, r, q, sigma, t, expiry, expiration),
            expiry=expiry,
            expiration=expiration,
            resolve=resolve,
            model_params=self.params,
            include_insight=include_insight,
        )

    def _resolve_symbol(
        self,
        explicit: str | None,
        S: float | None,
        r: float | None,
        q: float | None,
        sigma: float | None,
        t: float | None,
        expiry: str | None,  # noqa: ARG002 — referenced in docstring; intentional API
        expiration: str | None,  # noqa: ARG002 — same
    ) -> str | None:
        """Decide whether to forward a symbol for ticker auto-fill.

        Sending ``symbol`` triggers the server's ticker resolver, which
        requires both ``compute`` AND ``data`` scopes on the API key
        (``data-api/routes/compute.ts:206``). For users with compute-only
        keys, that's a 403. So: only fall back to ``self.symbol`` when the
        caller's numerics are incomplete enough to actually need resolution.

        Tenor handling: ``expiry`` / ``expiration`` strings are converted to
        numeric ``t`` *only* by the resolver (server side). When ``symbol``
        is omitted the resolver doesn't run, and the server rejects missing
        ``t`` (``data-api/routes/compute.ts:283``). So a fully-numeric
        compute-only call must supply ``t`` directly; passing only
        ``expiry``/``expiration`` requires symbol forwarding so the resolver
        can do the date math. This is the SDK-side workaround for that
        server contract; an upstream fix would convert expiry→t before
        the needs-resolution branch.
        """
        if explicit:
            return explicit
        has_full_numerics = (
            S is not None
            and r is not None
            and q is not None
            and sigma is not None
            and t is not None  # expiry/expiration alone is NOT sufficient — see docstring
        )
        return None if has_full_numerics else self.symbol

    # ── Persistence ──────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON. Excludes the bound client."""
        return {
            "_format_version": _FILE_FORMAT_VERSION,
            "model": self.model,
            "symbol": self.symbol,
            "params": self.params,
            "expiration": self.expiration,
            "fitError": self.fit_error,
            "calibrationTimeMs": self.calibration_time_ms,
            "provider": self.provider,
        }

    def save(self, path: str | Path) -> None:
        """Write the calibration to a JSON file on disk."""
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, client: OASClient | None = None) -> Calibration:
        """Reconstruct a Calibration from a previously-saved dict.

        :param client: bind this client so :meth:`price` / :meth:`greeks` work
            on the loaded calibration. Use :meth:`bind` later if not available
            at load time.
        """
        version = data.get("_format_version", _FILE_FORMAT_VERSION)
        if version > _FILE_FORMAT_VERSION:
            raise ValueError(
                f"Calibration file format version {version} is newer than this "
                f"SDK supports ({_FILE_FORMAT_VERSION}). Upgrade the SDK."
            )
        return cls(
            model=data["model"],
            symbol=data["symbol"],
            params=data["params"],
            expiration=data.get("expiration"),
            fit_error=data.get("fitError"),
            calibration_time_ms=data.get("calibrationTimeMs"),
            provider=data.get("provider"),
            client=client,
        )

    @classmethod
    def from_json(cls, path: str | Path, *, client: OASClient | None = None) -> Calibration:
        """Load a calibration from a JSON file written by :meth:`save`."""
        return cls.from_dict(json.loads(Path(path).read_text()), client=client)

    def bind(self, client: OASClient) -> Calibration:
        """Attach an OASClient to this calibration. Returns ``self`` for chaining."""
        self._client = client
        return self

    # ── Internals ────────────────────────────────────────────────────────

    def _require_client(self) -> OASClient:
        if self._client is None:
            raise RuntimeError(
                "This Calibration is not bound to an OASClient. Either pass "
                "client= to from_json/from_dict or call cal.bind(client) first."
            )
        return self._client

    def __repr__(self) -> str:
        return (
            f"Calibration(model={self.model!r}, symbol={self.symbol!r}, "
            f"expiration={self.expiration!r}, params=<{len(self.params)} keys>)"
        )
