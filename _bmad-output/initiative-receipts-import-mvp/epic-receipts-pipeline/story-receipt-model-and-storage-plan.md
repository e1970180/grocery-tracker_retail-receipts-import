---
title: 'Receipt model and storage'
type: 'feature'
ticket: '4a'
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

**Problem:** There is no receipt model, receipt schema or writer, so nothing extracted can be stored.

**Approach:** Add the one receipt shape in `domain`, the receipt schema, and a writer that stores a receipt in one PostgreSQL transaction and tells a first write, its own rerun and a duplicate apart. The model and schema cover every discount and settlement kind in the addendum, so later plug-ins add no migration.

**Decisions (owner, 2026-10-22):**
- The dedup key is the purchase timestamp to the minute for every chain; `zagreb_to_utc` truncates to the minute. The owner accepts that two purchases of one chain in the same minute collide. AD-8 is amended.
- The own-write lookup (AD-9) lives here, not in entry 7. A rerun of its own write violates both unique keys at once, so the writer cannot tell them apart from the error.

## Boundaries & Constraints

**Always:**
- `domain` has no I/O.
- Money is `Decimal` and `numeric(12,2)`.
- Zagreb-to-UTC conversion happens once, in `domain`.
- Receipt, lines, settlements and the feed row are written in one transaction.
- No personal data in git.

**Never:**
- Plug-ins, Gemini, the pipeline (4b); the pre-check (7); `resolver_v1` (14).
- No role names in migrations.
- No production database.
- Unmarked tests make no network call.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| MISMATCH | lines and settlements differ by 0,02 | check fails, nothing written | `items_settlement_mismatch` |
| WITHIN_TOLERANCE | difference of 0,01 | check passes, written | No error expected |
| DEDUP_HIT | same chain and minute already stored from another source | nothing new written | `duplicate` |
| OWN_WRITE | same source already stored | nothing new written | `own_write(existing receipt_id)` |
| ROLLBACK | failure injected after the lines insert | no receipt, line, settlement or feed row | exception propagates |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/config.py` -- add `db_statement_timeout_ms`, passed through conninfo `options`.
- `src/retail_receipts_import/domain/outcomes.py` -- `FailureReason.ITEMS_SETTLEMENT_MISMATCH`.
- `tests/conftest.py` -- `rri_env`, `block_network`, `pg_conn` (rolls back, refuses `grocery-tracker*`). Seed pattern in `tests/test_chains_reader.py`.
- Dev cluster -- `grocery-tracker-dev` on 192.168.100.218:5434, writer `rri_dev_writer`; story 2's default privileges cover new tables, sequences and types. Dev checks run from WSL scratch scripts.

## Tasks & Acceptance

**Execution:**
- [ ] `domain/receipt.py` -- `NormalizedReceipt`, `ReceiptLine`, `Settlement`, `PAYLOAD_VERSION`; `SettlementKind` (card, cash, bonus_points, coupon, deposit_refund); `DiscountKind` (none, included, separate_line); `zagreb_to_utc()` truncating to the minute; `check_consistency()`.
- [ ] `migrations/0002_receipts.sql` --
  - `receipts`: receipt_id uuid PK, chain_id, store_name, branch, purchased_at timestamptz, total, source_chat_id, source_message_id, created_at. Unique (chain_id, purchased_at) and unique (source_chat_id, source_message_id).
  - `receipt_lines`: PK (receipt_id, line_no), printed_text, quantity, unit, unit_price, printed_amount, discount_kind, discount_amount, discount_text, regular_amount, effective_amount.
  - `receipt_settlements`: PK (receipt_id, entry_no), kind, printed_text, signed amount.
  - `receipt_feed`: seq bigint identity, receipt_id unique.
- [ ] `adapters/postgres/receipts.py` -- `write_receipt(conn, receipt, source)` returning a closed result: stored, own write, duplicate. Look up the source, then the dedup key, then insert; a unique violation reruns both lookups. The caller supplies `receipt_id` and never inspects constraint names. The dedup-key lookup is its own function; entry 7's pre-check reuses it.
- [ ] `config.py`, `.env.example`, `README.md` -- the new setting.
- [ ] `tests/` -- unit tests for the model, `check_consistency` and `zagreb_to_utc` across both DST changes and seconds dropped; integration tests for the migration and each matrix row.
- [ ] `scratch/write_synthetic.py` -- as `rri_dev_writer`, writes a synthetic receipt (chat 0, message 1), reruns it, then writes it from chat 0, message 2; prints each result and the stored rows.

**Acceptance Criteria:**
- Given each matrix row, when the tests run, then the stated result holds.
- Given dev after `migrate`, when `scratch/write_synthetic.py` runs, then it prints stored, own write, duplicate, and one receipt and one feed row exist.
- Given the built image, when `zagreb_to_utc` runs inside it, then it succeeds; otherwise `tzdata` is pinned.
- Given a push, when CI runs, then the standard suite and integration tests pass.

## Implementation Notes

## Plan Change Log

- 2026-10-22 -- Owner moved the AD-9 own-write lookup from entry 7 into the tracer (added the OWN_WRITE row).
- 2026-10-22 -- Owner split entry 4 into this story and 4b (Spar receipt from PDF to dev), and set the minute dedup key.

## Review Triage Log

## Design Notes

- **Consistency.** Σ effective line amounts = Σ settlement amounts ± 0,01. Coupons and deposit refunds are positive entries, so a payout below zero is a negative cash or card amount.
- **Several discount lines on one item.** Their amounts are summed into `discount_amount` and their texts joined. No sample needs a child table.
- **The synthetic receipt stays in dev.** Its chain and minute must not match a Spar sample 4b will run live.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run <check>'` for ruff check, ruff format --check, mypy and pytest -- expected: all pass.
- `uv run pytest -m integration` against a throwaway `postgres:18.6` -- expected: migration and writer tests pass.
- `docker build`, then a `zagreb_to_utc` call in the image -- expected: no `ZoneInfoNotFoundError`.
