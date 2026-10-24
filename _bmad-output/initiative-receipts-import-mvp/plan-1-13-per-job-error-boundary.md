---
title: 'Per-job error boundary'
type: 'feature'
ticket: '13'
created: '2026-10-24'
status: 'in-progress'
baseline_revision: 'faf23f4bcdcd52f851c9751e430fa495ea25104a'
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

**Problem:** Any step exception postpones the job forever: a PostgreSQL or Telegram outage is not told apart from a bug, nobody is alerted, a raise after a Gemini answer repeats the paid call each time, and nothing reads `step_starts`.

**Approach:** A boundary in the jobs module classifies each job's exception: PostgreSQL connection-class errors and Telegram download errors become waits with an alert; anything else, and a job picked with three unrecorded step starts, ends the job as `failed` with an `internal:<state>` alert. A kept `pass1_json` that no longer parses redoes pass 1.

## Boundaries & Constraints

**Always:**
- Only `jobs.py` changes job state; `loop.run_due` keeps a log-only catch so a fault inside the boundary still moves on to the next job.
- The boundary re-reads the job; the state it sees is the state named in `internal:<state>` and in the wait.
- PostgreSQL connection class: `psycopg.OperationalError`/`InterfaceError` with no SQLSTATE, SQLSTATE class `08`, or `57P01`–`57P03`. Any other psycopg error is internal.
- Telegram download errors: `TelegramAPIError` and `TelegramRetryExhaustedError`.
- A wait is due after `retry_delay`, resets `step_starts`, keeps `waits` and `attempts`, tells the sender nothing.
- Recovery: `postgres_unreachable` when a job's pipeline opens; `telegram_unreachable` also after a download returns; `internal:<state>` when a later step in that state returns without an exception.
- Alert reasons carry the exception type, plus the SQLSTATE or the Telegram method; never `str(exc)`. The traceback goes to `log.exception`.
- Three unrecorded step starts is a fixed constant, checked when the job is picked, before any step runs.
- Decision: no retries for internal errors; a job stopped by one is moved to `failed` (owner, 2026-10-24).
- Decision: failure reason `internal_error`; the sender gets 👎 and its sender text, the admin its admin text with no file copy; wording in Design Notes (owner, 2026-10-24).
- Decision: `ChainReferenceError` (view missing or no privilege) is a wait like PostgreSQL, with no extra alert, since `chain_reference` is already raised (owner, 2026-10-24).
- Decision: the AD-16 amendment and AD-3 edges as worded in Design Notes (owner, 2026-10-24).
- Decision: implementation by Gemini 3.8 Flash in Antigravity, from a prompt written in this session (owner, 2026-10-24).

**Never:**
- No change to `app/alerts.py`, the Gemini classification, the attempt rules or the queue schema; no new setting, no backoff for these waits.
- No transition when the re-read job is already final (alert and log only).
- No PostgreSQL migration.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| PostgreSQL down | connect or query raises connection class, any pipeline state | same state, due after `retry_delay`, `step_starts` 0, `waits` kept; one `postgres_unreachable` | — |
| PostgreSQL back | next pipeline opens | one recovery; job continues | — |
| Reference unreadable | `ChainReferenceError` | same state, wait as for PostgreSQL | no alert beyond `chain_reference` |
| Telegram download fails | 401 or retries exhausted in `received` | `received`, no attempt, one `telegram_unreachable` | — |
| Download works again | download returns | recovery if active | — |
| Other exception | e.g. `RuntimeError`, `ProgrammingError`, missing `pass1_json` | `failed` with the internal reason, sender and admin told, file deleted, one `internal:<state>` | traceback logged |
| Three unrecorded starts | picked with `step_starts >= 3` | no step runs; as other exception | — |
| Raise after the final state | e.g. file delete after `stored` | state stays final | alert and log only |
| `pass1_json` no longer parses | `ValidationError` in `extract_pending` | `chain_pending`, same attempts, no alert | — |
| Same state works later | next step in that state returns | `internal:<state>` recovered | — |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/adapters/postgres/` -- add `is_connection_error(exc) -> bool` (predicate above), next to `chains.py`'s SQLSTATE sets.
- `src/retail_receipts_import/app/jobs.py` -- new `run(job, ports, max_attempts, retry_delay)`: three-starts check, then `advance`, catching per the matrix; `_extract` wraps only `Pass1Response.model_validate_json` for the fallback (`to_chain_pending(attempts=job.attempts, unsupported=False)`); `advance` recovers `POSTGRES_UNREACHABLE` after `open_pipeline()` enters, `TELEGRAM_UNREACHABLE` after `ports.download` returns, and `INTERNAL` for the state after each step returns. Internal end: `_finish(fresh_job, FAILED, failure_reason=...)`.
- `src/retail_receipts_import/adapters/queue/sqlite.py` -- `postpone` resets `step_starts` (docstring: a wait is a recorded result).
- `src/retail_receipts_import/app/loop.py` -- `run_due` calls `jobs.run`; its catch only logs. `LoopSettings.retry_delay` comment updated.
- `src/retail_receipts_import/domain/outcomes.py`, `texts/messages.toml` -- `FailureReason.INTERNAL_ERROR` and its two texts; `app/notify.py` `COPY_TO_ADMIN` unchanged.
- `_bmad-output/initiative-receipts-import-mvp/architecture-receipts-import/architecture-receipts-import.md` -- AD-16 rule and AD-3 diagram as in Design Notes.
- Tests that change meaning: `tests/test_loop.py` `STOP` becomes `psycopg.OperationalError("stopped here")` so mid-way stops stay waits; `write_result = RuntimeError("postgres down")` becomes the same; `test_step_exception_keeps_the_wait_count` becomes a PostgreSQL wait; `test_step_start_is_counted…` drives starts with `queue.start_step`; `test_exception_keeps_the_job_and_retries…` and the `RuntimeError` case of `test_download_exception_keeps…` now expect `failed`; `tests/test_dedup.py:177` models a crash, so it becomes a connection-class error. Do not keep them green by keeping old behavior.
- Reuse: `Fakes`, `make_fakes`, `first_cycle`, `rerun`, `RecordingTelegram`.

## Tasks & Acceptance

**Execution:**
- [ ] `adapters/postgres/`, `tests/` -- predicate with one test per class, incl. `ProgrammingError` → false.
- [ ] `domain/outcomes.py`, `texts/messages.toml`, `tests/test_texts.py` -- failure reason and texts.
- [ ] `adapters/queue/sqlite.py`, `app/jobs.py`, `app/loop.py` -- boundary, fallback, recoveries.
- [ ] `tests/test_loop.py`, `tests/test_dedup.py` -- every matrix row; changed tests above.
- [ ] `architecture-receipts-import.md` -- AD-16 and AD-3 amendment.

**Acceptance Criteria:**
- Given PostgreSQL failing for two loop cycles and then working, when the loop runs, then the admin gets one alert and one recovery and the job ends `stored` with no extra Gemini call.
- Given a step raising an unexpected error, when the loop runs, then the next due job still runs in the same cycle and the failed job is never picked again.

## Implementation Notes

## Plan Change Log

## Review Triage Log

## Design Notes

```toml
[sender_messages]
internal_error = "Не удалось обработать чек из-за внутренней ошибки. Администратор уведомлён."
[admin_messages]
internal_error = "Внутренняя ошибка при обработке чека, подробности в журнале; копия не приложена."
```

AD-16 rule, replacing its two error bullets and the step-start sentence:

> - Connection-class PostgreSQL errors (SQLSTATE class `08`, `57P01`–`57P03`, or a connection error with no SQLSTATE), an unreadable chain reference, and Telegram download errors are a wait of `job_retry_delay_s`: no attempt, nothing to the sender, `postgres_unreachable` or `telegram_unreachable`.
> - Any other error ends the job as `failed` with `internal_error`, logs the traceback and raises `internal:<state>`; it is not retried (owner decision 2026-10-24).
> - A job picked with 3 step starts and no recorded result is treated the same way.

AD-3 diagram: add `received`, `chain_pending`, `extract_pending`, `write_pending` `--> failed: internal error`.

Why a recovery on pipeline open: connecting is the first PostgreSQL contact of every job, so the next job after an outage shows it. A Telegram poll recovering `telegram_unreachable` while downloads still fail re-sends at most one alert pair per cycle; accepted, as both endpoints are the same Bot API.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run <check>'` for `ruff check`, `ruff format --check`, `mypy`, `pytest` -- expected: all green.
- The same with `pytest -m integration` against a throwaway `postgres:18.6` -- expected: green.

**Manual checks:**
- Live-run evidence (risk high, dev only, owner approval): stop dev PostgreSQL, send a Spar receipt, see one `postgres_unreachable` alert and no sender reaction; start it, see one recovery and the 👍, one stored receipt.
