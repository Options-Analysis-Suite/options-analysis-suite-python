"""Broker credentials for OAS endpoints that require live chain data (BYOK).

The OAS API does not pay for market data — calibration, full-mode probability,
and streaming endpoints require you to supply broker credentials via headers.
Construct one of the concrete subclasses, then pass it into the relevant
client method (``OASClient.calibrate(broker=TradierCredentials(token=...))``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerCredentials:
    """Abstract base for broker credentials.

    Subclasses must override :meth:`headers` to produce the exact header set
    the OAS API expects for that broker.
    """

    def headers(self) -> Mapping[str, str]:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass(frozen=True)
class TradierCredentials(BrokerCredentials):
    """Tradier API token. Free at https://tradier.com/products/market-data-api."""

    token: str

    def headers(self) -> Mapping[str, str]:
        return {
            "X-Broker-Type": "tradier",
            "X-Tradier-Key": self.token,
        }


@dataclass(frozen=True)
class TastytradeCredentials(BrokerCredentials):
    """Tastytrade OAuth credentials.

    Both fields are required by the OAS API for Tastytrade BYOK; ``refresh_token``
    is the long-lived OAuth refresh token, ``client_secret`` is the OAuth client
    secret bound to your Tastytrade app registration.
    """

    refresh_token: str
    client_secret: str

    def headers(self) -> Mapping[str, str]:
        return {
            "X-Broker-Type": "tastytrade",
            "X-Tastytrade-Refresh-Token": self.refresh_token,
            "X-Tastytrade-Client-Secret": self.client_secret,
        }
