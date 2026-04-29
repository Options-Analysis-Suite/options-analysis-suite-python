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


def run_codegen(input_path: Path, output_path: Path) -> None:
    """Invoke datamodel-codegen against a local OpenAPI JSON file."""
    cmd = [
        "datamodel-codegen",
        "--input", str(input_path),
        "--input-file-type", "openapi",
        "--output", str(output_path),
        "--output-model-type", "pydantic_v2.BaseModel",
        "--target-python-version", "3.10",
    ]
    if shutil.which("datamodel-codegen") is None:
        print("error: datamodel-codegen is not on PATH. Run `make install` or "
              "`pip install datamodel-code-generator`.", file=sys.stderr)
        sys.exit(2)
    subprocess.run(cmd, check=True)


def relax_extra_forbid(output_path: Path) -> int:
    """Replace every ``extra='forbid'`` with ``extra='ignore'`` so additive
    server fields don't break older SDK versions. Returns count replaced."""
    src = output_path.read_text()
    new, n = re.subn(r"extra\s*=\s*'forbid'", "extra='ignore'", src)
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
    print(f"Generated {OUTPUT}")
    print(f"Relaxed extra='forbid' → 'ignore' on {relaxed} model classes for forward-compat")
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
