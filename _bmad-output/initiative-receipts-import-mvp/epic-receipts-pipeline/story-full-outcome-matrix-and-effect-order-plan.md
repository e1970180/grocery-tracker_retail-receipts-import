---
title: 'Full outcome matrix and effect order'
type: 'feature'
ticket: '12'
created: '2026-10-23'
status: 'ready-for-dev'
baseline_revision: 'ce462aacb18d1e2af7e7697c6e4f5ee19e5692c5'
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

**Problem:** Only a stored receipt tells anyone anything: duplicates, unsupported chains, failures, Gemini waits and refused content end silently, the admin never hears of a failure, and receipt files stay on the volume forever.

**Approach:** One notify module maps each final state (and failure reason) to its reaction, sender message and admin notice from the texts file; jobs run finish → notify → delete file for every final path; intake reports refused content from allowlisted private senders so the loop can react; a startup sweep deletes files of finished jobs.

## Boundaries & Constraints

**Always:**
- AD-11 order: PostgreSQL commit, SQLite final state, best-effort sends (client retry rules, then only logged), local file deletion. Each send is caught on its own; a failed one skips no other send and never changes job state.
- Every text and emoji comes from `texts/messages.toml`; no `parse_mode`, as store names are untrusted.
- Admin notices go to a new required setting `admin_chat_id`; they name the buyer, the job and, for an unsupported chain, the printed store name.
- File copy to the admin only for `items_settlement_mismatch`, `total_settlement_mismatch` and `no_valid_result`.
- In-progress reaction on a Gemini wait only when `job.waits == 0`, no queue schema change.
- Decision: implementation runs here, in the main session, on Opus 5.5 (owner, 2026-10-23).
- Decision: 👀 only for `unavailable`; a `blocked` wait sends no reaction (owner, 2026-10-23).
- Decision: 🙈 on every non-receipt message from an allowlisted private sender, text, `/start`, stickers and voice included, per the matrix (owner, 2026-10-23).
- Decision: a job ending `unsupported_chain` clears the message's reaction, so no 👀 is left (owner, 2026-10-23).

**Never:**
- No operational alerts or PostgreSQL error classification (entry 13).
- No queue schema change, no PostgreSQL migration, no texts-file key change.
- No reaction or reply to non-allowlisted senders, non-private chats or third-party (business, guest) messages.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Stored | write committed | 👍 | — |
| Duplicate | pre-check or writer | 🤝 + duplicate message | — |
| Unsupported chain | second unsupported | reaction cleared; sender message; admin message with store name | — |
| Mismatch / no valid result | failed with that reason | 👎 + reason message; admin reason + file copy | — |
| Oversize after getFile / unavailable download | failed, no file | 👎 + reason message; admin reason, no copy | delete is a no-op |
| Gemini unavailable | first wait in a state | 👀 once | — |
| Refused content | allowlisted private: text, sticker, other mime, size > 20 MB or unknown | 🙈 only, no job | sent after the offset commit |
| Send fails | any Telegram error | logged; state unchanged; file still deleted | — |
| Restart | final jobs with files left | sweep deletes them before the loop | missing file ignored |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/adapters/telegram/client.py` -- add `send_message(chat_id, text, reply_to=None)` (with `allow_sending_without_reply`), `send_document(chat_id, path, caption)`, and `set_message_reaction` accepting `None` to clear (empty `reaction` list); `_call` gains a multipart path (`files=`, form `data=`); caption cut to 1024.
- `src/retail_receipts_import/config.py` -- `admin_chat_id: int` required; update `tests/conftest.py`, `tests/test_config.py`, `.env.example`.
- `src/retail_receipts_import/domain/intake.py` -- `accept` returns `Accepted | NotAccepted | None`; `NotAccepted(chat_id, message_id)` only after `_authorized` and the third-party check.
- `src/retail_receipts_import/app/notify.py` (new) -- `Notifier(telegram, texts, admin_chat_id)`: `finished(job, path, store_name=None)`, `in_progress(chat_id, message_id)`, `not_accepted(chat_id, message_id)`; each Telegram call in its own try/except.
- `src/retail_receipts_import/app/jobs.py` -- `JobPorts.react_stored` → `notify`; `_finish` does finish → notify → `files.delete`; `_unsupported` takes the `Unsupported` result for `store_name`; `_wait` calls `in_progress` when `kind is UNAVAILABLE` and `job.waits == 0`.
- `src/retail_receipts_import/app/loop.py` -- `poll` enqueues accepted jobs, then sends `not_accepted` for refused ones; nothing escapes.
- `src/retail_receipts_import/adapters/files/store.py` -- `delete(path)`, `missing_ok`.
- `src/retail_receipts_import/adapters/queue/sqlite.py` -- `final_jobs()` returning finished jobs' `Accepted`, for the sweep.
- `src/retail_receipts_import/app/service.py` -- build `Notifier`, run the sweep before `loop.run`.
- Already true: `Texts` and `OUTCOMES_*` match the matrix; client retries 429 with `retry_after`, 5 attempts.
- Call sites of `JobPorts(...)` and `react_stored`: `tests/test_loop.py` (`Fakes`), `tests/test_dedup.py`, `app/service.py`.

## Tasks & Acceptance

**Execution:**
- [ ] `adapters/telegram/client.py`, `tests/test_telegram_client.py` -- the two sends, MockTransport tests of payload and of a 4xx not retried.
- [ ] `config.py`, `domain/intake.py`, `adapters/files/store.py`, `adapters/queue/sqlite.py` -- setting, `NotAccepted`, `delete`, `final_jobs`, with unit tests.
- [ ] `app/notify.py`, `app/jobs.py`, `app/loop.py`, `app/service.py` -- notify, effect order, sweep wiring.
- [ ] `tests/test_notify.py`, `tests/test_loop.py` -- a recording fake Telegram and the real texts file: one test per matrix row, two consecutive unavailable waits giving one 👀, a raising send leaving state final and the file deleted, the sweep.

**Acceptance Criteria:**
- Given each final state, when the job ends, then the sender and admin get exactly the matrix row's texts from the texts file, after the final state is persisted, and the local file is gone.
- Given every Telegram send raising, when a job ends, then its state is the same as with working sends.

## Implementation Notes

## Plan Change Log

## Review Triage Log

## Design Notes

Why `waits == 0` instead of a persisted flag: `waits` resets on each transition or attempt, so a later wait stretch re-sends the same 👀, which replaces an identical reaction and is invisible; a flag would need a queue upgrade for no visible gain.

Why deletion follows a failed admin copy: AD-11 makes deletion unconditional; Telegram keeps the original.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && ... ruff format --check && ... mypy && ... pytest'` -- expected: all green.
- The same with `pytest -m integration` on a throwaway `postgres:18.6` -- expected: green.

**Manual checks:**
- Optional dev-bot run by the owner: a receipt failing as `no_valid_result` brings the admin a file copy with its caption (multipart field names are not provable offline).
