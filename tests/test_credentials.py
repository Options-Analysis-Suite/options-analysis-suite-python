"""Unit tests for the BYOK broker credential header contracts.

These pin the exact header set each credential class produces, since the OAS
API dispatches on ``X-Broker-Type`` and reads broker-specific header names.
"""

from __future__ import annotations

from oas import SchwabCredentials, TastytradeCredentials, TradierCredentials


def test_tradier_headers() -> None:
    assert TradierCredentials(token="tk").headers() == {
        "X-Broker-Type": "tradier",
        "X-Tradier-Key": "tk",
    }


def test_tastytrade_headers() -> None:
    assert TastytradeCredentials(refresh_token="rt", client_secret="cs").headers() == {
        "X-Broker-Type": "tastytrade",
        "X-Tastytrade-Refresh-Token": "rt",
        "X-Tastytrade-Client-Secret": "cs",
    }


def test_schwab_headers() -> None:
    assert SchwabCredentials(
        refresh_token="rt", client_id="ci", client_secret="cs"
    ).headers() == {
        "X-Broker-Type": "schwab",
        "X-Schwab-Refresh-Token": "rt",
        "X-Schwab-Client-Id": "ci",
        "X-Schwab-Client-Secret": "cs",
    }
