---
title: 'Per-job error boundary (second half of ticket 13; its status is in story-operational-alerts-and-per-job-error-boundary-plan.md)'
type: 'feature'
created: '2026-10-24'
status: 'built'
baseline_revision: 'faf23f4bcdcd52f851c9751e430fa495ea25104a'
route: 'full'
route_source: 'auto'
risk: 'high'
review: 'thorough'
review_source: 'pinned'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
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
- [x] `adapters/postgres/`, `tests/` -- predicate with one test per class, incl. `ProgrammingError` → false.
- [x] `domain/outcomes.py`, `texts/messages.toml`, `tests/test_texts.py` -- failure reason and texts.
- [x] `adapters/queue/sqlite.py`, `app/jobs.py`, `app/loop.py` -- boundary, fallback, recoveries.
- [x] `tests/test_loop.py`, `tests/test_dedup.py` -- every matrix row; changed tests above.
- [x] `architecture-receipts-import.md` -- AD-16 and AD-3 amendment.

**Acceptance Criteria:**
- Given PostgreSQL failing for two loop cycles and then working, when the loop runs, then the admin gets one alert and one recovery and the job ends `stored` with no extra Gemini call.
- Given a step raising an unexpected error, when the loop runs, then the next due job still runs in the same cycle and the failed job is never picked again.

## Implementation Notes

- Implemented by Gemini 3.8 Flash in Antigravity, per owner decision (2026-10-24).
- Added `is_connection_error` in `adapters/postgres/chains.py` covering SQLSTATE class `08`, `57P01`–`57P03`, and connection errors without SQLSTATE; exported in `adapters/postgres/__init__.py`.
- Added `FailureReason.INTERNAL_ERROR` in `domain/outcomes.py` with sender and admin messages in `texts/messages.toml`.
- Updated `Queue.postpone` in `adapters/queue/sqlite.py` to reset `step_starts` to 0.
- Implemented `jobs.run` error boundary with 3-starts check, exception classification (PostgreSQL waits, ChainReferenceError waits without extra alert, Telegram download waits, internal errors moving to `failed` without retries, and log/alert-only for errors after final state).
- Added recoveries in `jobs.advance`: `POSTGRES_UNREACHABLE` on pipeline open, `TELEGRAM_UNREACHABLE` after download, `INTERNAL` for state on step return.
- Updated `jobs._extract` to wrap only `Pass1Response.model_validate_json` for fallback to `chain_pending`.
- Updated `loop.run_due` to call `jobs.run` and log-only on unhandled exceptions; updated `LoopSettings.retry_delay` comment.
- Amended AD-16 and AD-3 diagram in `architecture-receipts-import.md`.
- Verification in WSL: `ruff check`, `ruff format --check`, `mypy`, `pytest` (438 passed, 34 integration deselected) all clean. Manual check on dev-bot pending owner.
- Review fixes (pass 1 patches, Antigravity): `_finish` recovers `internal:<state>`; one-line logs for waits; the three-starts guard finishes directly with reason `step_starts=<n>`; `ProcessKilled(BaseException)` drives the guard and the crash-after-commit test; added tests for the download alert text, `internal:received` recovery and the `run_due` catch; AD-3 fallback edge.
- Final verification (WSL, by the session): ruff, format, mypy clean; `pytest` 440 passed; `pytest -m integration` 34 passed against a throwaway `postgres:18.6` on localhost:55432. Live dev run (risk high) still pending owner approval.
- Live dev run (owner approved, 2026-10-24): the shared dev server was not stopped; the service reached it through a local proxy that dropped connections on demand (`scratch/run_dev_boundary.sh`, retry delay 60 s). Owner sent a Spar receipt: one `postgres_unreachable` alert (`OperationalError`), no sender reaction, job 5 waiting in `chain_pending` with a one-line warning. After the connection came back, one recovery message, pass 1 ran once, and the pre-check ended the job `duplicate` (the receipt was already stored as `01a16a91-…`), so the sender got 🤝 rather than 👍. Owner confirmed both messages in Telegram.
- Owner accepted both review notes as they are (2026-10-24): a SQLite fault after the PostgreSQL commit ends the job `failed` although the receipt is stored, and the `internal_error` sender text does not ask for a resend.

## Plan Change Log

## Review Triage Log

Pass 1 (thorough: blind-hunter, edge-case-hunter, verification-gap, intent-alignment): high 0, medium 3, low 14, false 6, maybe-false 0.

- medium, patch: `internal:<final>` from a raise after the final state never recovers, hiding later faults of that key (blind, edge). `_finish` recovers `INTERNAL` for its state.
- medium, patch: the crash-after-commit test in `test_dedup.py` injects a psycopg error from the SQLite queue, which cannot raise one, so it proves only the wait path (verification-gap, intent). Model the crash with a `BaseException` escaping the loop.
- medium, patch: the three-starts guard is tested only by writing `step_starts` in SQL or calling `start_step` by hand (blind, intent). Drive it with a `BaseException` from a fake across reruns.
- low, patch: every wait logs a full traceback each cycle, unlike `_wait`'s one line (blind). Traceback only on the internal branch.
- low, patch: the guard's alert reason is a bare `RuntimeError`, the same as a bug (blind). Distinct reason, no synthetic raise.
- low, patch: the `pass1_json` fallback edge is missing from the AD-3 diagram (blind).
- low, patch: download-path `telegram_unreachable` alert text never asserted (verification-gap).
- low, patch: `internal:received` recovery never tested (verification-gap).
- low, patch: the outer `run_due` catch has no test (verification-gap).
- low, patch: dead `fakes.reference = None`, a local import, a contradictory `_with_sqlstate` comment (blind).
- low, reject: `test_texts.py` repeats the full strings; harmless duplication.
- low, reject: the AD-16 sentence lists the unreadable reference next to the PostgreSQL/Telegram alerts; the wording is the owner's approved text.
- low, reject: the sender text does not ask for a resend; the text is the owner's approved wording (raised with the owner).
- low, reject: a fault escaping the boundary leaves the job due now; bounded by the three-starts guard, needs a broken SQLite.
- low, reject: connect-ok/query-fails can flap `postgres_unreachable`; the frozen rule recovers on pipeline open.
- low, reject: classification is tested on built psycopg errors, not a live connection; the predicate follows the frozen definition.
- low, reject: a SQLite fault after the PostgreSQL commit ends the job `failed` while the receipt is stored; this is the owner's rule for any other error (raised with the owner).
- false: notification sends raise past `_finish` or inside a step: `Notifier._send` catches every exception.
- false: a PostgreSQL error after pass 1 repeats the paid call: `find_other_source` swallows `psycopg.Error`, and reference reads come before `generate`.
- false: `telegram_unreachable` stays on after a file reply: the next successful poll recovers it.
- false: waits never end and the guard cannot fire: waits without a deadline are the owner's rule; the guard is for crashes.
- false: SQLSTATE classes 53/40 and local OSError/SQLite errors should wait: the frozen block defines the wait classes.
- false: a permanent 401 on getFile waits forever: by the frozen rule it is a Telegram wait with an alert.

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
