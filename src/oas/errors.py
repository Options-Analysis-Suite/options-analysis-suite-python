"""Typed exceptions raised by the OAS client.

Every error subclass carries the HTTP status, the server-side error code (when
available), and any structured fields the server returned (retry_after,
resets_at, etc.). Catch the specific subclass when you need the structured
data; catch :class:`OASError` for blanket handling.
"""

from __future__ import annotations


class OASError(Exception):
    """Base class for every error the OAS client raises."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class AuthenticationError(OASError):
    """401 — API key missing, malformed, or rejected."""


class ValidationError(OASError):
    """400/422 — request body, query parameters, or resolved inputs failed validation.

    The server typically includes per-field issue details in the response body;
    they aren't surfaced as structured fields here yet. Catch and inspect
    :attr:`OASError.args` for the raw message.
    """


class PermissionDeniedError(OASError):
    """403 — API key authenticated but lacks the required tier or scope.

    The server emits this for two distinct reasons, surfaced via :attr:`code`:

    - ``API_TIER_REQUIRED`` — your tier is missing (free tier hitting a paid endpoint).
    - ``INSUFFICIENT_SCOPE`` — your key authenticated but doesn't carry the
      ``compute`` / ``data`` scope that this endpoint needs. :attr:`required_scope`
      holds the missing scope when present.
    """

    def __init__(
        self,
        message: str,
        *,
        required_scope: str | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code)
        self.required_scope = required_scope


class NotFoundError(OASError):
    """404 — symbol or resource not found in the data warehouse."""


class RateLimitError(OASError):
    """429 — request bucket exceeded.

    :attr:`retry_after` is the recommended wait in seconds, parsed from the
    ``Retry-After`` response header.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: int | None = None,
        bucket: str | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code)
        self.retry_after = retry_after
        self.bucket = bucket


class CalibrationQuotaError(OASError):
    """429 — daily calibration quota exhausted.

    :attr:`resets_at` is the ISO-8601 timestamp at which the quota window
    rolls over, taken from the response body when present.
    """

    def __init__(
        self,
        message: str,
        *,
        resets_at: str | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code)
        self.resets_at = resets_at


class ConcurrencyLimitError(OASError):
    """429 — too many concurrent compute slots in use for your tier.

    :attr:`current` and :attr:`max` describe the tier-level concurrency cap;
    wait for a running request to finish and retry.
    """

    def __init__(
        self,
        message: str,
        *,
        current: int | None = None,
        max: int | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message, status=status, code=code)
        self.current = current
        self.max = max


class ServerError(OASError):
    """5xx — server-side failure. Idempotent reads are typically safe to retry."""
