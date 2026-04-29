"""Options Analysis Suite Python SDK.

Public surface::

    from oas import OASClient, TradierCredentials
    from oas.errors import RateLimitError, NotFoundError

    with OASClient(api_key="oas_live_...") as client:
        snap = client.snapshot("SPY")
"""

from oas.calibration import Calibration
from oas.client import OASClient
from oas.credentials import (
    BrokerCredentials,
    TastytradeCredentials,
    TradierCredentials,
)
from oas.errors import (
    AuthenticationError,
    CalibrationQuotaError,
    ConcurrencyLimitError,
    NotFoundError,
    OASError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    ValidationError,
)

__version__ = "0.1.0a5"

__all__ = [
    "OASClient",
    "Calibration",
    "BrokerCredentials",
    "TradierCredentials",
    "TastytradeCredentials",
    "OASError",
    "AuthenticationError",
    "ValidationError",
    "PermissionDeniedError",
    "NotFoundError",
    "RateLimitError",
    "CalibrationQuotaError",
    "ConcurrencyLimitError",
    "ServerError",
    "__version__",
]
