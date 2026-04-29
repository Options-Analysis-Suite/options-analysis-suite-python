.PHONY: install gen lint typecheck test test-live build clean

# Lint/typecheck/test targets route through ./.venv/bin/* so they work
# without activating the virtualenv first. `make install` provisions .venv
# via uv. `make build` calls `uv build` directly (no .venv lookup needed).
PY := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy

install:
	uv venv --python 3.12 .venv
	uv pip install --python .venv -e ".[dev,codegen]"

# Re-derive Pydantic models from the live OpenAPI spec. Requires datamodel-codegen.
gen:
	$(PY) scripts/gen_models.py

lint:
	$(RUFF) check src tests scripts

typecheck:
	$(MYPY)

# Unit + drift tests (no network). Reads tests/fixtures/openapi.snapshot.json by
# default; set OAS_OPENAPI_PATH=- to force a live fetch instead.
test:
	$(PYTEST) -m "not live" -v

# Integration test against the deployed API. Requires OAS_API_KEY in env.
# Also runs the fixture-freshness check that diffs the pinned snapshot against
# the live /openapi.json — refresh tests/fixtures/openapi.snapshot.json if it fails.
test-live:
	$(PYTEST) -m live -v

build:
	uv build

clean:
	rm -rf build dist *.egg-info src/oas.egg-info .pytest_cache .mypy_cache .ruff_cache
