.PHONY: install gen lint typecheck test test-live build clean

# Lint/typecheck/test targets route through ./.venv/bin/* so they work
# without activating the virtualenv first. `make install` provisions .venv
# via uv. `make build` calls `uv build` directly (no .venv lookup needed).
PY := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy

install:
	uv venv --python 3.12 --allow-existing .venv
	uv sync --locked --all-extras --python $(PY)

# Re-derive Pydantic models from OAS_OPENAPI_PATH when set, otherwise deployed
# OpenAPI. Requires datamodel-codegen.
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
# Also compares deployed operationIds with the repo-derived pinned contract.
test-live:
	$(PYTEST) -m live -v

build:
	uv build

clean:
	rm -rf build dist *.egg-info src/oas.egg-info .pytest_cache .mypy_cache .ruff_cache
