---
title: 'Store the receipt total and expose it in resolver_v1'
type: 'feature'
ticket: '21'
created: '2026-10-24'
status: 'built'
baseline_revision: '2ebe922ca46bae8d005158b004ad18840d0228fd'
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

**Problem:** The receipt total (the value of goods since 1.20) is checked before the write but never stored, so the Resolver cannot read it and the spec's CAP-4 success ("the stored total is readable through the Resolver contract") is unmet.

**Approach:** Migration 0005 adds a not-null `receipts.total`, backfilled for rows already stored; the writer stores `NormalizedReceipt.total`; `resolver_v1.receipts` gains `total` as a decimal string; `resolver_v1` 1.1.0 (additive) is published in `docs/contracts/` and `docs/api-versions.md`.

## Boundaries & Constraints

**Always:** `total numeric(12,2) NOT NULL`, no DEFAULT (a writer that omits it fails loudly), no CHECK on sign. The view keeps every existing column in order and appends `total` last, rendered `total::text` like the other money columns. The migration is one file applied in one transaction; the view keeps its grants (replace, never drop).

**Decisions (owner, 2026-10-24):** Rows already stored get `total` = the sum of their settlement amounts, not of their stored lines, because stored lines drop returns. The contract's minor-release rule becomes "adding columns", since consumers name their columns and never `SELECT *`. The plan stays whole above 1600 tokens. Total is stored and part of `resolver_v1`. hitl false despite risk high; thorough review and the dev live run stay. Code is written by Antigravity (`agy`, `gemini-3.8-flash-high`) via `agy-delegate`, run from this session; checks, review, dev migrate and the dev live run stay with this session.

**Never:** No change to the receipt checks, plug-ins, pipeline, texts, `chains_v1`, `migrate.py`, or other `resolver_v1` views. No `resolver_v2`. No `loyalty_card_number` exposure. No edit to migrations 0001–0004.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New receipt | writer stores Kaufland-like receipt, total 78.13 | `receipts.total` 78.13; Resolver reads `"78.13"` | none |
| Coupon receipt | lines 2.80, card 2.00 + coupon 0.80 | total `"2.80"` via `resolver_v1.receipts` | none |
| Existing row, no return | stored before 0005: line 2.00, card 2.00 | after migrate total 2.00 | none |
| Existing row with a dropped return | stored line 5.00, settlements sum 3.00 (return 2.00 dropped) | total 3.00, Resolver reads `"3.00"` | none |
| Raw insert without total | INSERT omitting `total` | refused | `NotNullViolation` |

</frozen-after-approval>

## Code Map

- `migrations/0005_receipt_total.sql` (new) -- `ALTER TABLE retail_receipts_import.receipts ADD COLUMN total numeric(12,2)`; `UPDATE` setting `total` to the sum of `receipt_settlements.amount` for the `receipt_id` (every stored receipt has at least one settlement); `ALTER COLUMN total SET NOT NULL`; `CREATE OR REPLACE VIEW resolver_v1.receipts` with the 0004 select list unchanged plus `total::text AS total` after `buyer_name`. Comments say why, no ticket or CAP ids.
- `src/retail_receipts_import/adapters/postgres/receipts.py:37-42,170-194` -- add `total` to `INSERT_RECEIPT` and `_insert_receipt` (`receipt.total`).
- `tests/test_receipts_writer.py:236-258` -- the two raw INSERTs (`test_schema_enforces_both_unique_keys`, `test_schema_refuses_bad_chain_ids`) add `total`, else NOT NULL fires before the constraint they test. `:260-345` `test_round_trip_keeps_every_field_and_reference` selects and asserts `total` (6.30). Add a test: raw INSERT without `total` raises `NotNullViolation`.
- `tests/test_resolver_v1.py:241-298` -- header SELECT reads `total`, asserts `"2.80"`. Add a backfill test: copy `migrations/0001..0004` into `tmp_path`, `apply_migrations` there (with the `resolver_session`-style provisioning, or `migrate_conn`), raw-insert a receipt with stored line 5.00 and settlements summing 3.00, then `apply_migrations(REPO / "migrations")` and assert the backfilled total and its `resolver_v1.receipts` text.
- `docs/contracts/resolver_v1.md` -- Version 1.1.0; `total` row in `resolver_v1.receipts` (text, not null, 2 decimals, the value of goods, equal to the sum of the receipt's settlement amounts); reading rule 3 gains that `total` equals the settlement sum; the "left out of 1.0.0" note drops "amount-paid aggregations" from the list; Versioning: minor changes are "adding columns to views" (drop "optional or nullable"); a short change note for 1.1.0.
- `docs/api-versions.md` -- `resolver_v1` 1.1.0.
- `README.md` -- only if it names the view columns or 0004 as last migration (check, no other change).
- Reuse: `conftest.py` `migrate_conn`, `receipts_conn`; `test_resolver_v1.py` `ResolverSession`, `_receipt`, `_line`, `_card`.

## Tasks & Acceptance

**Execution:**
- [x] `migrations/0005_receipt_total.sql` -- column, backfill, not null, view -- storage and contract surface
- [x] `src/retail_receipts_import/adapters/postgres/receipts.py` -- store `total` -- writer
- [x] `tests/test_receipts_writer.py`, `tests/test_resolver_v1.py` -- matrix rows; each new assertion fails on the baseline
- [x] `docs/contracts/resolver_v1.md`, `docs/api-versions.md` -- 1.1.0
- [x] Orchestrator: WSL check suite and `pytest -m integration` on a throwaway `postgres:18.6`
- [ ] Orchestrator, owner approval: dev `migrate` as `rri_dev_owner`; a scratch script as `resolver_dev_reader` reads `total` of every dev receipt; then a dev-bot receipt (calls Gemini) shows its value of goods as `total`

**Acceptance Criteria:**
- Given a receipt written by the writer, when the Resolver role reads `resolver_v1.receipts`, then `total` is the value of goods as a 2-decimal string, and every pre-1.1.0 column reads as before.
- Given the dev database after migrate, when `resolver_dev_reader` reads `resolver_v1.receipts`, then each existing receipt has a total equal to its settlement sum, and a new dev-bot receipt shows its value of goods.
- Given `docs/`, when read, then `resolver_v1.md` and `api-versions.md` both say 1.1.0 and describe `total`.

## Implementation Notes

- Implemented by Antigravity (`gemini-3.8-flash-high`, accept-edits, no shell commands) from `scratch/agy-prompt.md`; it ran no checks. README needed no change.
- Orchestrator: reworded the 0005 backfill comment (agy's said settlements are "what was actually paid"; they are the value of goods). Extended the backfill test with a no-return receipt paid by card + coupon (2.00), so the matrix row "existing row, no return" and multi-settlement summing are covered; dict comprehensions for mypy; ruff format.
- Verification (WSL): ruff, format, mypy clean; `pytest` 503 passed; `pytest -m integration` 45 passed on a throwaway `postgres:18.6` (localhost:55432, container `rri-it-pg`).

## Plan Change Log

- Review pass 1 (no loopback): the Code Map said to drop "amount-paid aggregations" from the left-out note; review showed `total` is the value of goods, not the amount paid, so the contract keeps "the amount paid" under a renamed "Not exposed" note. Patched in place as a one-phrase doc correction.

## Review Triage Log

Thorough, pass 1 (blind-hunter, edge-case-hunter, verification-gap, intent-alignment): medium 2, low 3, false 10, maybe-false 0.

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | Backfill test has no `deposit_refund` settlement; a kind-filtered backfill passes (verification-gap) | medium | patch | Reproduced: with `AND s.kind <> 'deposit_refund'` in 0005 the test passed. Second case now card 1.00 + coupon 0.50 + deposit_refund 0.50; on the mutant it fails (1.50 ≠ 2.00), on 0005 it passes. |
| 2 | Dropping "amount-paid aggregations" implies the amount paid is exposed (blind, edge, intent) | low | patch | `total` includes deposit refunds (`check_total` sums all kinds), so it differs from the amount paid. Note now lists "the amount paid". |
| 3 | `total` row silent on deposit refunds and sign (blind, edge) | low | patch | Negative total is reachable: returns count in the value of goods and `stored_lines` needs only one purchase. Row now says refunds included, may be zero or negative. |
| 4 | "Left out of 1.0.0" heading stale; view comment says column order is a choice (blind) | low | patch | Heading → "Not exposed"; comment now gives the `CREATE OR REPLACE VIEW` rule and grant reason. |
| 5 | Versioning rule rewritten in the same release (blind, edge, intent) | false | reject | Owner decision 2026-10-24 in the frozen block. |
| 6 | Backfill NULL → SET NOT NULL fails for a receipt without settlements (blind, edge, intent) | false | reject | Unreachable: the only writer requires `settlements` `min_length=1` and inserts them in the receipt's transaction. |
| 7 | Database does not enforce total = settlement sum or sign (blind, edge, intent) | false | reject | Only the writer stores receipts and runs `check_total` first; the contract's other derived rules (rule 3) rest on the same writer checks. |
| 8 | Read-back test cannot catch a wrong `total` source (blind) | false | reject | Backfill view asserts "3.00" where stored lines sum to 5.00; writer round trip asserts 6.30, not the lines' sum. |
| 9 | Hard-coded `000[1-4]` glob, duplicated role setup (blind) | false | reject | Migrations 0001–0004 are never renumbered (frozen Never); `resolver_session` applies all migrations, so it cannot stage a pre-0005 schema. |
| 10 | `api-versions.md` lacks changelog link and date (blind) | false | reject | The row links the contract, which carries the Changes section; the table has no date column for any contract. |
| 11 | Tests do not prove the plug-in total is the value of goods (intent) | false | reject | Covered by 1.20's fixtures; checks and plug-ins are out of this intent. |
| 12 | CAP-4 fixtures (Müller, coupon, negative payout) not read through `resolver_v1` (intent) | medium | defer | Pre-existing: fixtures do not exist yet; recorded in `deferred-work.md`. |
| 13 | Dev migrate and live run absent from the diff (intent) | false | reject | Orchestrator steps after review, gated on owner approval. |
| 14 | Matrix row "Kaufland-like 78.13" has no test (intent) | false | reject | Round trip stores a total (6.30) that differs from its stored lines and reads it back; the value is incidental. |
| 15 | README not confirmed (intent) | false | reject | agy checked it; `README.md` names neither view columns nor 0004 as last migration. |

After patches (WSL): ruff, format, mypy clean; `pytest` 503 passed; `pytest -m integration` 45 passed on a throwaway `postgres:18.6`.

## Design Notes

`CREATE OR REPLACE VIEW` may only append columns, so `total` goes last; dropping the view would lose the Resolver's grant. The ADD → UPDATE → SET NOT NULL order lets 0005 run on a populated table without a DEFAULT that would later hide a writer bug.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all pass
- same with `uv run pytest -m integration` and `RRI_TEST_DATABASE_URL` at the throwaway database -- expected: all pass

**Manual checks:**
- Dev: `total` readable through `resolver_v1.receipts` as `resolver_dev_reader`; dev-bot receipt's total equals its value of goods.
