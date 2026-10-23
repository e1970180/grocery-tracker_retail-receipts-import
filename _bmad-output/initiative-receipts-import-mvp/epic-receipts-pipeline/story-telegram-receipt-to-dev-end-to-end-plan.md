---
title: 'Telegram receipt to dev end to end'
type: 'feature'
ticket: '17'
created: '2026-10-23'
status: 'built'
baseline_revision: '25177efd73cc5d4baebf15cb57ece0c815cf1917'
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

**Problem:** A receipt reaches the pipeline only from a local file. A family member's Telegram message is never read, queued or answered.

**Approach:** Vendor the Telegram reference pack into `adapters/telegram/`. Add a SQLite job queue that commits the `getUpdates` offset in the same transaction as the jobs. Run one loop that downloads each job's file, calls `process_file`, records the final state, and sets 👍 only after a stored result.

## Boundaries & Constraints

**Always:**
- Gate: allowlisted sender, private chat, `message_id > 0`. Content is a `photo`, or a `document` whose mime is in the domain list `ACCEPTED_MIME_TYPES` = JPEG, PNG, WebP, PDF.
- Declared size must be at most 20 MB.
- `allowed_updates=["message"]`.
- Intake makes no download. A filtered update still advances the offset.
- Order for a stored result: PostgreSQL commit, then the SQLite final state, then the reaction. A failed reaction is logged only.
- Keep the pack's guarantees: no `raise_for_status`, token redaction, poll read timeout, 20 MB check after `getFile`, attachment precedence.

**Never:**
- No not-accepted, duplicate or failure reactions or messages (entry 12).
- No `sendMessage` or `sendDocument`.
- No file deletion or startup sweep.
- No attempts, waits, shortened poll, step counter or alerts (entries 6 and 13).
- No production database.
- No change to `pipeline.py`, the Gemini client or the writer.

**Decisions (owner, 2026-10-23):**
- Executor: this session, Claude Opus 5.5.
- A job whose step raised is retried after `RRI_JOB_RETRY_DELAY_S` (default 600 s), through `due_at`; entries 6 and 13 replace this.
- The plan is kept whole at about 2,160 tokens.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Stored | allowlisted PDF, pipeline `Stored` | job `stored`, receipt_id kept, 👍 | reaction failure logged |
| Not allowlisted / group | any content | no job, offset advanced | none |
| Text, sticker, video, HEIC, size > 20 MB or unknown | allowlisted | no job, offset advanced, no reaction | none |
| Redelivered update | same chat:message_id | no second job | unique key |
| Duplicate / Unsupported / Invalid | pipeline result | `duplicate` / `unsupported_chain` / `failed` + reason, no notice | none |
| Oversize after `getFile` | job `received` | `failed`, `file_too_large` | none |
| Exception in a step | download or pipeline raises | job keeps its state, `due_at` = now + retry delay, logged without secrets, loop continues | not retried before `due_at` |
| Restart | jobs committed, offset N | `getUpdates(offset=N)`, open jobs resume | none |

</frozen-after-approval>

## Code Map

- Pack: `doc-inbox/telegram_core_reference.zip`.
  - Copy `client.py` as is. Add nothing to it.
  - From `intake.py`, keep only `select_message` and `_authorized`. Category 1 accepts text and video.
  - From `attachments.py`, keep `_largest_photo_size`, the size checks, `get_file`/`download_file` and the error mapping. The job saves the returned bytes through the file store.
  - Do not copy `polling.py`. Its offset file and reactions conflict with AD-2 and the outcome matrix.
  - Port `test_client.py`, `test_attachments.py` and the gate rows of `test_intake.py`. All imports become package-relative. The code must pass ruff and strict mypy.
- `src/retail_receipts_import/domain/intake.py` (new):
  - `ACCEPTED_MIME_TYPES` and `MAX_FILE_BYTES`.
  - A pure `accept(message, allowed_user_ids) -> Accepted | None`. `Accepted` carries chat_id, message_id, buyer name (`first_name` plus `last_name`), file_id, kind, mime and declared size. Photo mime is `image/jpeg`.
  - Entry 5 reads the same list.
- `src/retail_receipts_import/adapters/queue/sqlite.py` (new):
  - `jobs` table: job_id, chat_id, message_id, buyer_name, file_id, kind, mime, declared_size, state (text), failure_reason, receipt_id, due_at, updated_at. UNIQUE (chat_id, message_id).
  - One-row `offset` table. `PRAGMA user_version = 1`; refuse to open any other version.
  - `enqueue(accepted_list, next_offset)` in one transaction, `INSERT OR IGNORE`. Also `read_offset`, `due_jobs(now)` and `set_state`.
- `src/retail_receipts_import/adapters/files/store.py` (new) -- `path_for(chat_id, message_id, mime)` under `<data_dir>/files/`.
- `src/retail_receipts_import/app/jobs.py` (new):
  - The only writer of job state.
  - `received` → download → `chain_pending`.
  - `chain_pending` → `process_file` → final.
  - `Result` maps to state: `Stored`/`Duplicate` → `stored`/`duplicate`, `Unsupported` → `unsupported_chain`, `Invalid` → `failed` with its reason.
  - The `JobState` StrEnum lists all AD-3 states. 17 uses only those above.
- `src/retail_receipts_import/app/loop.py` (new):
  - Each pass: poll, enqueue, process due jobs, check `stop`.
  - Catches step exceptions per job, logs them redacted, and applies the retry policy.
  - Ports are fakeable: Telegram, queue, files, pipeline and clock.
- `src/retail_receipts_import/app/pipeline.py` -- reuse `process_file`, `Ports` and `Result` unchanged. Wire the ports as `scratch/ingest_local.py` does, with one autocommit `psycopg` connection per job, so a dropped connection never outlives a job.
- `src/retail_receipts_import/config.py`:
  - `allowed_user_ids: Annotated[list[int], NoDecode]` with a before-validator that splits on commas. `.env` already has `RRI_ALLOWED_USER_IDS`.
  - Add `data_dir` (default `/data`), `telegram_poll_timeout_s` (default 30) and `job_retry_delay_s` (default 600, > 0).
- `src/retail_receipts_import/__main__.py` -- `_run` builds the adapters and runs the loop until `stop`. Texts are loaded once, and `reactions[STORED]` is the success emoji.
- `.env.example`, `tests/conftest.py` -- add the new variables.
- Do not change: `pipeline.py`, `adapters/gemini/client.py`, `adapters/postgres/*`, `texts/messages.toml`.

## Tasks & Acceptance

**Execution:**
- [ ] `adapters/telegram/` and its ported tests -- vendor the kept parts -- one Telegram client (AD-15)
- [ ] `domain/intake.py` -- the gate and the accepted list -- pure, shared with entry 5
- [ ] `adapters/queue/sqlite.py`, `adapters/files/store.py` -- durable jobs and offset -- AD-1, AD-2
- [ ] `app/jobs.py`, `app/loop.py` -- states, step boundary, reaction order -- AD-3, AD-11, AD-14
- [ ] `config.py`, `__main__.py`, `.env.example` -- settings and wiring -- `run` serves the bot
- [ ] Tests with fake ports:
  - every matrix row;
  - an injected failure between the job insert and the offset write persists neither;
  - a restart: a fake client records the offset passed to `getUpdates`;
  - the allowlist parses `"358177329"` and `"1, 2"`.

**Acceptance Criteria:**
- Given the dev service with `RRI_ENV=dev`, when the owner sends a Spar PDF other than …2600 to the dev bot, then 👍 appears and the stored receipt matches its owner-confirmed record from 4b.
- Given the service is stopped after acknowledging updates, when it restarts, then no acknowledged update is fetched again and no job is lost.

## Implementation Notes

- 2026-10-23, implemented in this session (Claude Opus 5.5).
- `JobState`, `FINAL_STATES` and `Job` live in `domain/jobs.py`, not `app/jobs.py`: the queue adapter returns jobs and may import only `domain`. `app/jobs.py` stays the only code that changes state.
- The pack's gate (`select_message` and `_authorized`) and `largest_photo_size` moved into `domain/intake.py`, so the gate stays pure. `adapters/telegram/download.py` keeps the pack's getFile size checks, including the fallback to the declared size, and raises `FileTooLarge` or `FileUnavailable` instead of returning a status.
- `app/service.py` wires the adapters, so `__main__._run` only loads texts, logs readiness and calls `serve`. A queue file of an unknown version exits with 2.
- `FileStore.save` writes a temp file, fsyncs it and renames it before the job leaves `received`.
- Exception logs depend on the adapters' own redaction (Telegram client, `GeminiError`). The loop knows no secrets. The ported client tests cover the token redaction.
- A SIGTERM during the long poll waits up to the poll timeout; compose's 10 s grace may then SIGKILL. This is safe for durability: the offset is committed only with the jobs.
- `.env.example` and `rri_env` gained the new variables; the owner's `.env` already has `RRI_ALLOWED_USER_IDS`.
- WSL checks: ruff check, ruff format --check, mypy strict, pytest (191 passed) all pass. Integration tests were not run: no throwaway `RRI_TEST_DATABASE_URL`.
- A heredoc was used once to append tests to `tests/test_config.py`, against AGENTS.md; later edits used the edit tool.
- Correction: `select_message` was not kept. `accept` reads only `update["message"]`, because `allowed_updates=["message"]` and an edit would repeat a source already taken. Only `_authorized` came from the pack's `intake.py`.
- Review patches: `run_due` runs after a failed poll, `FileStore.save` fsyncs the directory, and the client test asserts token redaction. Checks pass again: 192 tests.

## Plan Change Log

## Review Triage Log

Quick pass 1: 0 high, 2 medium, 2 low, 4 false.

| # | Finding | Verdict | Route | Evidence |
| --- | --- | --- | --- | --- |
| 1 | AC 1 has no dev-bot live run | false | reject | Owner-gated live step, still pending; it needs separate approval because it calls Gemini. Not a code defect. |
| 2 | `_download` lets `TelegramAPIError`/`FileUnavailable` retry every 600 s forever | medium | defer | Real: a 4xx or pathless file keeps the job `received`, with one getFile call per retry and no Gemini call. The frozen matrix row "download raises → keeps its state, retry" prescribes this. Ending such jobs needs a failure reason and its texts, which belongs to the attempt and step-count rules of entries 6 and 13. |
| 3 | `live_photo` precedence dropped | false | reject | A live photo's `photo` field is its still image, the same receipt picture as `live_photo.photo`. Accepting either stores the same JPEG, so no wrong outcome follows. |
| 4 | Note claims `select_message` was kept | low | reject | The note is wrong: `accept` reads only `message`, which matches `allowed_updates=["message"]`. The fix is a plan edit; a correcting note is appended. |
| 5 | A failed poll skips `run_due` | medium | patch | Confirmed: `continue` skipped due jobs during a Telegram outage. `run_due` now always runs. `test_a_poll_failure_still_runs_due_jobs` fails on the old code. |
| 6 | `FileStore.save` does not fsync the directory | low | patch | Confirmed: the rename could be lost on a power cut after the SQLite commit, leaving `chain_pending` with no file. The directory is now fsynced after `os.replace`. |
| 7 | Redaction test does not check redaction | low | patch | Confirmed: the ported test asserted only attempts. It now asserts no token in the exception, its chain or the logs. |
| 8 | Heredoc used during implementation | false | reject | A process slip already disclosed; the diff has no heredoc and no code to change. |

## Design Notes

AD-2 limits the job row to the source reference, file_id, kind and declared size. The row also holds the buyer name and mime: `telegram_source` and `process_file` need them, and Telegram cannot return them later. One pipeline step stands in for `chain_pending` → `extract_pending` → `write_pending` until entry 6 splits it. Keeping `state` as text and setting `user_version` lets entry 6 add states and columns on the existing volume. HEIC is deferred because the pinned Pillow 13.0.0 does not open it without `pillow-heif`. This was checked.

## Verification

**Commands:**
- `wsl -- bash -l scratch/checks.sh` -- expected: ruff, format, mypy strict and pytest all pass.
- `uv run pytest -m integration` through the WSL wrapper, with a throwaway `RRI_TEST_DATABASE_URL` -- expected: pass, or reported as not run.

**Manual checks:**
- The dev-bot run calls Gemini live and needs separate owner approval. If a live answer diverges from the recorded fixture, stop and report.
