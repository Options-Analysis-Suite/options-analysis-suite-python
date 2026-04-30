# Maintaining the SDK

Internal docs for the SDK maintainer. Public-facing usage docs are in
[README.md](README.md). This file is **not** shipped in the wheel/sdist
and **not** rendered on the PyPI project page.

## Development

```bash
# Set up dev env
make install

# Lint / typecheck / test
make lint
make typecheck
make test         # unit + drift, no network. Uses tests/fixtures/openapi.snapshot.json
make test-live    # integration (needs OAS_API_KEY env var). Also re-checks the
                  # pinned spec fixture against the deployed /openapi.json.

# Build distribution
make build

# Regenerate Pydantic models from the live OpenAPI spec
make gen
```

Refresh the pinned spec fixture with:

```bash
curl -s https://data.optionsanalysissuite.com/openapi.json \
  > tests/fixtures/openapi.snapshot.json
```

## Drift gate

The SDK's `_manifest.py` registers every operationId → `OASClient` method
pairing. `tests/test_drift.py` runs four checks against the spec:

1. Every `ENDPOINTS` operationId actually exists in `/openapi.json`
2. Every registered `Endpoint.sdk_method` resolves to a real `OASClient` attr
3. Every registered `Endpoint.path` is a path in the spec
4. **Strict gate**: spec ops − ignored − expected-missing == `ENDPOINTS` keys.
   Catches both unfinished stubs left in the allowlist and surprise spec
   additions.

The `EXPECTED_MISSING_OPERATION_IDS` allowlist is **empty** — the SDK
covers every typed operation. The `live` test suite double-checks that
the pinned `tests/fixtures/openapi.snapshot.json` still matches deployed
prod.

## Updating the SDK when the spec changes

When the upstream OpenAPI spec changes, the SDK reacts as follows:

| Spec change | SDK reaction | Maintainer action |
|---|---|---|
| **New field** on existing schema (e.g., add `vegaWeighted` to `MetricsResponse`) | Old SDK versions silently ignore the unknown field via `extra='ignore'` — users on `0.1.x` don't break. | `make gen` to expose the new field on the response model. Bump version, update CHANGELOG, release. |
| **New endpoint** (new operationId) | `tests/test_drift.py` fails the strict-gate assertion, naming the missing operationId. | Add a method to `src/oas/client.py`, add an entry to `src/oas/_manifest.py`, run `make test` until drift passes, release. |
| **Removed / renamed endpoint** | Drift gate fails the other way — the SDK manifest references an operationId that no longer exists. | Remove the corresponding `client.py` method and `_manifest.py` entry. Bump major if the SDK had shipped that method publicly. |
| **Schema field type change** (e.g., `atmIv: number → string`) | `make gen` regenerates with the new type; `mypy --strict` flags any callers that assumed the old type. | Fix call sites, regen, release. |
| **Spec fixture stale** | `make test-live` fetches the deployed `/openapi.json` and compares against `tests/fixtures/openapi.snapshot.json`. | Refresh the fixture and commit. |

The drift gate is the forcing function — you cannot accidentally ship an
SDK that's out of sync with the deployed API surface.

## Release process

Releases are tag-driven via the `publish.yml` GitHub Actions workflow.
The publish job uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC) — no API tokens are stored anywhere.

**One-time setup (on PyPI):**

1. Visit https://pypi.org/manage/account/publishing/
2. Add a pending publisher with:
   - Owner: `Options-Analysis-Suite`
   - Repository: `options-analysis-suite-python`
   - Workflow filename: `publish.yml`
   - Environment: `pypi`
3. (After the first publish, the project will exist on PyPI and the
   pending publisher becomes a regular trusted publisher.)

**One-time setup (on GitHub):**

The publish job runs in a GitHub environment named `pypi` (see
`environment: pypi` in `publish.yml`). Create it under **Settings →
Environments → New environment**. Optional but recommended: require
manual approval, restrict to the `main` branch, and add reviewers so a
stray tag push can't ship to PyPI without a human in the loop.

**Per-release:**

1. Bump `version` in `pyproject.toml` to the new version
   (e.g. `0.1.0a2` → `0.1.0`). This is the single source of truth —
   `oas.__version__` and the `User-Agent` header both derive from
   it via `importlib.metadata` at import time.
2. Refresh the editable install in your dev env: `uv pip install -e .`
   (or `pip install -e .`). Editable installs cache dist-info, so
   without this step `make test` and any local sanity checks will
   still report the **previous** version.
3. Update `CHANGELOG.md` under the new version heading; move
   `[Unreleased]` items into it.
4. Commit (`chore: release vX.Y.Z`).
5. Tag the commit: `git tag vX.Y.Z` (the `v` prefix is required — the
   publish workflow only triggers on tags matching `v*`).
6. Push the tag: `git push origin vX.Y.Z`.

The workflow:
- Verifies the tag's version matches `pyproject.toml`
- Runs lint + typecheck + offline tests
- Builds sdist + wheel via `uv build`
- Validates distribution metadata (`twine check`)
- Publishes to PyPI through the OIDC trusted publisher

If the tag-vs-pyproject guard fails, fix `pyproject.toml`, retag with
`git tag -d` + recreate, and re-push.

## Sync between monorepo and standalone repo

The SDK lives in two places:

- `options-analysis-suite/sdk/python/` — canonical dev location (private monorepo)
- `options-analysis-suite-python/` (root) — release mirror, this repo

Edit in the monorepo, then before each release rsync to the standalone repo:

```bash
rsync -av \
  --exclude='.git' --exclude='.venv' --exclude='dist' \
  --exclude='.mypy_cache' --exclude='.pytest_cache' --exclude='.ruff_cache' \
  /path/to/monorepo/sdk/python/ /path/to/options-analysis-suite-python/
```

**Don't use `--delete`** — it would wipe the standalone repo's
`.github/workflows/` (those don't exist in the monorepo).
