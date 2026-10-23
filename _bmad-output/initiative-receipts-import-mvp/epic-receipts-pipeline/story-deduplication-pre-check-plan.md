---
title: 'Deduplication pre-check'
type: 'feature'
ticket: '7'
created: '2026-10-23'
status: done
baseline_revision: '53f980bcfc751f0e773fb36697ef2b5fed1a80e9'
route: 'full'
route_source: 'auto'
risk: 'high'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A resent receipt (another photo or PDF of a stored purchase) still runs pass 2 before the writer calls it a duplicate, so a Gemini call is spent on every resend.

**Approach:** After pass 1 finds a supported chain, normalize its printed time with the plug-in's rule and look up the dedup key with the writer's own lookup. A row from another source ends the job as `duplicate` at once; anything else continues to pass 2 as today.

## Boundaries & Constraints

**Always:**
- The pre-check is advisory: the unique constraint at write time stays the only authority.
- Pass-1 time missing or unreadable, or PostgreSQL failing the lookup with a `psycopg.OperationalError`, skips the pre-check with no wait, no attempt and no alert.
- A pre-check hit consumes no attempt, persists no `extract_pending`, and stores the existing `receipt_id` on the job.
- A key held by the job's own source is not a hit; the job continues and the writer resolves it.
- The key uses the same `zagreb_to_utc` truncation as pass 2, through `ChainPlugin.normalize_pass1_time`.
- Decision: live evidence is a dev-bot run: the owner sends the same Spar PDF twice as two messages; the second ends `duplicate`, the logs show no pass 2, and dev holds one row (owner, 2026-10-23).
- Decision: implementation runs in a subagent on Sonnet 5.5 (owner, 2026-10-23).

**Never:**
- No duplicate reaction or message (entry 12), no alerts or PostgreSQL error classification (entry 13).
- No migration, no queue schema change, no change to `write_receipt` or its lookup order.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Resend, other source | key stored from another source | `duplicate`, existing `receipt_id`, no pass 2 | — |
| New purchase | key not stored | `extract_pending`, pass 2 runs | — |
| Own source holds the key | stored from this source | `extract_pending`; writer gives own write → `stored` | — |
| Pass-1 time null or unreadable | `purchase_time` null or `"9h"` | lookup not called, pass 2 runs | — |
| PostgreSQL fails the lookup | `OperationalError` | warning logged, pass 2 runs | no wait, attempt or alert |
| Pre-check skipped, writer finds key | another source holds it | `duplicate` from the writer (existing behaviour) | — |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/adapters/postgres/receipts.py` -- new `find_other_source(conn, chain_id, purchased_at, source) -> uuid.UUID | None` over the existing `find_by_dedup_key`; returns the id only when the row's source differs; catches `psycopg.OperationalError`, logs a warning without the connection string, returns `None`.
- `src/retail_receipts_import/app/pipeline.py` -- `Ports` gains `find_other_source: Callable[[str, datetime, ReceiptSource], uuid.UUID | None]`; new `precheck(pass1, source, ports) -> Duplicate | None` using `PLUGINS[pass1.chain].normalize_pass1_time`.
- `src/retail_receipts_import/app/jobs.py` -- `_detect_chain`, `ChainFound` branch: call `pipeline.precheck(pass1, _source(job), steps)`; a hit `_finish(DUPLICATE, receipt_id=...)` and logs `pre-check`; otherwise unchanged.
- `src/retail_receipts_import/app/service.py` -- `pipeline_ports` binds `find_other_source` to `conn`.
- Already true, no change: `_write` maps the writer's `DUPLICATE` to `duplicate` and `OWN_WRITE` to `stored`; `Queue.finish` accepts `DUPLICATE` from any state; Spar's `normalize_pass1_time` exists (`DATE` accepts `01.02.2030` and `01.02.2030.`).
- Call sites of `Ports(...)`: `tests/test_loop.py` (`Fakes`), `tests/test_pipeline.py` (`FakePorts`), `tests/test_spar_fixtures.py`.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/adapters/postgres/receipts.py` -- `find_other_source`.
- [ ] `src/retail_receipts_import/app/pipeline.py`, `app/jobs.py`, `app/service.py` -- the port, `precheck` and the wiring.
- [ ] `tests/test_loop.py`, `tests/test_pipeline.py`, `tests/test_spar_fixtures.py` -- the new port in each fake (`Fakes` gains a settable stored id and records lookups); unit tests for every matrix row except the PostgreSQL one.
- [ ] `tests/test_dedup.py` (integration) -- `jobs.advance` on a real `Queue` with `pipeline_ports(settings, receipts_conn, fake_generate)`, overriding only `read_chain_reference`:
  - two messages of one purchase, pass 1 of the second printing `01.02.2030` where pass 2 printed `01.02.2030.`: the second ends `duplicate` with the first's id, no `SparPass2` call for it, one row in `receipts` and in `receipt_feed`;
  - the same with pass-1 time `null`: pass 2 runs, the writer's result ends it `duplicate`, one row;
  - `Queue.finish` raising once after the commit, then a rerun after `retry_delay`: `stored`, one receipt, one feed row;
  - `find_other_source` on a closed connection returns `None` (confirm psycopg raises `OperationalError` there, not `InterfaceError`).

**Acceptance Criteria:**
- Given a stored Spar receipt, when another message with a different file of the same purchase is processed, then the job ends `duplicate`, pass 2 is never called, and the database holds one receipt.
- Given a crash between the PostgreSQL commit and the SQLite final mark, when the job is run again, then it ends `stored` and nothing more is written.

## Implementation Notes

- Implemented by a subagent on Sonnet 5.5, per the owner's decision; diff read and checks rerun in the main session.
- `tests/steps.py` (`run_steps`) does not call `precheck`; the pre-check is exercised through `jobs` and `precheck` directly.
- The PostgreSQL-failure row is covered at the adapter (`find_other_source` on a closed connection returns `None` and logs `OperationalError`); a `None` takes the same path as the tested miss.
- Verification, in WSL: ruff check, ruff format --check and mypy clean; `pytest` passed 331; `pytest -m integration` passed 33 (5 in `tests/test_dedup.py`) against a throwaway `postgres:18.6` container on port 55432, stopped afterwards.
- Dev-bot manual check pending the owner.
- Dev-bot check, 2026-10-23, at `f731b1129fa8702d1fb421d735ff276723917df0`: the owner sent one Spar PDF as two messages. Job 3 ran pass 1 and pass 2 and was `stored` as `01a16a91-10f4-74a1-9679-df555e718a40`. Job 4 made one Gemini call (pass 1), logged `pre-check found receipt 01a16a91-…`, and ended `duplicate` with that id, 0 attempts and no pass-1 result kept. Dev holds 1 receipt and 1 feed row at the key (`scratch/verify_dedup.py`).
- After the review patches (tests only): ruff, mypy clean; `pytest` 331 passed; `pytest -m integration` 33 passed on a throwaway `postgres:18.6`.

## Plan Change Log

## Review Triage Log

- quick, iteration 0: low 2, false 1.
  - low -- `test_key_held_by_the_own_source_goes_on_to_the_writer` never exercises the own-source filter; confirmed by deleting the filter in `find_other_source`: `tests/test_loop.py` and `tests/test_pipeline.py` still pass (119). The filter is covered by the integration test `test_find_other_source_ignores_the_own_source` -- patch: rename and recomment the unit test to claim only the miss-to-own-write path.
  - low -- closed-connection test checks `"OperationalError" in caplog.text`, not the warning level -- patch: assert a WARNING record naming `OperationalError`.
  - false -- "pass 2 does not run after an `OperationalError` on a broken connection": the job does move to `extract_pending` with no attempt, as for a miss; the reference read failing there is existing behaviour, recorded in Design Notes, and a usable connection (for example `57014` statement timeout) does run pass 2 -- rejected.

## Design Notes

Why the lookup failure is caught: the connection is per job and autocommit. A drop at the pre-check then fails pass 2's reference read, and the job postpones in `extract_pending` with pass 1 kept, so Gemini is not asked pass 1 again.

Accepted risk (AD-8): a misread pass-1 time that lands on another stored receipt's minute ends the new receipt as `duplicate` without pass 2. The same collision at pass 2 time is already accepted for two purchases in one minute.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && ... ruff format --check && ... mypy && ... pytest'` -- expected: all green.
- The same with `pytest -m integration` and `RRI_TEST_DATABASE_URL` on a throwaway `postgres:18.6` -- expected: green, including `tests/test_dedup.py`.

**Manual checks:**
- Dev bot, run by the owner: the same Spar PDF sent twice as two messages; the second job ends `duplicate`, its log has a `pre-check` line and no pass-2 call, and dev's `receipts` holds one row for that key.
