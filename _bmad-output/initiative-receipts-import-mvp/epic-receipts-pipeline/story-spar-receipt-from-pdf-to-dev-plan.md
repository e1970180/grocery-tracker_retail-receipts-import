---
title: 'Spar receipt from PDF to dev'
type: 'feature'
ticket: '4b'
created: '2026-10-22'
status: 'ready-for-dev'
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

**Approach:** Take one local Spar PDF, with its chain given by the caller, to PostgreSQL. Pass 2 reads the receipt, the Spar plug-in builds the `NormalizedReceipt`, and the 4a writer stores it.

**Decisions (owner):**
- Split: Telegram intake, queue, job states, loop and success reaction are a separate entry (`deferred-work.md`) carrying the dev-bot verify; this story is proven on a local Spar PDF (2026-10-22).
- The Spar purchase time is the header's `Vaša kupnja dana DD.MM.YYYY. u HH:MM`, to the minute (2026-10-22).
- Fixtures: samples …1402 (Joker), …0100 (cash with change), …7088 (cash and card), …2600 (deposit info, weighed lines). Each PDF goes to Gemini once for pass 2. Only the recorded responses and hand-derived expected records are committed, and the owner confirms the records (2026-10-22).
- Split: pass 1 (chain detection, the reference read before it, the supported-chain check) is its own story, together with the seller-OIB guard (`chains_v1` 1.1.0); see `deferred-work.md` (2026-10-23).

## Boundaries & Constraints

**Always:**
- `domain` has no I/O.
- The model transcribes and the plug-in computes (AD-5): regular and effective amounts, cash net of change.
- The plug-in sets `chain_id` from its own key, never from model text.
- Every Gemini call is a stateless `generate_content` with a response schema, the config model and timeout, and the lowest `thinking_level`.
- No PDF and no personal data in git. The response schemas never ask for card or terminal fields.

**Never:**
- Pass 1, the chain reference read, the supported-chain check, the seller-OIB guard (the pass-1 story).
- Telegram, the queue, job states, the loop or reactions (entry 17); the classifier, retry timing or image preprocessing (5); waits or attempts (6); the pre-check (7); other plug-ins (8–11).
- No production database.
- Unmarked tests make no network call.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY_PATH | Spar PDF, chain `spar` | `Stored(receipt_id)` | No error expected |
| JOKER | item 1,99 then `Joker 15% -0,30` | regular 1,99, effective 1,69; `Vaša ušteda` ignored | No error expected |
| CASH_CHANGE | `GOTOVINOM 50,00`, `OSTATAK NOVCA 22,82`, total 27,18 | one cash settlement 27,18 | No error expected |
| MIXED | cash 1,89 and card 4,13 | two settlements | No error expected |
| DEPOSIT_INFO | `Povratna naknada 12 * 0,10 = 1,20` | not a settlement; the receipt balances | No error expected |
| NO_PLUGIN | chain id with no plug-in | nothing written, no Gemini call | `Unsupported` |
| UNREADABLE | a pass-2 date or amount that cannot be parsed, or a response failing the schema | nothing written | `Invalid(no_valid_result)` |
| MISMATCH | lines or total do not balance with settlements | nothing written | `Invalid` with its mismatch reason |
| GEMINI_ERROR | the SDK raises | nothing written | exception propagates, with no key in the message |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/domain/receipt.py` -- reuse as is: `NormalizedReceipt`, `ReceiptLine` (`included_discount`/`separate_discount`), `Settlement`, `SettlementKind`, `zagreb_to_utc`, `check_consistency`, `check_total`, `telegram_source`.
- `src/retail_receipts_import/domain/chains/__init__.py` -- chain id helpers; the registry and `spar/` go beside it.
- `src/retail_receipts_import/adapters/postgres/receipts.py` -- `write_receipt(conn, receipt_id, receipt, source) -> WriteResult`; needs autocommit; `OWN_WRITE` maps to `Stored`.
- `src/retail_receipts_import/domain/outcomes.py` -- `FailureReason.NO_VALID_RESULT`, `ITEMS_SETTLEMENT_MISMATCH`, `TOTAL_SETTLEMENT_MISMATCH`.
- `src/retail_receipts_import/config.py` -- `Settings`; `gemini_api_key` exists.
- google-genai 2.32.0 (checked): `types.HttpOptions(timeout=<ms>)`, `types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)`, `GenerateContentConfig(response_mime_type="application/json", response_json_schema=...)`, `response.model_version`, `types.Part.from_bytes`.
- `doc-inbox/fixtures/Spar + Interspar receipts/` -- source PDFs, git-ignored; `.gemma4.json` files are not ground truth.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/domain/chains/registry.py` -- `ChainPlugin` protocol (chain_id, pass-2 prompt and schema model, `normalize`) and `PLUGINS` keyed by chain id.
- [ ] `src/retail_receipts_import/domain/chains/spar/` -- pass-2 schema (amounts as printed strings), prompt, and `normalize` applying the Design Notes traps; an unparseable value raises a domain `UnreadableReceipt`.
- [ ] `src/retail_receipts_import/adapters/gemini/client.py` -- `generate(data, mime, prompt, schema) -> str`; JSON schema from the pydantic model; logs `model_version`; never sets `thinking_budget` or `retry_options`.
- [ ] `src/retail_receipts_import/app/pipeline.py` -- `process_file(path, mime, chain_id, source, ports)` with ports for `generate` and the write; returns `Stored | Duplicate | Unsupported | Invalid`; balance checks run before the write.
- [ ] `config.py`, `.env.example`, `README.md` -- `gemini_model` (default `gemini-3.8-flash`), `gemini_timeout_s` (default 120), `gemini_thinking_level` (default `minimal`).
- [ ] `tests/` -- fake-port unit tests, one per matrix row; fixture tests over `tests/fixtures/spar/<last 4 digits>/{pass2,expected}.json`, grepped for PAN, `TID`, `MID`, `RRN` before commit.
- [ ] `scratch/record_spar.py`, `scratch/ingest_local.py` -- the one-time pass-2 recording (owner approves the four Gemini calls), and the live run of …2600 into dev as `rri_dev_writer` (chat 0, message 3), printing stored rows.

**Acceptance Criteria:**
- Given the recorded responses, when the fixture tests run offline, then each normalized receipt equals its owner-confirmed record to the cent.
- Given dev with 4a migrated, when `scratch/ingest_local.py` runs on …2600, then the stored receipt, lines and settlement match its record and the feed has one row for it.
- Given a push, when CI runs, then the standard suite passes.

## Implementation Notes

## Plan Change Log

- 2026-10-22 -- Owner moved the AD-9 own-write lookup from entry 7 to the tracer (now 4a).
- 2026-10-22 -- Owner split entry 4 into 4a and this story; `allowed_user_ids` went to the Telegram entry.
- 2026-10-23 -- Plan at about 2,200 tokens; owner split pass 1 into its own story and moved the seller-OIB guard there.
- 2026-10-23 -- Owner kept the narrowed plan at about 2,000 tokens (chars/4) and approved it.

## Review Triage Log

## Design Notes

- **Spar traps.**
  - Branch is the middle segment of `Broj računa` (`3169/8714/103` → `8714`); the whole value is `receipt_number`.
  - Store name is the printed store line (`INTERSPAR ARENA ZAGREB`), address the line under it.
  - A discount line (`Joker 15% -0,30`) under an item is that item's `separate_discount`.
  - Cash is the `GOTOVINOM` amount minus `OSTATAK NOVCA`; `PLAĆANJE <card>` is card.
  - `Povratna naknada N * 0,10` is information only; the deposits are already in the line amounts.
  - Ignore `Vaša ušteda`, the VAT table, `KZP Markice`/`SMEG`, the card block and its `DATUM`/`VRIJEME`.
  - Weighed `kg(N)` lines are checked against the printed amount only.
- **Expected records** are derived by hand from each PDF, not from the recorded response, and shown to the owner before commit.
- **The live-run receipt stays in dev.** The Telegram entry must send a different Spar sample, or it gets `Duplicate`.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run <check>'` for ruff check, ruff format --check, mypy and pytest -- expected: all pass.
