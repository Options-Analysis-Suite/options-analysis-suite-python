"""HTTP transport used by :class:`oas.OASClient`. Internal — not part of the
public API.

Responsibilities:
- Set Authorization + User-Agent headers
- Perform the request via httpx
- Map non-2xx responses to typed :mod:`oas.errors` subclasses
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Any

import httpx

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


def _resolve_version() -> str:
    try:
        return _pkg_version("options-analysis-suite")
    except PackageNotFoundError:
        return "0.0.0+unknown"


_USER_AGENT = f"options-analysis-suite-py/{_resolve_version()}"


class Transport:
    def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": _USER_AGENT,
            },
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        resp = self._client.request(method, path, json=json, params=params, headers=headers)
        if resp.is_success:
            return resp.json()
        self._raise_typed(resp)
        # _raise_typed always raises — this is just to satisfy the type checker.
        raise OASError("unreachable")

    def _raise_typed(self, resp: httpx.Response) -> None:
        try:
            body: dict[str, Any] = resp.json()
            if not isinstance(body, dict):
                body = {}
        except Exception:
            body = {}

        status = resp.status_code
        msg = body.get("error") or body.get("message") or resp.text or f"HTTP {status}"
        code = body.get("code")

        if status == 401:
            raise AuthenticationError(msg, status=status, code=code)
        if status in (400, 422):
            raise ValidationError(msg, status=status, code=code)
        if status == 403:
            raise PermissionDeniedError(
                msg,
                required_scope=body.get("requiredScope") or body.get("scope"),
                status=status,
                code=code,
            )
        if status == 404:
            raise NotFoundError(msg, status=status, code=code)
        if status == 429:
            if code == "CALIBRATION_QUOTA_EXCEEDED":
                raise CalibrationQuotaError(
                    msg, resets_at=body.get("resetsAt"), status=status, code=code
                )
            # CONCURRENCY_LIMIT_EXCEEDED is the calibration-pool variant; the
            # cheap/heavy compute pools emit COMPUTE_CONCURRENCY_LIMIT. Both
            # surface the same {current, max} structured fields.
            if code in ("CONCURRENCY_LIMIT_EXCEEDED", "COMPUTE_CONCURRENCY_LIMIT"):
                raise ConcurrencyLimitError(
                    msg,
                    current=body.get("current"),
                    max=body.get("max"),
                    status=status,
                    code=code,
                )
            ra = resp.headers.get("retry-after")
            retry_after = int(ra) if ra and ra.isdigit() else None
            raise RateLimitError(
                msg,
                retry_after=retry_after,
                bucket=resp.headers.get("X-RateLimit-Bucket"),
                status=status,
                code=code,
            )
        if status >= 500:
            raise ServerError(msg, status=status, code=code)
        raise OASError(msg, status=status, code=code)

    def close(self) -> None:
        self._client.close()
