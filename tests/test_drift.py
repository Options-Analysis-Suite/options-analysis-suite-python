"""SDK ↔ OpenAPI drift tests.

The core check is that every operationId served by ``/openapi.json`` (minus
those tagged for non-typed-client surfaces) has a registered SDK method in
``oas._manifest.ENDPOINTS``. We also check the inverse: nothing in the
manifest claims to cover a path that no longer exists in the spec.

Run offline by setting ``OAS_OPENAPI_PATH`` to a local spec file; otherwise
the ``openapi_spec`` fixture fetches deployed prod.

Note: until ``OASClient`` exposes every operationId, the strict-equality
test below is marked ``xfail(strict=False)``. Step 5 of the SDK build (filling
in the remaining client methods) will make it pass naturally; once that
happens, drop the ``xfail`` decorator.
"""

from __future__ import annotations

from typing import Any

from oas._manifest import (
    ENDPOINTS,
    EXPECTED_MISSING_OPERATION_IDS,
    SDK_IGNORED_OPERATION_IDS,
)
from oas.client import OASClient

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def _spec_operation_ids(spec: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for _path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in HTTP_METHODS:
                continue
            opid = op.get("operationId") if isinstance(op, dict) else None
            if opid:
                out.add(opid)
    return out


def test_sdk_manifest_only_references_real_operation_ids(openapi_spec: dict[str, Any]) -> None:
    """Every operationId we register must actually exist in the spec."""
    spec_ids = _spec_operation_ids(openapi_spec)
    sdk_ids = set(ENDPOINTS.keys())
    extra_in_sdk = sdk_ids - spec_ids
    assert not extra_in_sdk, (
        f"SDK manifest references operationIds that aren't in /openapi.json: "
        f"{sorted(extra_in_sdk)}"
    )


def test_sdk_methods_exist_on_client() -> None:
    """Every Endpoint.sdk_method must resolve to an actual OASClient attribute."""
    for op_id, endpoint in ENDPOINTS.items():
        assert hasattr(OASClient, endpoint.sdk_method), (
            f"OASClient.{endpoint.sdk_method} is missing (registered for {op_id})"
        )


def test_sdk_paths_match_spec_paths(openapi_spec: dict[str, Any]) -> None:
    """Each registered Endpoint.path must be present in the served spec."""
    spec_paths = set(openapi_spec.get("paths", {}).keys())
    for op_id, ep in ENDPOINTS.items():
        assert ep.path in spec_paths, (
            f"SDK endpoint {op_id} claims path {ep.path} but /openapi.json does not list it"
        )


def test_sdk_covers_every_typed_operation_id(openapi_spec: dict[str, Any]) -> None:
    """Strict drift gate: ENDPOINTS must equal (spec ops − ignore − expected-missing).

    Two failure modes this catches:

    1. **Surprise spec addition**: a new operationId shipped that's neither
       wired up in ENDPOINTS nor allowlisted in EXPECTED_MISSING_OPERATION_IDS.
    2. **Stale allowlist**: someone wired up an OASClient method but forgot
       to remove the operationId from EXPECTED_MISSING_OPERATION_IDS.

    As step 5 fills in OASClient methods, drain the corresponding entries from
    EXPECTED_MISSING_OPERATION_IDS in oas._manifest. When that set is empty,
    the SDK has full coverage of the typed operation surface.
    """
    spec_ids = _spec_operation_ids(openapi_spec)
    sdk_ids = set(ENDPOINTS.keys())
    expected = spec_ids - SDK_IGNORED_OPERATION_IDS - EXPECTED_MISSING_OPERATION_IDS

    missing = expected - sdk_ids
    assert not missing, (
        f"Spec has typed operationIds with no OASClient method and no "
        f"EXPECTED_MISSING entry: {sorted(missing)}. Either add the SDK method "
        f"or allowlist it in oas._manifest.EXPECTED_MISSING_OPERATION_IDS."
    )

    stale_allowlist = sdk_ids & EXPECTED_MISSING_OPERATION_IDS
    assert not stale_allowlist, (
        f"OASClient methods exist but are still in EXPECTED_MISSING_OPERATION_IDS: "
        f"{sorted(stale_allowlist)} — drop them from the allowlist now that "
        f"they're wired up."
    )

    expected_in_spec = EXPECTED_MISSING_OPERATION_IDS - SDK_IGNORED_OPERATION_IDS
    stale_spec = expected_in_spec - spec_ids
    assert not stale_spec, (
        f"EXPECTED_MISSING_OPERATION_IDS references operationIds that aren't "
        f"in /openapi.json anymore: {sorted(stale_spec)}"
    )
