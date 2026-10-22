---
title: 'Runtime baseline and first deployment'
type: 'feature'
ticket: '2'
created: '2026-10-22'
status: 'built'
baseline_revision: 'cbcb11a66cff487fdcf2a3182154e3a69e195112'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The service has no runtime: no validated config, no outcome enums or texts file, no container, no migration runner, and it has never been deployed, so no later story can run on the home server.

**Approach:** Add a pydantic-settings config with an environment guard and secret redaction, closed outcome and failure-reason enums in `domain` with a TOML texts loader that fails fast on a missing key or a disallowed reaction emoji, a Dockerfile and one compose service with one named volume, and a `migrate` command applying numbered SQL as the schema owner; create the dev database with its three roles and run `migrate` against it.

**Decisions (owner, 2026-10-22):**
- One Telegram bot serves dev and the future production. Production does not run until the whole project is developed, so the two never poll at once. The environment guard checks the configured environment against the database name only.
- The service schema is `retail_receipts_import` (snake_case); `resolver_v1` stays a separate schema.
- No production in this story. The dev database `grocery-tracker-dev` on 192.168.100.218 and its three roles (schema owner, writer, Resolver read-only) are created by the agent through the pg18 MCP. Home-server deployment and the production `migrate` move to a later pre-production step.

## Boundaries & Constraints

**Always:** secrets only from environment or the gitignored `.env`, redacted from logs and exceptions (DSNs print without password); startup fails fast on invalid config, environment mismatch, or a texts file missing a key; migrations are numbered plain SQL applied once each, in order, inside a transaction, as the schema owner role only; CI PostgreSQL image matches the server's minor version.

**Never:** no Telegram, Gemini or receipt logic (later stories); no PostgreSQL in compose; no production database, deployment, or `migrate` against production; integration tests never target the dev database.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY_PATH | valid env, complete texts file | service logs readiness and idles | No error expected |
| ENV_MISMATCH | `RRI_ENV=prod` with database `grocery-tracker-dev` | refuses to start, names the mismatch | exit non-zero, no secret in message |
| TEXTS_MISSING_KEY | texts file lacks one outcome key | refuses to start, names the key | exit non-zero |
| BAD_EMOJI | reaction emoji not in Telegram's allowed set | refuses to start, names the key | exit non-zero |
| MIGRATE_RERUN | all migrations already applied | applies nothing, exits 0 | No error expected |
| MIGRATE_FAIL | a migration's SQL fails | that migration rolls back, later ones not run | exit non-zero, DSN redacted |

</frozen-after-approval>

## Code Map

- `pyproject.toml` -- pinned deps already cover pydantic-settings and psycopg; add a `[project.scripts]` entry for the CLI.
- `src/retail_receipts_import/__init__.py` -- empty package; seed layout per architecture Structural Seed.
- `tests/conftest.py` -- socket and `psycopg.connect` guard for unmarked tests; `pg_conn` fixture from `RRI_TEST_DATABASE_URL`, rolls back on exit. Reuse for migrate integration tests.
- `.dockerignore` -- allow-list (pyproject, uv.lock, src, docs/contracts); must add `migrations/` and `texts/`.
- `.github/workflows/ci.yml` -- service image `postgres:18.0` is provisional; align to the server version read through the pg18 MCP.
- `doc-inbox/telegram_core_reference.zip` -- not used here; Telegram adapter is a later story.
- `.env` (gitignored) -- already holds the bot token and Gemini key under `RRI_TELEGRAM_BOT_TOKEN`, `RRI_GEMINI_API_KEY`; config field names must match. Role passwords are generated into it, never printed.
- `postgres-mcp` MCP is a different instance (PG 16, `receipts_db`); use only `pg18` for the dev database.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/config.py` -- pydantic-settings model (env prefix `RRI_`), environment guard, redacted DSN/secret repr -- AD conventions Config, Environments, Errors
- [ ] `src/retail_receipts_import/domain/outcomes.py` -- closed `Outcome` and `FailureReason` enums from receipt-outcomes.md -- texts keys
- [ ] `src/retail_receipts_import/app/texts.py` + `texts/messages.toml` -- loader validating every key and the reaction emoji set
- [ ] `src/retail_receipts_import/migrate.py` + `migrations/0001_*.sql` -- numbered runner with an applied-migrations table
- [ ] `src/retail_receipts_import/__main__.py` -- `run` (load config, texts, log readiness, idle) and `migrate` subcommands
- [ ] `Dockerfile`, `compose.yaml`, `.env.example`, `.dockerignore` -- one service, one named volume, base `python:3.14.8-slim-trixie`
- [ ] `.github/workflows/ci.yml` -- pin PostgreSQL image to the server minor version; add a `docker build` step so the Dockerfile is proven on every push
- [ ] `tests/` -- unit tests for the matrix rows; integration test for migrate idempotence and rollback
- [ ] pg18 MCP -- create `grocery-tracker-dev`, the three roles, schema `retail_receipts_import` owned by the schema owner, writer and Resolver grants
- [ ] `README.md` -- environment variables and the migrate command

**Acceptance Criteria:**
- Given the dev database, when `migrate` runs as the schema owner from WSL, then migrations apply and a second run applies nothing.
- Given dev config, when the service starts, then it logs readiness; with a mismatched environment or an incomplete texts file it refuses to start.
- Given a push, when CI runs, then the image builds and the check suite and integration tests pass on the server's PostgreSQL version.

## Implementation Notes

- PostgreSQL server is 18.6; CI service image pinned to `postgres:18.6`.
- Roles carry the environment in the name (`rri_dev_owner`, `rri_dev_writer`, `resolver_dev_reader`) because production roles will likely share the cluster. Passwords were generated into `.env`; only SCRAM-SHA-256 verifiers were sent to the server.
- Environment guard rule: `dev` requires a database name ending in `-dev`, `prod` one that does not. The production name is not decided yet.
- Reaction emoji set copied from Bot API `ReactionTypeEmoji` (2026-10-22). Default reactions: stored 👍, duplicate 🤝, failed 👎, in progress 👀, not accepted 🙈 — editable in `texts/messages.toml`.
- PostgreSQL 18.6 listens on 192.168.100.218:5434 (5433 is the PG 16 instance; 5432 is closed). The pg18 MCP wraps calls in a transaction, so `CREATE DATABASE` ran from WSL as `rri_dev_owner` under a temporary CREATEDB grant, then ownership went to `postgres` and CREATEDB was revoked. `rri_dev_owner` keeps CREATE on the database for the later `resolver_v1` schema.
- Schema `retail_receipts_import` is owned by `rri_dev_owner`; `rri_dev_writer` has USAGE plus default privileges on tables, sequences and types; `resolver_dev_reader` has CONNECT only until `resolver_v1` exists. PUBLIC has no CONNECT or TEMPORARY on the database.
- Live run, 2026-10-22: `migrate` from WSL applied 1 migration, the second run applied 0.

## Plan Change Log

## Review Triage Log

| Lens | Location | Verdict | Route | Evidence |
| --- | --- | --- | --- | --- |
| quick | `tests/test_migrate.py` `migrate_conn` | medium | patch | Fixture drops `retail_receipts_import` in whatever database the test DSN names; now refuses database names containing `grocery-tracker`. |
| quick | `migrate.discover` / `MIGRATIONS_DIR` | medium | patch | A missing directory returned no migrations and `migrate` reported "applied 0"; failing test added, `discover` now raises on no migrations. |
| quick | `__main__._migrate` empty password | low | patch | `SecretStr("")` passed the `is None` check and `replace("", …)` garbled the message; failing test added, empty password now refused with exit 2. |
| quick | writer DML on `schema_migrations` | low | reject | Real through default privileges, but only a service bug writing that table could hurt, and a role-aware revoke adds complexity. |
| quick | plan checkboxes unticked | low | reject | Fix is editing this build's plan. |

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run <check>'` for ruff check, ruff format --check, mypy, pytest -- expected: all pass
- `uv run pytest -m integration` -- in CI against the service container -- expected: migrate tests pass
- `uv run python -m retail_receipts_import migrate` twice in WSL against the dev database -- expected: first applies, second applies nothing

**Manual checks (if no CLI):**
- Through pg18: schema `retail_receipts_import` exists, owned by the schema owner; writer and Resolver roles have only their grants.
