---
title: 'Toolchain pins and CI'
type: 'chore'
ticket: '1'
created: '2026-10-21'
status: 'built'
baseline_revision: '9b774b7433913a553bc7642cc64c81d36c88e5de'
route: 'oneshot'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `pyproject.toml` pins a stale toolchain (ruff 0.9.9 targeting py313, mypy 1.15.0, pytest 8.3.5) that conflicts with the spine's Stack and AGENTS.md, has no runtime pins and no `integration` marker, and there is no CI, so later stories have no harness for PostgreSQL integration tests.

**Approach:** Pin every Stack row in `pyproject.toml` with `==` (dev tools, runtime libraries, build backend), set ruff `target-version = "py314"`, add the `integration` marker excluded from a plain `pytest` run, add one integration smoke test reading a dedicated test-only DSN variable, and add a GitHub Actions workflow on every push that runs `uv sync --locked`, the four standard checks and `pytest -m integration` against a PostgreSQL service container, using the same commands as the local WSL suite.

</frozen-after-approval>

## Implementation Notes

Oneshot: about 100 lines across `pyproject.toml`, `uv.lock`, `tests/`, and one workflow file; mechanical toolchain work with no domain logic.

- Versions: Stack rows as listed; hatchling 1.32.4, actions/checkout v7.0.1 and astral-sh/setup-uv v10.3.1 looked up as latest on 2026-10-21.
- `uv.lock` regenerated with `uvx uv@0.13.4` because WSL has uv 0.9.2; no `[tool.uv] required-version`, since the Windows uv 0.8.22 runs the BMad render script from this root.
- `postgres:18.0` in CI is provisional; the runtime-baseline story aligns it to the server version.
- Test DSN comes only from `RRI_TEST_DATABASE_URL`, never libpq `PG*` defaults; `pg_conn` fails when it is unset.
- `pytest -m integration` was not run locally: Docker is not running on this machine. It is verified only by the first CI run.

## Review Triage Log

- medium, patch: libpq bypasses the socket guard (reproduced: an unmarked test reached `192.0.2.1` and timed out). The guard now refuses `psycopg.connect` in unmarked tests; `tests/test_network_guard.py` keeps the repro.
- medium, patch: `with psycopg.connect(...)` commits on exit, so a fixture user's writes would persist. The fixture now rolls back before exit.
- low, patch: integration tests were held to localhost by the socket guard; they are now exempt like `live`, since they target an explicit test DSN.
- medium, defer: AGENTS.md's check list lacks `uv sync --locked`, `pytest -m integration` and the test DSN variable. Editing AGENTS.md is the owner's call.
- false: risk/route mismatch. Risk comes from the ticket; the route follows the workflow's LOC rule; quick review is pinned by the oneshot step. The plan-copy mismatch was the diff taken before the frontmatter edit.
- low, rejected: actions pinned by tag, not SHA. The exact-pin rule covers `pyproject.toml`; SHA pinning adds upkeep with no reachable threat at this scale.
- false: untracked provisional postgres tag. Ticket 2's description already owns the alignment.
- n/a: package reasons go in the commit message, which this commit provides.
