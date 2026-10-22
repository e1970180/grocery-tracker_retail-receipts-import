---
title: 'Spar receipt from PDF to dev'
type: 'feature'
ticket: '4b'
created: '2026-10-22'
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

**Problem:** There is no Gemini extraction, chain plug-in or pipeline.

**Approach:** Take one local Spar PDF to PostgreSQL. Pass 1 detects the chain against the chain reference, pass 2 reads the receipt, the Spar plug-in builds the `NormalizedReceipt`, and the 4a writer stores it.

**Decisions (owner, 2026-10-22):**
- Split: Telegram intake, queue, job states, loop and success reaction are a separate entry (`deferred-work.md`) carrying the dev-bot verify; this story is proven on a local Spar PDF.
- The Spar purchase time is the header's `Vaša kupnja dana DD.MM.YYYY. u HH:MM`, to the minute.
- Fixtures: samples …1402 (Joker), …0100 (cash with change), …7088 (cash and card), …2600 (deposit info, weighed lines). Each PDF goes to Gemini once. Only the recorded responses and hand-derived expected records are committed, and the owner confirms the records.
- Fallback seam if over budget: pass 1 as its own story.

## Boundaries & Constraints

**Always:**
- `domain` has no I/O.
- The model transcribes and the plug-in computes (AD-5): regular and effective amounts, cash net of change.
- The chain reference is read before each pass 1.
- Every Gemini call is a stateless `generate_content` with a response schema, the config model and timeout, and the lowest `thinking_level`.
- No PDF and no personal data in git. The response schemas never ask for card or terminal fields.

**Never:**
- Telegram, the queue, job states, the loop or reactions (the split-off entry); the classifier, retry timing or image preprocessing (5); waits or attempts (6); the pre-check (7); other plug-ins (8–11).
- No production database.
- Unmarked tests make no network call.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY_PATH | Spar PDF, reference has `spar` active | `Stored(receipt_id)` | No error expected |
| JOKER | item 1,99 then `Joker 15% -0,30` | regular 1,99, effective 1,69; `Vaša ušteda` ignored | No error expected |
| CASH_CHANGE | `GOTOVINOM 50,00`, `OSTATAK NOVCA 22,82`, total 27,18 | one cash settlement 27,18 | No error expected |
| MIXED | cash 1,89 and card 4,13 | two settlements | No error expected |
| DEPOSIT_INFO | `Povratna naknada 12 * 0,10 = 1,20` | not a settlement; the receipt balances | No error expected |
| NOT_SUPPORTED | pass 1 returns `other`, or a chain with no plug-in or not active | nothing written, no pass 2 | `Unsupported` |
| UNREADABLE | pass 1 `unreadable`, or a pass-2 date that cannot be parsed | nothing written | `Invalid(no_valid_result)` |
| GEMINI_ERROR | the SDK raises | nothing written | exception propagates, with no key in the message |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/config.py` -- add `gemini_model` (default `gemini-3.8-flash`) and `gemini_timeout_s`.
- `src/retail_receipts_import/domain/chains/__init__.py` -- `KnownChain`, `OTHER`, `UNREADABLE`, `is_chain_id`; registry and Spar package go beside them.
- `src/retail_receipts_import/adapters/postgres/chains.py` -- `read_chain_reference(conn)`, as is.
- `src/retail_receipts_import/domain/outcomes.py` -- `FailureReason.NO_VALID_RESULT`.
- `doc-inbox/fixtures/Spar + Interspar receipts/` -- source PDFs, git-ignored; `.gemma4.json` files are not ground truth.

## Tasks & Acceptance

**Execution:**
- [ ] `domain/chains/registry.py`, `domain/chains/spar/` -- `ChainPlugin` protocol (chain_id, pass-1 time hint, pass-2 prompt and schema model, `normalize_pass1_time`, `normalize`), the registry with `supported(reference)`, and the Spar plug-in.
- [ ] `domain/extraction.py` -- the pass-1 schema model (chain, store name, printed date and time) and the vocabulary prompt from the reference and the plug-ins' hints.
- [ ] `adapters/gemini/client.py` -- `generate(file_bytes, mime, prompt, schema) -> raw JSON`; log the response's model version; check against google-genai 2.32.0.
- [ ] `app/pipeline.py` -- `process_file(path, mime, source, ports) -> Stored | Duplicate | Unsupported | Invalid`; runs 4a's `check_consistency` before the write.
- [ ] `config.py`, `.env.example`, `README.md` -- the new settings.
- [ ] `tests/` -- unit tests with fake ports, one per matrix row; fixture tests from `tests/fixtures/spar/`: recorded pass-1 and pass-2 responses and expected records for the 4 samples, grepped for PAN and terminal fields before commit.
- [ ] `scratch/record_spar.py`, `scratch/ingest_local.py` -- the one-time live recording, and a live run of …2600 into dev as `rri_dev_writer` (chat 0, message 3), printing stored rows.

**Acceptance Criteria:**
- Given the recorded responses, when the fixture tests run offline, then each normalized receipt equals its owner-confirmed record to the cent.
- Given dev with 4a migrated, when `scratch/ingest_local.py` runs on …2600, then the stored receipt, lines and settlement match its record and the feed has one row for it.
- Given a push, when CI runs, then the standard suite passes.

## Implementation Notes

## Plan Change Log

- 2026-10-22 -- Owner moved the AD-9 own-write lookup from entry 7 to the tracer (now 4a).
- 2026-10-22 -- Owner split entry 4 into 4a and this story; `allowed_user_ids` went to the Telegram entry.

## Review Triage Log

## Design Notes

- **Spar traps.**
  - Branch is the middle segment of `Broj računa` (`3169/8714/103` → `8714`).
  - `Povratna naknada N * 0,10` is information only; the deposits are already in the line amounts.
  - Ignore `Vaša ušteda`, the VAT table, `KZP Markice`/`SMEG`, the card block and its `DATUM`/`VRIJEME`.
  - Weighed `kg(N)` lines are checked against the printed amount only.
- **The live-run receipt stays in dev.** The Telegram entry must send a different Spar sample, or it gets `Duplicate`.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run <check>'` for ruff check, ruff format --check, mypy and pytest -- expected: all pass.
