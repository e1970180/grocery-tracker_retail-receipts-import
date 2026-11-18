---
title: 'Operational alerts'
type: 'feature'
ticket: '13'
created: '2026-10-24'
status: done
baseline_revision: '383e5e577a40d22b30eb8fdfbcb0bd36fc18466e'
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

**Problem:** The admin never hears of an operational fault: a blocked Gemini, a Telegram outage or a chain reference out of step with the plug-ins shows only in the log.

**Approach:** An in-memory alert set over the closed AD-13 kinds, each sent to the admin once when it starts (with a reason) and once when it recovers, with texts from the texts file. This entry raises `gemini_config`, `telegram_unreachable` and `chain_reference`; the per-job error boundary raises `postgres_unreachable` and `internal:<state>` through the same alerts in its own entry.

## Boundaries & Constraints

**Always:**
- `AlertKind` in `domain`: `postgres_unreachable`, `gemini_config`, `telegram_unreachable`, `chain_reference`, `internal`; texts tables `[alerts]` and `[recoveries]` keyed by it, every key required.
- Alert key is the kind, or `internal:<state>` for `internal`; a key already active sends nothing; recovering an inactive key sends nothing.
- Admin text: texts-file line, then the key, then the reason (start only); no `parse_mode`.
- A failed alert send is only logged through `Notifier`; it never raises and the key stays active, so recovery is still sent.
- Reasons carry no secret and no receipt content: Gemini code/status/reason, Telegram exception type and method, chain ids, SQLSTATE.
- `chain_reference` is checked at startup and on every reference read: a plug-in id missing or inactive in the reference, rejected rows (the reader returns them for this alert), or an unreadable view (`ChainReferenceError`). Startup never blocks on it.
- Decision: implementation by Gemini 3.8 Flash in Antigravity, from a prompt written in this session (owner, 2026-10-24).
- Decision: the plan is split; the per-job error boundary goes to `deferred-work.md` (owner, 2026-10-24).

**Never:**
- No change to job handling, waits, `run_due` or the step-start counter (the boundary entry).
- No queue schema change, no PostgreSQL migration.
- No alert for a Gemini `unavailable` wait or for a receipt outcome; no persisted alert state.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Gemini blocked | `blocked` wait, twice | one `gemini_config` alert | — |
| Gemini back | next successful `generate` | one recovery | — |
| Telegram poll fails | `TelegramAPIError` / `TelegramRetryExhaustedError` from `get_updates`, twice | one `telegram_unreachable` alert | other poll errors only logged |
| Telegram back | next successful `get_updates` | one recovery | — |
| Plug-in missing / inactive | `spar` absent or in `inactive_ids` | one `chain_reference` alert naming it | the job path is unchanged |
| Rejected rows / view unreadable | `rejected` non-empty / `ChainReferenceError` | one `chain_reference` alert | error re-raised to the caller |
| Reference fixed | read with no fault | one recovery | — |
| Startup, PostgreSQL down | connect fails | logged, service starts | no alert here |
| Alert send fails | Telegram error | logged only | key stays active |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/domain/outcomes.py` -- add `AlertKind(StrEnum)`.
- `texts/messages.toml` -- `[alerts]`, `[recoveries]`, wording in Design Notes.
- `src/retail_receipts_import/app/texts.py` -- `Texts.alerts`, `Texts.recoveries: dict[AlertKind, str]`, loaded with `_section` over `set(AlertKind)`.
- `src/retail_receipts_import/app/notify.py` -- `Notifier.admin(where, text)`: one admin `send_message` through `_send`.
- `src/retail_receipts_import/app/alerts.py` (new) -- `Alerts(notifier, texts)`: `start(kind, reason, state=None)`, `recover(kind, state=None)`, `check_reference(reference) -> ChainReference` (faults against `domain.chains.registry.PLUGINS`, start or recover, returns the reference), `watch_generate(generate) -> Generate` (recover `gemini_config` after a call returns), `read_checked(read) -> ChainReference` (on `ChainReferenceError` start with its message and re-raise; otherwise `check_reference`).
- `src/retail_receipts_import/app/jobs.py` -- `JobPorts.alerts: Alerts`; `_wait` calls `alerts.start(GEMINI_CONFIG, ...)` when `wait.kind is BLOCKED`, reason from `wait.error` code/status/reason.
- `src/retail_receipts_import/app/loop.py` -- `run`: Telegram poll error → `alerts.start(TELEGRAM_UNREACHABLE, ...)`; `poll` recovers it right after `get_updates` returns.
- `src/retail_receipts_import/app/service.py` -- build `Alerts` once; `pipeline_ports(settings, conn, generate, alerts)` sets `read_chain_reference` through `alerts.read_checked`; `serve` passes `alerts.watch_generate(gemini.generate)` and, before `loop.run`, calls `jobs.check_reference(ports)`: opens the pipeline and reads the reference, logging any exception.
- Call sites: `JobPorts(...)` in `tests/test_loop.py` (`Fakes`), `tests/test_dedup.py`, `app/service.py`; `pipeline_ports` in `tests/test_service.py`; `Texts(...)` in tests, if any build it by hand.
- Reuse: `tests/test_notify.py` `RecordingTelegram`, `TEXTS`, `ADMIN`; `tests/test_loop.py` `BLOCKED`, `SPAR_ONLY`, `SPAR_WITHDRAWN`.

## Tasks & Acceptance

**Execution:**
- [x] `domain/outcomes.py`, `texts/messages.toml`, `app/texts.py`, `tests/test_texts.py` -- kinds and texts; a missing `[alerts]` key is refused.
- [x] `app/notify.py`, `app/alerts.py`, `tests/test_alerts.py` -- start once, recover once, failed send logged and recovery still sent, `internal:<state>` keys independent, every reference fault, `watch_generate`, `read_checked` re-raises.
- [x] `app/jobs.py`, `app/loop.py`, `app/service.py` -- hooks and wiring.
- [x] `tests/test_loop.py`, `tests/test_service.py`, `tests/test_dedup.py` -- call sites; two blocked waits give one alert; two failed polls then one good poll give one alert and one recovery; a non-Telegram poll error gives none; `pipeline_ports` reads the reference through the check.

**Acceptance Criteria:**
- Given a fault kind failing on every run and then working, when the loop runs, then the admin gets exactly one alert and one recovery for it.
- Given every Telegram send raising, when an alert starts, then the loop goes on and the job states are the same as with working sends.

## Implementation Notes

## Plan Change Log

## Review Triage Log

Pass 1 (quick lens, run by the owner in a separate Claude CLI session): high 0, medium 2, low 2, false 1, maybe-false 0.

- medium, patch: `chain_reference` was never run through the loop, so the matrix row "the job path is unchanged" had no test. Added `test_withdrawn_plugin_alerts_once_and_leaves_the_job_path_unchanged`: a startup check, two pass-1 reads, one alert, the job ends `unsupported_chain` as before, and a fixed reference sends one recovery.
- medium, patch: `jobs.check_reference` had no test, including the matrix row "Startup, PostgreSQL down". Added `test_startup_reference_check_with_postgres_down_only_logs`; the startup-fault case is covered by the test above.
- low, patch: the AC2 test never showed the loop going on after a failed alert send. Added `test_failing_alert_sends_do_not_stop_the_loop`: with every send failing, two failed polls and one good poll run, and the key recovers.
- low, patch: the `jobs.check_reference` docstring said what it does, not why (AGENTS.md). Rewritten to give the reason for the early check and for swallowing exceptions.
- false: the plan copy in the diff showed `status: 'done'` and no review. The diff was staged before step 04 set the frontmatter; the file on disk carries `in-review`, `quick` and `pinned`.

## Design Notes

Texts (Russian, admin-facing):

```toml
[alerts]
postgres_unreachable = "PostgreSQL недоступен, чеки ждут записи."
gemini_config = "Gemini отклоняет запросы из-за настройки (ключ, квота или модель), чеки ждут."
telegram_unreachable = "Telegram API недоступен."
chain_reference = "Справочник сетей не согласован с плагинами."
internal = "Внутренняя ошибка при обработке чека."

[recoveries]
postgres_unreachable = "PostgreSQL снова доступен."
gemini_config = "Gemini снова отвечает."
telegram_unreachable = "Telegram API снова доступен."
chain_reference = "Справочник сетей снова согласован с плагинами."
internal = "Внутренняя ошибка устранена."
```

Why all five kinds now: the texts file and the enum are closed sets checked at startup, so the boundary entry adds behaviour, not keys.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run <check>'` for `ruff check`, `ruff format --check`, `mypy`, `pytest` -- expected: all green.
- The same with `pytest -m integration` against a throwaway `postgres:18.6` -- expected: green.

**Manual checks:**
- Optional dev-bot run: set `active = false` on `spar` in the dev reference, restart, see one alert; set it back, send a receipt, see one recovery and the 👍.
