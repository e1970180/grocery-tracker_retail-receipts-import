---
title: 'Job wait backoff, short poll and failed downloads'
type: 'feature'
ticket: '19'
created: '2026-10-23'
status: 'ready-for-dev'
baseline_revision: 'c621b0041d9f91832be44030e5d5192a2ddde9f2'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every Gemini wait is treated as the first, so a blocked Gemini is retried every 600 s forever. The settings binding in `serve` is untested. The long poll can hold a due job up to 30 s. A file Telegram no longer serves is retried forever and never ends.

**Approach:** Persist the wait count and feed it to `classify`. Build the pipeline ports and the loop settings in tested factories. Cap the long poll at the next due job. End a permanent download failure through the attempt limit as `failed` with `file_unavailable`.

## Boundaries & Constraints

**Always:**
- No queue schema change. `SCHEMA_VERSION` stays 2, using the `waits` and `attempts` columns entry 6 added.
- A wait writes `waits + 1`. Every transition, attempt and download failure resets `waits` to 0. An exception (`postpone`) leaves it as it is.
- `classify` gets the wait count persisted on the job when its step starts.
- A download failure consumes one attempt and keeps the job `received`, due after `job_retry_delay_s`. It ends as `failed` with `file_unavailable` at `job_max_attempts`. A successful download then resets attempts to 0, as it does today.
- `FailureReason.FILE_UNAVAILABLE = "file_unavailable"`, with texts copied exactly into `texts/messages.toml`:
  - sender: «Не удалось скачать файл из Telegram. Пришлите чек ещё раз.»;
  - admin: «Файл не скачивается из Telegram после всех попыток; копия не приложена.».
- Decision: a 401 is not the file's fault. A revoked bot token keeps the job on the generic retry with no attempt consumed; every other 4xx ends the file (owner, 2026-10-23).
- Decision: the plan stays whole at about 1,800 tokens (owner, 2026-10-23).
- Long-poll timeout = `clamp(ceil(next_due − now), 0, telegram_poll_timeout_s)`. With no waiting job it is the full timeout.

**Never:**
- No texts, reactions or admin copies sent, and no in-progress reaction (entry 12).
- No alerts and no PostgreSQL error classification (entry 13).
- No dedup pre-check (entry 7).
- No change to the AD-7 rules entry 6 implemented.
- No new retry inside the Telegram client.

## I/O & Edge-Case Matrix

| Scenario | State before | Result | State after |
|---|---|---|---|
| Gemini wait, no server delay | `waits` w | `ExtractionWait` | same state, due after `min(cap, initial·2^w)`, `waits` w+1 |
| Gemini wait with RetryInfo or Retry-After | `waits` w | `ExtractionWait` | due after the server delay, `waits` w+1 |
| Transition or attempt after waits | `waits` > 0 | next state | `waits` 0, the next wait uses `initial` |
| Step exception | `waits` w | exception | due after `job_retry_delay_s`, `waits` w |
| getFile or download 4xx, or no `file_path` | `received`, attempts a < limit−1 | `FileUnavailable` | `received`, attempts a+1, due after `job_retry_delay_s`, no pipeline opened |
| The same on the last attempt | attempts limit−1 | `FileUnavailable` | `failed`, `file_unavailable` |
| getFile or download 401 | `received` | `TelegramAPIError` | `received`, no attempt, due after `job_retry_delay_s` |
| 429, 5xx or network after the client's retries | `received` | `TelegramRetryExhaustedError` | `received`, no attempt, due after `job_retry_delay_s` (unchanged) |
| Next job due in 7 s, timeout 30 | — | poll | `getUpdates(timeout=7)` |
| A job due now or overdue | — | poll | `timeout=0` |
| No waiting job | — | poll | `timeout=30` |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/adapters/telegram/download.py` -- wraps a non-401 `TelegramAPIError` from `get_file` or `download_file` as `FileUnavailable` (`from` the original). A 401, `FileTooLarge` and `TelegramRetryExhaustedError` pass through.
- `src/retail_receipts_import/app/pipeline.py` -- `Classify` becomes `Callable[[GeminiCallError, int], Classification]`. `detect_chain` and `extract` take `waits` and pass it through `_with_gemini`.
- `src/retail_receipts_import/app/jobs.py`:
  - `advance(job, ports, max_attempts, retry_delay)`;
  - `advance` returns after the download unless the job is now `chain_pending`, so a retried download opens no pipeline (`_STEPS` has no `received` step);
  - `_wait` passes `job.waits + 1`;
  - `_download` catches `FileUnavailable`;
  - steps pass `job.waits` to the pipeline.
- `src/retail_receipts_import/adapters/queue/sqlite.py`:
  - `wait(..., waits=)`;
  - new `retry_download(job_id, due_at, now, *, attempts)`, which resets step starts and waits;
  - new `next_due_at() -> datetime | None` over non-final jobs, an aware UTC datetime (`fromtimestamp(x, UTC)`); a naive one would fail inside `poll` and read as a getUpdates failure.
- `src/retail_receipts_import/app/loop.py` -- `poll` computes the timeout from `next_due_at`. `run_due` passes `settings.retry_delay` into `advance`.
- `src/retail_receipts_import/app/service.py` -- new `pipeline_ports(settings, conn, generate) -> Ports`, used by `open_pipeline`, and new `loop_settings(settings) -> LoopSettings`, used by `serve`. Neither opens anything.
- `src/retail_receipts_import/domain/outcomes.py`, `texts/messages.toml` -- the new reason and its two texts. Already true, no change: `load_texts` requires a key for every `FailureReason` in both sections, and the Dockerfile copies `texts/` into the image.
- `src/retail_receipts_import/domain/jobs.py`, `config.py` -- fix the stale comments on `Job.waits`, `gemini_backoff_*` and `job_max_attempts`, which now covers downloads too.
- Reuse: `domain/extraction.classify` and `_backoff_s` stay unchanged. In `tests/test_loop.py`, `Fakes` and `FakeTelegram` gain a recorded `timeout`.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/adapters/telegram/download.py`, `tests/test_telegram_download.py` -- the 4xx wrap. Tests: a 400 from getFile and a 404 from the download raise `FileUnavailable`; a 401 raises `TelegramAPIError`; a 5xx raises `TelegramRetryExhaustedError`.
- [ ] `src/retail_receipts_import/domain/outcomes.py`, `texts/messages.toml` -- the reason and its texts.
- [ ] `src/retail_receipts_import/adapters/queue/sqlite.py` -- `wait` with the count, `retry_download`, `next_due_at`.
- [ ] `src/retail_receipts_import/app/pipeline.py`, `src/retail_receipts_import/app/jobs.py`, `src/retail_receipts_import/app/loop.py`, `src/retail_receipts_import/app/service.py`, `src/retail_receipts_import/config.py`, `src/retail_receipts_import/domain/jobs.py` -- wiring and the factory.
- [ ] `tests/test_loop.py`, `tests/test_queue.py`, `tests/test_service.py` -- every matrix row. Also:
  - `waits` survives a reopen;
  - a retried `FileUnavailable` never enters `open_pipeline` and logs no exception;
  - the poll-timeout rows run on a real `Queue`, not only on `Fakes`;
  - the factory test: initial 600, cap 1800, retry delay 900, pixel cap 100. `waits=0` gives 600 s, `waits=5` gives 1800 s, a 20×20 image comes back at no more than 100 pixels, and `loop_settings` gives `retry_delay == timedelta(seconds=900)`.

**Acceptance Criteria:**
- Given a blocked Gemini across three runs of the loop, when each run waits, then the delays are initial, 2×initial, then the cap.
- Given a file Telegram answers with 400 three times (limit 3), when the job runs each time it is due, then it ends `failed` with `file_unavailable`, three getFile calls, no Gemini call and no pipeline opened.
- Given the service is started with the new texts file, when it loads texts, then it starts, and a texts file without the `file_unavailable` key is refused.

## Design Notes

Why attempts reset after a download: a download failure and a Gemini result fail for different reasons, so a file fetched on its third try still gets every Gemini attempt.

Why a 400 from getFile does not end the job at once: Telegram answers "wrong file_id or the file is temporarily unavailable", which may pass. The attempts give the file about 20 minutes at the defaults.

Why the timeout is rounded up: the job is then at most 1 s late. Rounding down would wake the loop early with nothing due, and a fraction of a second would round to a zero-timeout poll repeated in a loop.

Why the factory test values all differ: `waits=0` alone cannot tell initial from cap, since `min(600, 1800) == min(1800, 600)`. That is why the test also checks `waits=5`.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && ... ruff format --check && ... mypy && ... pytest'` -- expected: all green.
- The same with `pytest -m integration` and `RRI_TEST_DATABASE_URL` set -- expected: green, unchanged.

## Implementation Notes

- Owner, 2026-10-23: plan approved and stopped at `ready-for-dev`; implementation resumes in a fresh `bmad-build` session.

## Plan Change Log

- 2026-10-23, advanced elicitation (edge sweep, failure modes, assumption audit, second-order, pre-mortem), applied with the owner's approval, frozen block included:
  - a retried download now returns from `advance` before the pipeline; `_STEPS` has no `received` step, so it would have raised `KeyError` after opening PostgreSQL;
  - `loop_settings` factory added, since `Ports` holds no retry delay;
  - `next_due_at` is aware UTC;
  - texts loader and Dockerfile marked as no change;
  - the getFile-400 rationale added.

## Review Triage Log
