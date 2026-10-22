---
title: 'Chain reference consumer contract and reader'
type: 'feature'
ticket: '3'
created: '2026-10-22'
status: 'in-progress'
baseline_revision: '716183f245c85fd255356db01fe3d5f3fcf5ac49'
route: 'full'
route_source: 'auto'
risk: 'high'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The service has no source of known chains. Pass 1 needs the chain vocabulary and the registry needs to know which plug-ins are backed by an active reference row, but the admin-owned reference has no published shape and no reader.

**Approach:** Publish the `chains_v1` consumer contract 1.0.0 in `docs/contracts/` with a `docs/api-versions.md` entry, and add a PostgreSQL reader that returns the active chains as a domain type; the admin then creates the reference table, view and five rows in the dev database.

**Decisions (owner, 2026-10-22):**
- The reference lives in schema `public`: table `public.chains`, view `public.chains_v1`, owned by `postgres` (the admin).
- A bad row (invalid slug, NULL field, repeated `chain_id`) is skipped and returned as rejected, so the later `chain_reference` alert can fire while the valid chains keep working.
- The agent creates the dev reference on the admin's behalf: a temporary login role made through the pg18 MCP runs the contract SQL from WSL, ownership then passes to `postgres` and the role is dropped. Production moves to the pre-production step; there is no production database yet.
- Rows: `dm` «dm» [DM, dm]; `kaufland` «Kaufland» [KAUFLAND, Kaufland]; `lidl` «Lidl» [LIDL, Lidl]; `mueller` «Müller» [MÜLLER, Müller, Muller]; `spar` «Spar» [SPAR, Spar, INTERSPAR].

## Boundaries & Constraints

**Always:** the contract is this project's own, semver from 1.0.0; the view is read by name, never a table or enum; `chain_id` is a stable, unique lowercase ASCII slug; the reader returns only `active` rows; a structural fault (SQLSTATE 42P01, 3F000, 42703, 42501) raises one typed `ChainReferenceError` the later `chain_reference` alert can map; connection-class errors (class 08, 57P01–57P03) propagate unchanged for the AD-16 wait; integration tests seed the reference themselves in the throwaway database and refuse any database named `grocery-tracker*`.

**Never:** no migration of this project creates or writes the reference; no foreign key from receipt tables; no chain plug-ins, registry, pass-1 prompt or alerting (later stories); no production database.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY_PATH | five active rows | five chains, ordered by `chain_id`, aliases as a tuple | No error expected |
| INACTIVE | one row `active = false` | that chain absent | No error expected |
| BAD_ROW | `chain_id = 'Spar'`, or a NULL field | valid chains returned; the bad row listed as rejected with a reason | No exception |
| DUPLICATE_ID | two rows share `chain_id` | both rows rejected, other chains returned | No exception |
| NO_VIEW | view or column absent, or no `SELECT` | nothing returned | `ChainReferenceError`, cause kept |
| DB_DOWN | connection lost | nothing returned | psycopg `OperationalError` propagates |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/config.py` -- `Settings.conninfo(user, password)` and `redacted_dsn(user)`; reuse, no new settings.
- `src/retail_receipts_import/migrate.py` -- raw-SQL style; do not touch.
- `tests/conftest.py` -- `TEST_DSN_VAR`, `pg_conn` (rolls back on exit), unit-test psycopg guard. `pg_conn` has no project-database guard; only `migrate_conn` in `tests/test_migrate.py` refuses `grocery-tracker` names.
- `.dockerignore` -- already ships `docs/contracts/`.
- `docs/` -- absent; this story creates it.
- Dev database `grocery-tracker-dev` on 192.168.100.218:5434. The pg18 MCP is bound to database `postgres` as superuser, so dev SQL runs from WSL with `psql`. Writer role `rri_dev_writer`. Since PostgreSQL 15, `public` is owned by `pg_database_owner` and PUBLIC has no CREATE on it.

## Tasks & Acceptance

**Execution:**
- [ ] `docs/contracts/chains_v1.sql` -- the single reference DDL (table `public.chains`, view `public.chains_v1` selecting the four columns, constraints) plus the five rows; grants stay out, since the grantee differs per environment -- one source for tests and the dev setup
- [ ] `docs/contracts/chains_v1.md` -- contract 1.0.0: view, columns and types, slug rule `^[a-z][a-z0-9_]{0,31}$`, reserved ids `other` and `unreadable`, unique and never reused, `active` instead of delete, non-empty `display_name`, `aliases text[]` with non-empty elements, `SELECT` on the view for the environment's writer role (`rri_dev_writer` in dev), versioning (additive column = minor, anything else = `chains_v2`); links the `.sql`
- [ ] `docs/api-versions.md` -- table of contracts: own consumer contract `chains_v1` 1.0.0; `resolver_v1` pending
- [ ] `src/retail_receipts_import/domain/chains/__init__.py` -- frozen `KnownChain(chain_id, display_name, aliases: tuple[str, ...])`, slug pattern, sentinels `OTHER`, `UNREADABLE`
- [ ] `src/retail_receipts_import/adapters/__init__.py`, `adapters/postgres/__init__.py`, `adapters/postgres/chains.py` -- `read_chain_reference(conn) -> ChainReference`, `RejectReason` (`StrEnum`), `RejectedRow`, `ChainReferenceError`; no logging, no alerting
- [ ] `tests/conftest.py` -- `pg_conn` refuses database names containing `grocery-tracker`
- [ ] `tests/test_chains_reader.py` -- integration: seed by executing `chains_v1.sql` in `pg_conn`, failing first if `public.chains` or `public.chains_v1` exists; one test per matrix row except DB_DOWN; no-SELECT via `CREATE ROLE` + `SET ROLE` inside the transaction, nothing asserted after the aborted query. Unit, with a fake connection: `UndefinedTable` maps to `ChainReferenceError`, `OperationalError` with `sqlstate=None` propagates
- [ ] `scratch/read_chains.py` -- local-only evidence (scratch is gitignored): reads dev as the writer role from `.env`, prints the redacted DSN and the result, never a password
- [ ] dev database -- the procedure in Design Notes; output recorded in Implementation Notes
- [ ] `README.md` -- one paragraph: the service needs the chain reference; link to the contract

**Acceptance Criteria:**
- Given a CI database seeded from `chains_v1.sql`, when the reader runs, then it returns `dm`, `kaufland`, `lidl`, `mueller`, `spar` in that order with no rejected rows.
- Given one seeded row set inactive, when the reader runs, then that id is absent from the chains and listed among the inactive ids.
- Given added rows `Spar`, `other`, a NULL `display_name` and two rows sharing `chain_id` `x`, when the reader runs, then the five valid chains are returned and the bad rows are rejected with `invalid_slug`, `reserved_id`, `null_field` and `duplicate_id`.
- Given the view dropped or `SELECT` withheld, when the reader runs, then `ChainReferenceError` is raised; given a lost connection, then the psycopg `OperationalError` reaches the caller.
- Given the dev database after setup, when `scratch/read_chains.py` runs in WSL as `rri_dev_writer`, then it prints the five chains with `INTERSPAR` among `spar`'s aliases, and the temporary role no longer exists in `pg_roles`.
- Given a push, when CI runs, then the standard check suite and integration tests pass.

## Implementation Notes

- Reject-reason mapping beyond the obvious: a blank `display_name` and a non-boolean `active` map to `null_field` (as unusable as a missing value); a NULL `aliases` maps to `null_field`, a non-array, NULL element, empty element or nested array to `bad_aliases`. Per-row faults are checked first; a row with no other fault whose `chain_id` occurs more than once (active or not) gets `duplicate_id`.
- The contract table carries the rules as named constraints, so integration tests serve rule-breaking rows through a union view over an unconstrained table inside the test transaction.
- Local verification (WSL, uv 0.13.4): ruff check, ruff format --check, mypy strict, pytest (34 passed) green; `pytest -m integration` against a throwaway `postgres:18.6` container on localhost:55432: 10 passed, including the 7 chain reader tests.
- Dev setup NOT done. The pg18 MCP was confirmed to point at the dev cluster (PostgreSQL 18.6, `grocery-tracker-dev` and `rri_dev_*` roles present). WSL has no `psql`, so the setup was to run through a psycopg scratch script; writing the temporary-role pgpass file and the setup script was refused by the harness permission classifier, so no role was created and nothing was written to dev. Needs owner action or explicit permission.

## Plan Change Log

- 2026-10-22: Dev setup step 1 creates the temporary role through `DO ... EXECUTE format(...)`, since `VALID UNTIL` rejects an expression; added a stop-and-report rule if the role cannot log in.

## Review Triage Log

## Design Notes

The reader selects the four named columns with no filter, then validates each row, finds duplicate ids and applies `active` in Python. Filtering in SQL would hide NULL `active` rows and duplicates with one inactive copy. Validation covers types too: a `text` aliases column would come back as `str`, and `tuple("DM")` is `('D', 'M')`.

```python
@dataclass(frozen=True)
class ChainReference:
    chains: tuple[KnownChain, ...]
    inactive_ids: tuple[str, ...]
    rejected: tuple[RejectedRow, ...]  # RejectedRow(chain_id: str | None, reason: RejectReason)
```

Reasons: `invalid_slug`, `reserved_id`, `null_field`, `bad_aliases`, `duplicate_id`. Only SQLSTATE 42P01, 3F000, 42703, 42501 become `ChainReferenceError(...) from exc`; anything else re-raises unchanged.

Dev setup (agent acting as admin):
1. The pg18 MCP runs a `DO` block: `EXECUTE format('CREATE ROLE %I LOGIN IN ROLE postgres PASSWORD %L VALID UNTIL %L', '<tmp>', '<generated>', now() + interval '1 hour')` (`VALID UNTIL` takes only a literal, not an expression). The password appears in the MCP transcript, hence the short expiry. If the role cannot log in from WSL (e.g. pg_hba rejects it), stop and report to the owner; server config changes are not approved.
2. The password goes into a `0600` pgpass file in WSL `$HOME`, outside the repo, and is never echoed.
3. `psql` runs `SET ROLE postgres`, then `chains_v1.sql`, then `GRANT SELECT ON public.chains_v1 TO rri_dev_writer`, so objects are owned by `postgres` from the start; it confirms `rri_dev_writer` has USAGE on `public`.
4. The pg18 MCP drops the role; `pg_roles` confirms it is gone; the pgpass file is deleted.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run <check>'` for ruff check, ruff format --check, mypy, pytest -- expected: all pass
- `uv run pytest -m integration` -- in CI, and locally against a throwaway PostgreSQL if one is available -- expected: chain reader tests pass
- `uv run scratch/read_chains.py` in WSL -- expected: five chains from dev
