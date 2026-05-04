"""Re-derive the generated Pydantic models from the OpenAPI spec.

Pulls ``/openapi.json`` from the deployed data-api (or a local file via
``OAS_OPENAPI_PATH``) and regenerates ``src/oas/_generated/models.py`` via
``datamodel-code-generator``.

After generation we post-process the output to flip every ``extra='forbid'``
to ``extra='ignore'`` so the SDK survives additive server fields without
forcing a release. The OpenAPI spec stays strict for contract enforcement;
the SDK is lenient at parse time.

Usage::

    python scripts/gen_models.py [--input PATH] [--url URL]

Run via ``make gen``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://data.optionsanalysissuite.com/openapi.json"
OUTPUT = Path(__file__).resolve().parent.parent / "src" / "oas" / "_generated" / "models.py"


def fetch_spec(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:
        return r.read()


def _resolve_codegen_bin() -> str:
    """Locate the `datamodel-codegen` binary, preferring the one colocated
    with the running interpreter so `make gen` works in unactivated shells.

    We deliberately do NOT `Path(sys.executable).resolve()` — that follows
    the venv's python symlink back to the base interpreter (e.g.
    `/usr/bin/python3.12`) and computes a `bin/` outside the venv, missing
    the venv-installed `datamodel-codegen`. Using the unresolved parent
    keeps us in `.venv/bin/` (POSIX) or `.venv\\Scripts\\` (Windows).

    We use `shutil.which(..., path=...)` against the interpreter's bin
    directory rather than constructing the path manually so PATHEXT
    handling works on Windows (where the entry point is
    `datamodel-codegen.exe`) and the executable-bit check stays correct
    on POSIX.
    """
    exe_dir = Path(sys.executable).parent
    colocated = shutil.which("datamodel-codegen", path=str(exe_dir))
    if colocated:
        return colocated
    on_path = shutil.which("datamodel-codegen")
    return on_path if on_path else "datamodel-codegen"


def run_codegen(input_path: Path, output_path: Path) -> None:
    """Invoke datamodel-codegen against a local OpenAPI JSON file."""
    codegen_bin = _resolve_codegen_bin()
    if shutil.which(codegen_bin) is None:
        print("error: datamodel-codegen is not available on PATH or in the "
              "active interpreter's bin directory. Run `make install` or "
              "`pip install datamodel-code-generator`.", file=sys.stderr)
        sys.exit(2)
    cmd = [
        codegen_bin,
        "--input", str(input_path),
        "--input-file-type", "openapi",
        "--output", str(output_path),
        "--output-model-type", "pydantic_v2.BaseModel",
        "--target-python-version", "3.10",
    ]
    subprocess.run(cmd, check=True)


def relax_extra_forbid(output_path: Path) -> int:
    """Replace every ``extra='forbid'`` with ``extra='ignore'`` so additive
    server fields don't break older SDK versions. Returns count replaced."""
    src = output_path.read_text()
    new, n = re.subn(r"extra\s*=\s*'forbid'", "extra='ignore'", src)
    if n:
        output_path.write_text(new)
    return n


# Match a `name: <type containing '| None'> = Field(\n        ...,` block where
# ``...`` is `datamodel-codegen`'s "required, no default" sentinel. We promote
# the field to ``= Field(None, …)`` so callers can deserialize older API
# responses that omit the field. The OpenAPI spec stays strict (the field
# remains in ``required``); only the SDK's parse-time stance is loosened.
#
# Why we need this even though the spec is the source of truth: any field that
# is structurally nullable (``T | None``) is one server-side hiccup away from
# being absent entirely (e.g. behind feature flags, or for endpoints that omit
# the field on legacy paths). Generated SDKs that hard-require these fields
# turn a soft contract drift into a parse-time crash for every consumer. The
# 0.1.0a7 release shipped exactly this failure mode for ``ExposureSnapshot
# .absGamma`` until 0.1.0a8 patched it; this regex makes the patch durable
# across regenerations.
_NULLABLE_REQUIRED_FIELD = re.compile(
    r"(\b\w+:\s*[^\n=]*?\|\s*None[^\n=]*?=\s*Field\(\s*\n\s*)\.\.\.,",
    re.MULTILINE,
)


def relax_nullable_required_fields(output_path: Path) -> int:
    """For every ``name: T | None = Field(..., …)`` declaration in the
    generated module, replace the required-sentinel ``...`` with ``None`` so
    the field defaults to ``None`` when omitted from a server response. The
    SDK is intentionally lenient at parse time even where the spec marks the
    field required."""
    src = output_path.read_text()
    new, n = _NULLABLE_REQUIRED_FIELD.subn(r"\1None,", src)
    if n:
        output_path.write_text(new)
    return n


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=os.environ.get("OAS_OPENAPI_URL", DEFAULT_URL),
                   help="URL to fetch OpenAPI spec from (default: deployed prod)")
    p.add_argument("--input", help="Local OpenAPI JSON file (overrides --url)")
    args = p.parse_args()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    if args.input:
        input_path = Path(args.input)
        if not input_path.is_file():
            print(f"error: input file does not exist: {input_path}", file=sys.stderr)
            return 2
        run_codegen(input_path, OUTPUT)
    else:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(fetch_spec(args.url))
            tmp = Path(f.name)
        try:
            run_codegen(tmp, OUTPUT)
        finally:
            tmp.unlink(missing_ok=True)

    relaxed = relax_extra_forbid(OUTPUT)
    nulled = relax_nullable_required_fields(OUTPUT)
    print(f"Generated {OUTPUT}")
    print(f"Relaxed extra='forbid' → 'ignore' on {relaxed} model classes for forward-compat")
    print(f"Defaulted nullable Field(...) → Field(None) on {nulled} fields for forward-compat")
    # The OpenAPI spec uses additionalProperties: false on all tightened response
    # schemas (PriceResponse, GreeksResponse, SnapshotResponse, etc.). If
    # datamodel-codegen ever emits zero `extra='forbid'` annotations for those,
    # something has changed — either the spec went lax or the generator's
    # output format changed. Fail loud rather than silently shipping models
    # that reject additive server fields at parse time.
    if relaxed == 0:
        print(
            "error: relax pass found zero extra='forbid' annotations to rewrite. "
            "This usually means datamodel-code-generator changed its output format "
            "or the OpenAPI spec stopped using additionalProperties: false. Inspect "
            f"{OUTPUT} and update relax_extra_forbid() before publishing.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
