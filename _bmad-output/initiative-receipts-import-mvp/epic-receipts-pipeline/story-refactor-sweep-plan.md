---
title: 'Refactor sweep'
type: 'refactor'
ticket: '15'
created: '2026-10-24'
status: 'built'
baseline_revision: '4b928da8e81d2959bcfb3ba41bbe1d4fc943bb6d'
route: 'full'
route_source: 'auto'
risk: 'low'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The five chain normalizers each carry their own copy of the pass-2 schema guard, the purchase-time parser and the pass-1 time parser, differing only in the date and time regexes, and the settings docs have drifted from `Settings`: the README table lacks eight settings, `RRI_ALLOWED_USER_IDS` among them, and `.env.example` lacks four.

**Approach:** Move the shared parsing into `domain/chains/printed.py` and have each normalizer call it with its own regexes, keeping every chain's rules, regexes and error messages; bring the README table and `.env.example` in line with `Settings`.

## Boundaries & Constraints

**Always:** Every fixture test passes unchanged; error message texts stay as they are; each chain keeps its own DATE and TIME regexes (Müller refuses seconds on purpose, Spar refuses them too).

**Decision:** The Lidl normalizer builds its lines and settlements inside the model guard, as Kaufland, DM and Müller already do, so a malformed row is `UnreadableReceipt` (no_valid_result) instead of an internal error with receipt content in the log; this is the one accepted behavior change (owner, 2026-10-24).

**Decision:** Implementation is written by Gemini 3.8 Flash through agy from this plan (owner, 2026-10-24).

**Never:** No change to settlement building, change netting, line parsing, `_is_info` lists or plug-in classes; they differ per chain in checks and messages. No change to `app/`, adapters, migrations or contracts.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid receipt, each chain | recorded fixtures | same `NormalizedReceipt` as before | none |
| Two-digit year (DM, Kaufland) | `23.05.26` | year 2026 | none |
| Bad date or time | `32.13.2026`, `25:99` | pass 2 `UnreadableReceipt` with today's message; pass 1 `None` | as today |
| Schema-invalid response | not matching `*Pass2` | `UnreadableReceipt("response fails the schema (N errors)")` | as today |
| Lidl row failing `ReceiptLine` | e.g. quantity `0` | `UnreadableReceipt("receipt fails the model (N errors)")`, no receipt text in it | was a raw `ValidationError` |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/domain/chains/printed.py` -- shared helpers (`stripped`, `fold`, `money`, `quantity`, 4-digit `DATE`); add the new helpers here.
- `src/retail_receipts_import/domain/chains/{spar,lidl,kaufland,dm,mueller}/normalize.py` -- each has `normalize` opening with `XPass2.model_validate_json` in a `ValidationError` guard, a public `normalize_pass1_time(date, time)` and a private `_purchase_time(date, time)`, identical except: DM and Kaufland use a local `DATE` accepting `\d{2}|\d{4}` year (2-digit → `2000 +`); Spar `TIME` has two groups, the others take `group(1)`, `group(2)`; Müller `TIME` is `\d{2}:\d{2}` only.
- `src/retail_receipts_import/domain/chains/*/__init__.py` -- plug-ins delegate to `normalize` and `normalize_pass1_time`; not changed.
- `src/retail_receipts_import/config.py` -- `Settings`, the source of truth for the docs.
- `README.md:12-25` -- settings table; missing `RRI_ALLOWED_USER_IDS`, `RRI_GEMINI_BACKOFF_INITIAL_S`, `RRI_GEMINI_BACKOFF_CAP_S`, `RRI_IMAGE_MAX_PIXELS`, `RRI_TELEGRAM_POLL_TIMEOUT_S`, `RRI_JOB_RETRY_DELAY_S`, `RRI_JOB_MAX_ATTEMPTS`, `RRI_DATA_DIR`.
- `.env.example` -- missing `RRI_GEMINI_BACKOFF_INITIAL_S`, `RRI_GEMINI_BACKOFF_CAP_S`, `RRI_IMAGE_MAX_PIXELS`, `RRI_TEXTS_PATH`.
- Tests reach normalizers only through the plug-ins; none import their private names.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/domain/chains/printed.py` -- add `SHORT_YEAR_DATE` (the DM/Kaufland regex), `parse_pass2(model, response)` raising today's schema `UnreadableReceipt`, `purchase_time(date_re, time_re, date_text, time_text) -> datetime` raising today's two messages, and `pass1_time(date_re, time_re, date, time) -> datetime | None` returning the UTC time or `None` on any failure; a two-digit year group maps to `2000 +` -- one copy of rules that were five.
- [ ] `src/retail_receipts_import/domain/chains/{spar,lidl,kaufland,dm,mueller}/normalize.py` -- replace the local guard and both time functions with the helpers, keep `normalize_pass1_time` as a one-line public wrapper, keep each chain's `TIME` (and DATE choice); drop Spar's `as _x` import aliases -- same behavior, less code.
- [ ] `src/retail_receipts_import/domain/chains/lidl/normalize.py` -- move `_lines` and `_settlements` inside the model guard -- the decided fix.
- [ ] `tests/test_lidl_fixtures.py` -- a Lidl response with a quantity `0` item row through `LIDL.normalize` raises `UnreadableReceipt`; write it first and see it fail -- proves the fix.
- [ ] `README.md` -- add the eight missing rows with their defaults from `Settings` -- the docs match the code.
- [ ] `.env.example` -- add the four missing keys with their defaults -- same.
- [ ] `tests/test_printed.py` -- unit tests of the I/O matrix rows on the helpers (2- and 4-digit year, bad date, bad time, Müller-style regex refusing seconds, schema failure message) -- the helpers carry the rules now.

**Acceptance Criteria:**
- Given the refactored normalizers, when the full check suite and the integration tests run, then all pass with no fixture or existing test changed.
- Given `Settings`, when its fields are compared with the README table and `.env.example`, then every field appears in both.

## Implementation Notes

- Implemented by Gemini 3.8 Flash through agy (`accept-edits`, one run, no shell). The orchestrator then made `pass1_time` call `purchase_time` instead of repeating it, switched `parse_pass2` to PEP 695 type parameters (ruff UP047), and shortened a test comment (E501).
- The new Lidl test fails on the baseline normalizer with a raw `ValidationError` and passes after the fix.
- Verification (WSL): ruff, format, mypy clean; `pytest` 610 passed; `pytest -m integration` 45 passed on a throwaway `postgres:18.6` (localhost:55432, started from Windows Docker, removed afterwards); `tests/fixtures` unchanged.

## Plan Change Log

## Review Triage Log

- Pass 1 (quick): high 0, medium 0, low 2, false 0, maybe-false 0.
  - low, patch: README `RRI_ALLOWED_USER_IDS` row did not say "Required." though `config.py:44` has no default and `min_length=1`; added.
  - low, patch: README backoff rows omitted the misconfigured case and the doubling stated at `config.py:24-25`; reworded from that comment.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && ... ruff format --check && ... mypy && ... pytest'` -- expected: all green.
- Same with `uv run pytest -m integration` and `RRI_TEST_DATABASE_URL` set to the throwaway test database -- expected: green.
- `git diff --stat <baseline> -- tests/fixtures` -- expected: empty.
