---
title: 'Job steps, attempts and resume'
type: 'feature'
ticket: '6'
created: '2026-10-23'
status: 'draft'
baseline_revision: ''
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

**Problem:** `chain_pending` runs pass 1, pass 2 and the write as one step. A wait after pass 1 reruns it, and nothing survives a restart between passes. Any `Invalid` ends the job at once, and the first unsupported pass-1 result is final.

**Approach:** Make each AD-3 state its own persisted step: pass 1 in `chain_pending`, pass 2 and its checks in `extract_pending`, the write in `write_pending`. The job row keeps the attempt count, the unsupported flag, step starts, the pass-1 result and the versioned receipt. `app/jobs` applies the AD-7 rules in one SQLite transaction per transition.

## Boundaries & Constraints

**Always:**
- Each transition, attempt or wait is one SQLite transaction, written only by `app/jobs` through the queue.
- The dev queue file is upgraded in place from version 1, so the committed offset survives. Every column entry 19 needs, the wait count included, arrives in this one version bump.
- A job resumes from its persisted state. From `write_pending` Gemini is never called again.
- `receipt_id` is assigned and persisted when the job enters `write_pending`.
- The attempt limit `job_max_attempts` comes from config, default 3, shared by both passes.
- A step start is counted in its own transaction before the step runs. A transition, attempt or wait resets it to 0; an exception does not.
- The unknown-chain fixture is one live pass-1 recording of an existing Lidl sample against a reference narrowed to `spar` (owner, 2026-10-23).
- Live-run evidence on the dev bot: a receipt sent while Gemini is blocked by a wrong model id, the service restarted, the model restored; the receipt is stored without a resend (owner, 2026-10-23).

**Never:**
- No wait count growth, backoff doubling, shortened long poll or download-failure ending; those are entry 19. `classify` stays bound with `waits=0`.
- No in-progress reaction, failure texts sent, admin copy or file deletion (entry 12).
- No alerts or PostgreSQL error classification; a write exception keeps `write_pending` with `job_retry_delay_s` (entry 13).
- No dedup pre-check; `chain_pending` → `extract_pending` always skips it (entry 7).

## I/O & Edge-Case Matrix

| Scenario | State before | Result | State after |
|---|---|---|---|
| Gemini unavailable or blocked, pass 1 or 2 | `chain_pending` / `extract_pending` | `ExtractionWait` | same state, no attempt, due after the classifier's delay |
| Invalid (schema, unreadable, OIB, mismatch, Gemini 4xx) | attempts a < limit−1 | `Invalid` | `chain_pending`, attempts a+1, pass-1 result and flag cleared |
| Invalid on the last attempt | attempts limit−1 | `Invalid` | `failed`, reason of this attempt |
| First unsupported | `chain_pending`, flag clear, attempts < limit−1 | `Unsupported` | `chain_pending`, attempts +1, flag set |
| Second unsupported in a row | flag set | `Unsupported` | `unsupported_chain` |
| Unsupported, invalid, unsupported (limit 3) | — | — | `unsupported_chain` on the last attempt |
| Limit 1, first unsupported | attempts 0 | `Unsupported` | `unsupported_chain` |
| Supported chain | `chain_pending` | pass-1 result | `extract_pending`, result persisted |
| Chain no longer supported at pass 2 | `extract_pending` | reference changed | `chain_pending`, no attempt |
| Valid and consistent | `extract_pending` | receipt | `write_pending`, receipt, version, `receipt_id` |
| Restart in `write_pending` | persisted receipt | write | `stored` / `duplicate`, zero `generate` calls |
| Payload version differs or does not parse | `write_pending` | — | `extract_pending`, no attempt |
| Oversize after `getFile` | `received` | `FileTooLarge` | `failed`, `file_too_large` (unchanged) |
| Any download exception | `received` | — | `received`, due after `job_retry_delay_s` (unchanged) |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/app/pipeline.py` -- `process_file` splits into pass-1, pass-2 (OIB and consistency checks) and write steps. Reuse `ExtractionWait`, `Ports` and the `Result` variants. Pass 2 re-reads the reference for the chain's OIBs.
- `src/retail_receipts_import/app/jobs.py` -- `advance` runs the current state's step and applies the matrix; it now catches `ExtractionWait` and records the wait.
- `src/retail_receipts_import/app/loop.py` -- `run_due` loses its `ExtractionWait` branch and keeps the generic handler; the wait log line moves with the catch.
- `src/retail_receipts_import/adapters/queue/sqlite.py` -- `SCHEMA_VERSION` 2 and the v1 upgrade; one call per transition kind; `due_jobs` returns the new fields.
- `src/retail_receipts_import/domain/jobs.py` -- `Job` gains the persisted fields; the receipt payload version constant lives in `domain`.
- `src/retail_receipts_import/app/service.py` -- `process` opens one connection per job; the steps share it.
- `src/retail_receipts_import/config.py` -- add `job_max_attempts`.
- `tests/test_loop.py` -- `Fakes` and `cycle` are the harness. `test_non_stored_result_ends_the_job_without_a_notice` and `test_gemini_wait_postpones_by_its_own_delay` change.
- `tests/fixtures/spar/` -- pass-1 and pass-2 recordings for the step tests. `scratch/record_spar.py` is the recording pattern; Lidl samples are in `doc-inbox/fixtures/`.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/adapters/queue/sqlite.py` -- version 2 columns: attempts, waits, step starts, unsupported flag, pass-1 JSON, receipt JSON, payload version; the v1 upgrade; transition, wait and step-start calls -- AD-3, one transaction each.
- [ ] `src/retail_receipts_import/app/pipeline.py` -- three step functions -- a wait in pass 2 must not rerun pass 1.
- [ ] `src/retail_receipts_import/app/jobs.py` -- the matrix -- the only owner of job state.
- [ ] `src/retail_receipts_import/app/loop.py`, `src/retail_receipts_import/app/service.py`, `src/retail_receipts_import/config.py` -- wiring and `job_max_attempts=3`, > 0.
- [ ] `scratch/record_unknown_chain.py` -- one live pass-1 call for one Lidl sample with the vocabulary `spar` only, into `tests/fixtures/unknown_chain/pass1.json`; an answer other than `other` stops the work and is reported, with no prompt change -- AD-6.
- [ ] `tests/` -- every matrix row with fake ports; a restart between each pair of steps; a v1 queue file with an offset and a `chain_pending` job, upgraded and resumed; the unknown-chain fixture giving `other` and `Unsupported`.

**Acceptance Criteria:**
- Given a job stopped after each step, when the service restarts, then the job continues from the next step, and from `write_pending` with zero `generate` calls.
- Given a version 1 queue file with an offset and an unfinished job, when the service opens it, then the offset is unchanged and the job runs to `stored`.
- Given the recorded unknown-chain response, when pass 1 parses it, then the chain is `other` and the job takes the unsupported path.

## Design Notes

Pass 2 re-reads the reference rather than persisting OIBs, so an OIB the admin corrects applies on the next pass. A chain withdrawn meanwhile is the reference's change, not the file's, so no attempt is consumed. A v1 `chain_pending` job meant "downloaded, pipeline next", which v2 `chain_pending` also means, so the upgrade changes no state. The waits column is written 0 here; entry 19 fills it.

## Verification

**Commands:**
- `wsl -- bash -lc '... uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all green.
- `wsl -- bash -lc '... uv run pytest -m integration'` with `RRI_TEST_DATABASE_URL` set -- expected: green.

**Manual checks:**
- Dev bot, with the owner: send a Spar receipt with `RRI_GEMINI_MODEL` set to a retired model, see the job wait in `chain_pending`, restart with the right model, see 👍 and one stored receipt. A blocked wait is persisted as 600 s, so the receipt is stored up to 10 minutes after the restart.

## Implementation Notes

- Owner, 2026-10-23: the plan stays whole at about 2,100 tokens; code is written by Claude Opus 5.5 in a separate Claude Code CLI session, not a subagent.

## Plan Change Log

## Review Triage Log
