---
title: 'Job waits, attempts and resume'
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

**Problem:** `chain_pending` runs pass 1, pass 2 and the write as one step, so any wait reruns pass 1, a Gemini outage after pass 2 calls Gemini again, and nothing survives a restart between passes. Any `Invalid` ends the job at once, the first unsupported pass-1 result is final, and every wait uses the first backoff delay because the job keeps no wait count. A download that can never succeed is retried forever.

**Approach:** Make each AD-3 state its own persisted step: pass 1 in `chain_pending`, pass 2 and the checks in `extract_pending`, the write in `write_pending`. The job row keeps the attempt count, wait count, step starts, the unsupported flag, the pass-1 result and the versioned receipt. `app/jobs` applies every AD-7 rule in one SQLite transaction per transition, and the loop shortens its long poll to the next due job.

## Boundaries & Constraints

**Always:**
- Each transition, attempt or wait is one SQLite transaction, written only by `app/jobs` through the queue.
- The queue file on the dev volume is upgraded in place from version 1, so the committed offset survives. All new columns arrive in this one version bump.
- A job is resumed from its persisted state. From `write_pending` Gemini is never called again.
- `receipt_id` is assigned and persisted when the job enters `write_pending`.
- The attempt limit `job_max_attempts` comes from config, default 3, and is shared by both passes.
- The wait count grows by one per Gemini wait and feeds `classify`. It returns to 0 on every transition and every consumed attempt.
- A step start is counted in its own transaction before the step runs. Any recorded outcome (transition, attempt, wait) returns it to 0; an exception does not.

**Never:**
- No in-progress reaction, failure texts sent, admin copy or file deletion (entry 12).
- No alerts and no PostgreSQL error classification; a write exception keeps `write_pending` with `job_retry_delay_s` (entry 13). The step-start count is only recorded here.
- No dedup pre-check; `chain_pending` → `extract_pending` always skips it (entry 7).
- No branch on Telegram description text without a recorded fixture.

## I/O & Edge-Case Matrix

| Scenario | State before | Result | State after |
|---|---|---|---|
| Gemini unavailable or blocked, pass 1 or pass 2 | `chain_pending` / `extract_pending`, waits n | `ExtractionWait` | same state, waits n+1, no attempt, due after `classify(waits=n)` |
| Invalid (schema, unreadable, OIB, mismatch, Gemini 4xx) | either Gemini state, attempts a < limit−1 | `Invalid` | `chain_pending`, attempts a+1, pass-1 result cleared |
| Invalid on the last attempt | attempts limit−1 | `Invalid` | `failed`, reason of this attempt |
| First unsupported | `chain_pending`, flag clear, attempts < limit−1 | `Unsupported` | `chain_pending`, attempts +1, flag set |
| Second unsupported in a row | flag set | `Unsupported` | `unsupported_chain` |
| Unsupported, invalid, unsupported (limit 3) | — | — | `unsupported_chain` on the third, the last attempt |
| Limit 1, first unsupported | attempts 0 | `Unsupported` | `unsupported_chain` |
| Supported chain | `chain_pending` | pass-1 result | `extract_pending`, result persisted |
| Chain no longer supported at pass 2 | `extract_pending` | reference changed | `chain_pending`, no attempt |
| Valid and consistent | `extract_pending` | receipt | `write_pending`, receipt, version, `receipt_id` |
| Restart in `write_pending` | persisted receipt | write | `stored` / `duplicate`, zero `generate` calls |
| Stored payload version differs or does not parse | `write_pending` | — | `extract_pending`, no attempt |
| Oversize after `getFile` | `received` | `FileTooLarge` | `failed`, `file_too_large` (unchanged) |
| Telegram unavailable on download | `received` | retries exhausted, transport error | `received`, due after `job_retry_delay_s` |
| Permanent download failure | `received` | 4xx or no `file_path` | see Open Questions 1 |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/app/pipeline.py` -- `process_file` splits into three step functions (pass 1, pass 2 with OIB and consistency checks, write). `ExtractionWait`, `Ports` and the `Result` variants are reused; pass 2 re-reads the reference for the chain's OIBs.
- `src/retail_receipts_import/app/jobs.py` -- `advance` runs the step of the current state and applies the matrix. It now catches `ExtractionWait` itself and records the wait.
- `src/retail_receipts_import/app/loop.py` -- `run_due` loses its `ExtractionWait` branch; the generic handler stays. `poll` takes the shortened timeout.
- `src/retail_receipts_import/adapters/queue/sqlite.py` -- `SCHEMA_VERSION` 2 with a v1 upgrade; one transition call per matrix row; `next_due_at`. `due_jobs` returns the new fields.
- `src/retail_receipts_import/domain/jobs.py` -- `Job` gains the persisted fields; the receipt payload version constant lives in `domain`.
- `src/retail_receipts_import/adapters/telegram/download.py` -- `FileUnavailable` exists; `TelegramAPIError` (4xx) and `TelegramRetryExhaustedError` come from `client.py`.
- `src/retail_receipts_import/app/service.py` -- `classify` is bound with `waits=0` today; it now takes the job's wait count.
- `src/retail_receipts_import/config.py` -- add `job_max_attempts`.
- `tests/test_loop.py` -- `Fakes` and `cycle` are the harness. `test_non_stored_result_ends_the_job_without_a_notice` and `test_gemini_wait_postpones_by_its_own_delay` change.
- `tests/fixtures/spar/` -- pass-1 and pass-2 recordings for the step tests.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/adapters/queue/sqlite.py` -- version 2 columns: attempts, waits, step starts, unsupported flag, pass-1 JSON, receipt JSON, payload version; the v1 upgrade; transition, wait, step-start and `next_due_at` calls -- AD-3, one transaction each.
- [ ] `src/retail_receipts_import/app/pipeline.py` -- three step functions -- a wait in pass 2 must not rerun pass 1.
- [ ] `src/retail_receipts_import/app/jobs.py` -- the matrix -- the only owner of job state.
- [ ] `src/retail_receipts_import/app/loop.py` -- poll timeout `min(poll_timeout_s, max(0, ceil(next_due − now)))` while jobs wait -- AD-14.
- [ ] `src/retail_receipts_import/app/service.py` -- build the pipeline ports from `Settings` and the job's wait count in one small factory -- makes the deferred wiring testable.
- [ ] `src/retail_receipts_import/config.py` -- `job_max_attempts=3`, > 0.
- [ ] `tests/` -- every matrix row with fake ports; a restart between each pair of steps; a v1 queue file with an offset and a `chain_pending` job upgraded and resumed; the factory test below.
- [ ] Unknown-chain fixture -- see Open Questions 2.

**Acceptance Criteria:**
- Given the factory built from `Settings` with distinct non-default `image_max_pixels`, `gemini_backoff_initial_s`, `gemini_backoff_cap_s` and `job_retry_delay_s`, when its `classify` runs at waits 0 and at a wait count where the cap applies, then the delays equal initial and cap, and `prepare` uses the configured pixel cap.
- Given a job in `extract_pending` and a Gemini wait, when the loop runs it twice, then pass 1 is not called again and the second delay is twice the first.
- Given jobs waiting with the next due in 7 s, when the loop polls, then the long-poll timeout is 7 s, and with no waiting job it is `telegram_poll_timeout_s`.
- Given a job killed after each step, when the service restarts, then the job continues from the next step.

## Open Questions

1. Permanent download failure (4xx from `getFile` or the download, or no `file_path`). Options: (a) fail at once; (b) consume an attempt per failure, retry after `job_retry_delay_s`, fail at the limit. Both add a `FailureReason` whose sender and admin texts the texts loader requires at startup.
2. Live evidence. The ticket is `risk: high` with `hitl: false`; AGENTS requires `hitl` and live-run evidence. AD-6's unknown-chain fixture needs one live pass-1 recording. Options for its source: a receipt of a chain outside the reference, or an existing Lidl sample recorded against a reference narrowed to `spar`. Proposed evidence: a dev-bot receipt sent while Gemini is blocked by a wrong model id, the service restarted, the model restored, and the receipt stored without a resend.
3. Size. The plan is over the 1,600-token target. The seam: (6a) queue v2 with every column, persisted steps, attempts, unsupported rule, resume and payload version; (6b) wait count into `classify`, the factory and its test, shortened poll, download failures.

## Design Notes

Backoff stays `min(cap, initial << waits)`, so with the defaults a job waits 600, 1,200, then 1,800 s. Pass 2 re-reads the reference rather than persisting OIBs, so an OIB the admin corrects takes effect on the next pass; a chain withdrawn meanwhile is the reference's change, not the file's, so no attempt is consumed. A v1 `chain_pending` job meant "downloaded, pipeline next", which v2 `chain_pending` also means, so the upgrade sets no state.

## Verification

**Commands:**
- `wsl -- bash -lc '... uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all green.
- `wsl -- bash -lc '... uv run pytest -m integration'` with `RRI_TEST_DATABASE_URL` set -- expected: green.

## Implementation Notes

## Plan Change Log

## Review Triage Log
