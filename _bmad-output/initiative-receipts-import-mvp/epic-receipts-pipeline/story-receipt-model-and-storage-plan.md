---
title: 'Receipt model and storage'
type: 'feature'
ticket: '4a'
created: '2026-10-22'
status: 'built'
baseline_revision: '568f2034cebc579ad4a47ecab4c2451bdb9bf051'
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

**Problem:** There is no receipt model, receipt schema or writer, so nothing extracted can be stored.

**Approach:** Add the one receipt shape in `domain`, the receipt schema, and a writer that stores a receipt in one PostgreSQL transaction and tells a first write, its own rerun and a duplicate apart. The model and schema cover every discount and settlement kind in the addendum, so later plug-ins add no migration.

**Decisions (owner, 2026-10-22):**
- The dedup key is the purchase timestamp to the minute for every chain; `zagreb_to_utc` truncates to the minute. The owner accepts that two purchases of one chain in the same minute collide. AD-8 is amended.
- The own-write lookup (AD-9) lives here, not in entry 7. A rerun of its own write violates both unique keys at once, so the writer cannot tell them apart from the error.

**Decisions (owner, 2026-10-23):**
- A receipt also stores its receipt number, store address, currency, masked loyalty card and buyer, because the Resolver needs them. The buyer comes from the source, not the image: for Telegram it is the sender's name. The currency column amends the architecture's "only EUR, no currency column" convention.
- The admin can delete a wrongly stored receipt so it can be resent. This amends the spec's "no manual-correction path". 4a only prepares the schema for it: cascades and a `deleted` feed event. The delete command itself is a later entry, after the Resolver contract.
- A receipt that holds only returns is not stored.
- Storno and return lines take part in the consistency check but are never stored. A storno, full or partial, is netted into the line it cancels; the database holds only purchased lines, so the Resolver never filters by line kind.
- The source reference is a source kind plus a reference text, so another messenger or a file needs no migration.
- A receipt line has its own `line_id`, a UUIDv7 generated in Python.
- PostgreSQL 18.6 or later everywhere.
- A second check: the printed total equals card plus cash ± 0,01, failing as `total_settlement_mismatch`. The total is then derivable from the settlements, so it is not stored.
- `chain_id` is never printed or model text: the model and the schema accept only a reference slug, never `other` or `unreadable`. The wrong-chain check by seller OIB belongs to the plug-ins (`chains_v1` 1.1.0).
- User-facing wording lives only in `texts/messages.toml`, so it can change without a code change. The items check text now says «с суммой оплат».

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
| TOTAL_MISMATCH | lines and settlements agree, total differs from card + cash by 0,02 | check fails, nothing written | `total_settlement_mismatch` |
| WITHIN_TOLERANCE | difference of 0,01 | check passes, written | No error expected |
| DEDUP_HIT | same chain and minute already stored from another source | nothing new written | `duplicate` |
| OWN_WRITE | same source already stored | nothing new written | `own_write(existing receipt_id)` |
| PARTIAL_STORNO | 3 pieces sold, 1 cancelled by storno | one line with quantity 2 and netted amounts stored | No error expected |
| OVER_STORNO | storno cancels more than the line holds | nothing written | `ValueError` from the model |
| RETURN_ONLY | only return lines | nothing written | `ValueError` from the model |
| ROLLBACK | failure injected after the lines insert | no receipt, line, settlement or feed row | exception propagates |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/config.py` -- `Settings.conninfo()`; add `db_statement_timeout_ms` (default 30000), passed as `options="-c statement_timeout=…"`.
- `src/retail_receipts_import/domain/outcomes.py` -- reuse `FailureReason.ITEMS_SETTLEMENT_MISMATCH`; add `TOTAL_SETTLEMENT_MISMATCH = "total_settlement_mismatch"`.
- `texts/messages.toml` -- the startup check needs a sender and an admin text for every failure reason.
- `src/retail_receipts_import/migrate.py` -- `SCHEMA`; the "conn must be in autocommit" docstring is the pattern for the writer.
- `src/retail_receipts_import/adapters/postgres/chains.py` -- style reference: module-level SQL, typed errors, `psycopg.Connection[tuple[Any, ...]]`.
- `tests/conftest.py` -- `pg_conn`, `block_network`; move `migrate_conn` here from `tests/test_migrate.py` and add `receipts_conn` on top of it (keeping its `grocery-tracker` dbname guard). It applies the repo migrations into a fresh schema per test (autocommit).
- Migrations never name roles; the writer role's privileges come from story 2's default privileges and are proven by the deferred dev check, not here.

## Tasks & Acceptance

**Execution:**
- [x] `src/retail_receipts_import/domain/receipt.py` --
  - `PAYLOAD_VERSION = 1`; `SettlementKind` (card, cash, bonus_points, coupon, deposit_refund).
  - `LineKind` (sale, storno, return). pydantic `ReceiptLine`: kind (default sale), cancels_line (1-based position of an earlier sale line; required on a storno line, forbidden on the others), printed_text, quantity, unit (optional), unit_price (optional), printed_amount, included_discount and separate_discount (default 0), discount_text (optional). A sale line has quantity > 0 and amounts and discounts ≥ 0; storno and return lines carry them as printed, negative quantity and amounts ≤ 0. `regular_amount` = printed + included and `effective_amount` = printed − separate are plain properties, not computed fields.
  - `Settlement`: kind, printed_text, signed amount. bonus_points, coupon and deposit_refund must be > 0; card and cash may be negative.
  - `NormalizedReceipt`: payload_version, chain_id (must pass `domain.chains.is_chain_id` and not be in `RESERVED_IDS`, so neither a printed name nor a pass-1 sentinel reaches storage), store_name, branch_number, receipt_number, store_address and loyalty_card_number (optional str, as printed; a branch number keeps leading zeros and may be alphanumeric, a loyalty card number may be masked), currency (`Literal["EUR"]`, default `"EUR"`), purchased_at, total, lines and settlements (both non-empty).
  - `stored_lines(receipt)`: adds each storno's quantity, printed_amount, included_discount and separate_discount to the sale line it cancels; printed_text, unit, unit_price and discount_text stay the sale line's. It drops lines netted to zero quantity and all return lines. A `NormalizedReceipt` validator rejects a `cancels_line` that is out of range, not earlier, or not a sale line; a netted line with a negative summed field or a negative effective amount (the schema CHECK, mirrored so a bad receipt fails in the model, not inside the write); a zero quantity with a non-zero amount or discount; and an empty `stored_lines`.
  - `SourceKind` (telegram) and `ReceiptSource`: kind, ref (non-empty str), buyer_name (non-empty str); `telegram_source(chat_id, message_id, buyer_name)` builds ref `"<chat_id>:<message_id>"`. Use `extra="forbid"`, money `Decimal` with max 12 digits and 2 places, quantity with max 12 digits and 3 places (PostgreSQL would round silently), and purchased_at aware UTC with zero seconds and microseconds.
  - `zagreb_to_utc(naive)` -> aware UTC truncated to the minute, rejecting aware input. `check_consistency(receipt) -> Decimal | None` returns the signed difference when its absolute value exceeds 0.01. `ItemsSettlementMismatch(difference)` is the domain error for it. `check_total(receipt) -> Decimal | None` does the same for total against Σ card and cash entries, with `TotalSettlementMismatch(difference)`.
- [x] `domain/outcomes.py`, `texts/messages.toml` -- the new failure reason. Sender: «Не удалось обработать чек: итог не сходится с оплатой картой и наличными. Администратор получил копию.» Admin: «Итог чека не сходится с суммой оплат картой и наличными больше чем на 0,01 EUR.» Reword `items_settlement_mismatch`, since that check now compares lines with settlements: sender «Не удалось обработать чек: сумма позиций не сходится с суммой оплат. Администратор получил копию.», admin «Сумма позиций не сходится с суммой оплат больше чем на 0,01 EUR.» All wording stays in `texts/messages.toml` only; code refers to texts by reason key and holds no user-facing wording.
- [x] Manual image check (no file unless it fails) -- build the image and call `zagreb_to_utc` in it once; on `ZoneInfoNotFoundError` pin `tzdata` in `pyproject.toml` and `uv.lock`.
- [x] `migrations/0002_receipts.sql` --
  - `receipts`: receipt_id uuid PK, chain_id text with CHECK `chain_id ~ '^[a-z][a-z0-9_]{0,31}$'` and NOT IN ('other', 'unreadable') (no FK, AD-18), store_name text, branch_number, receipt_number, store_address and loyalty_card_number (text NULL), currency text NOT NULL CHECK (= 'EUR'), purchased_at timestamptz, buyer_name text, source_kind text (no CHECK, so a new source needs no migration), source_ref text, created_at DEFAULT now(). Unique (chain_id, purchased_at) and unique (source_kind, source_ref); the receipt number is in neither.
  - `receipt_lines` (PK line_id uuid, unique (receipt_id, line_no)): the stored line fields without kind, plus regular_amount and effective_amount as `GENERATED ALWAYS AS (…) STORED` from printed and the discounts, so they cannot drift from their source; CHECK quantity > 0 and effective_amount ≥ 0; quantity `numeric(12,3)`, unit text NULL, unit_price NULL, discounts with CHECK ≥ 0.
  - `receipt_settlements` (PK receipt_id, settlement_no): kind (text + CHECK, not an enum type), printed_text, amount.
  - `receipt_feed`: seq bigint identity PK, receipt_id uuid with no FK, event text CHECK in ('stored', 'deleted'), unique (receipt_id, event). The writer inserts only `stored`.
  - Lines and settlements have an FK to receipts with ON DELETE CASCADE. Money is `numeric(12,2)`.
- [x] `src/retail_receipts_import/adapters/postgres/receipts.py` --
  - `write_receipt(conn, receipt_id, receipt, source) -> WriteResult` (kind stored, own_write or duplicate, with a receipt_id). It raises `ItemsSettlementMismatch` or `TotalSettlementMismatch` before any SQL when `check_consistency` or `check_total` fails, and never writes the total, and `ValueError` unless `conn.autocommit`, because a savepoint would report stored before the commit.
  - Order: `find_by_source`, then `find_by_dedup_key(conn, chain_id, purchased_at) -> StoredRef | None` (public, reused by entry 7; `StoredRef` holds receipt_id, source_kind and source_ref, so the pre-check can tell its own write from a duplicate), then one `conn.transaction()` with module-level helpers that insert the receipt, `stored_lines` (each with a `uuid.uuid7()` line_id), settlements and feed row, numbered from 1.
  - Catch only `errors.UniqueViolation`, outside the `with conn.transaction()` block so the rollback is done, then rerun both lookups once. If both miss, re-raise it.
- [x] `config.py`, `.env.example`, `README.md` -- the new setting. `tests/test_config.py`: the timeout reaches `conninfo()` (shared with `migrate`; 30 s is far above any migration here).- [ ] `tests/test_receipt.py` -- pricing with included, separate and both discounts, validators including the settlement and line-kind signs and a `chain_id` of `Spar`, `other` and `unreadable` rejected, `check_consistency` and `check_total` at 0.01 and 0.02 (`check_total` also with a mixed card and cash payment and a negative card amount), `stored_lines` for a full storno, a partial storno with a discount (asserting unit_price and printed_text are the sale line's), an over-storno, a `cancels_line` out of range or forward, a separate discount above the printed amount, a quantity with 4 decimals, a purchase with a return and a return-only receipt, `telegram_source`, a JSON round trip that compares equal, and `zagreb_to_utc` with seconds dropped. DST cases use hand-written literals: 2026-10-25 02:30 → 00:30Z (the first, summer occurrence) and 2026-03-29 02:30 → 01:30Z.
- [x] `tests/test_receipts_writer.py` (integration) -- one test per matrix row. DEDUP_HIT and OWN_WRITE assert that receipt and feed counts stay at 1. ROLLBACK patches the settlements helper and asserts every table is empty. The violation path patches the lookups to miss once; a second test makes them miss twice and expects the `UniqueViolation`. A non-autocommit `pg_conn` gets `ValueError`. The migration test checks both unique constraints and that a raw insert with chain_id `Spar` or `other` fails the CHECK. A round-trip test stores, then reads back by raw SQL, a receipt that has bonus points, a coupon, a deposit refund above the purchase with a negative card amount, lines with each discount type, a partial storno and a return, and every reference field and the buyer filled. The test checks every column, the generated regular and effective amounts, that storno and return lines are absent, and that line_no runs 1..n.

**Acceptance Criteria:**
- Given each matrix row, when the tests run, then the stated result holds.
- Given the built image, when `zagreb_to_utc` runs inside it (a manual check, recorded in Implementation Notes), then it succeeds.
- Given a push, when CI runs, then the standard suite and integration tests pass.

## Implementation Notes

- Verified in WSL: `ruff check`, `ruff format --check`, `mypy` (strict), `pytest` (65 passed), `pytest -m integration` (27 passed) against a throwaway `postgres:18.6` container. The container ran through Windows Docker Desktop, since the WSL distro has no Docker daemon.
- Image check: `docker build` succeeded; `zagreb_to_utc` gave 00:30Z for 2026-10-25 02:30 and 01:30Z for 2026-03-29 02:30 inside the image. No `tzdata` pin was needed. The scratch script was removed.
- Nullability: `branch_number`, `receipt_number`, `store_address` and `loyalty_card_number` are nullable in both the model and the schema. A duplicate or own write returns the id of the receipt already stored.
- Not verified here: the CI run on push, and the dev live check (deferred in `deferred-work.md`).

## Plan Change Log

- 2026-10-23 -- Owner accepted the plan size over the guideline and the reworded `items_settlement_mismatch` texts, kept in the texts file so wording changes need no code change.
- 2026-10-23 -- Owner chose to guard `chain_id` against OCR text and code mistakes: a slug and reserved-id validator in the model plus the same CHECK in `receipts`; the wrong-chain cross-check by seller OIB goes to the plug-ins through `chains_v1` 1.1.0 (`deferred-work.md`).
- 2026-10-23 -- Owner approved three renames from a naming review: `branch` to `branch_number`, `loyalty_card` to `loyalty_card_number`, `entry_no` to `settlement_no`; the feed table, `seq`, `kind` and `event` keep their names.
- 2026-10-23 -- Owner added the total check against card plus cash with its own failure reason and dropped the total column.
- 2026-10-23 -- Owner chose storno netted and unstored (partial storno included), a generic source reference, a Python `line_id`, and PostgreSQL 18.6+; architecture conventions and AD-9 amended, AGENTS.md updated.
- 2026-10-23 -- Owner chose to support deleting a stored receipt (cascades and a `deleted` feed event here; the command later) and not to store return-only receipts.
- 2026-10-23 -- Owner added receipt number, store address, currency, loyalty card and buyer after the comparison with the legacy schema.
- 2026-10-23 -- Owner split the dev live check (migrate plus the synthetic write as `rri_dev_writer`) into `deferred-work.md`, to run right after this build.

- 2026-10-22 -- Owner moved the AD-9 own-write lookup from entry 7 into the tracer (added the OWN_WRITE row).
- 2026-10-22 -- Owner split entry 4 into this story and 4b (Spar receipt from PDF to dev), and set the minute dedup key.

## Review Triage Log

Code review (quick), 2026-10-23: 7 findings; 5 patched, 2 rejected.

| Finding | Verdict | Evidence / action |
| --- | --- | --- |
| `test_receipt.py` task line runs into the previous bullet and stays unchecked | low | real, but the fix edits this build's plan; rejected |
| Pricing not unit-tested for included-only and separate-only lines | low | only the both-discounts case exists; patch, direct test addition |
| Round trip and STORED result never check the passed `receipt_id` | medium | the SELECTs omit `receipt_id`, `test_one_cent_difference_is_written` checks only `kind`; patch |
| Writer test docstring names the story's matrix | low | process reference banned by AGENTS.md; patch, reword |
| `Connection[Any]` instead of `Connection[tuple[Any, ...]]` | low | `fetchone()` is `Any`, so `_stored_ref`'s annotation is unchecked; patch |
| `test_pooled_transaction_connection_is_refused` names pooling it does not test | low | test uses plain non-autocommit `pg_conn`; patch, rename |
| CI on push and the dev live check unverified | false | not a defect in the diff: CI runs on push, the dev check is deferred by the owner; reported to the owner |

Plan review 2, 2026-10-23: 3 high, 6 medium, 7 low. Patched: storno netting names the summed fields; effective ≥ 0 mirrored in the model; quantity precision; catch placement; `find_by_dedup_key` returns the source; generated amount columns; `cancels_line` rules; missing tests (autocommit, re-raise, timeout, raw-SQL round trip); outcomes spec row; architecture ERD and AD-10. Rejected: the 4a ticket `verify` keeps the dev check, because a high-risk story needs that live evidence. Owner then accepted the size and the reworded mismatch texts.

Plan review, 2026-10-23: 1 high, 3 medium, 5 low; all patched in the plan.

| Finding | Verdict | Evidence / action |
| --- | --- | --- |
| A single discount kind cannot hold a Kaufland item with both `Štedite` and `Kaufland Card` | high | addendum Kaufland Discounts; replaced by included and separate amounts |
| `total` undefined | medium | defined in Design Notes; later checked against card plus cash and not stored (owner) |
| No storage test for the CAP-3/CAP-4 shapes | medium | added a round-trip integration test |
| Image check ordered before the domain code, and not automated | medium | moved after the domain task, marked manual |
| Settlement signs not enforced | low | added a validator per kind |
| Column types open | low | specified branch, quantity and nullability |
| `receipts_conn` guard | low | built on `migrate_conn` |
| `created_at` vs clock port | low | justified as a database audit column |
| Location of `ItemsSettlementMismatch` | low | placed in `domain/receipt.py` |

## Design Notes

- **Consistency.** Σ effective amounts of all printed lines, storno and returns included, = Σ settlement amounts ± 0,01. Stored lines therefore exceed the settlements when a receipt has a return; the Resolver contract must say so.
- **Storno netting.** A storno line repeats the cancelled quantity, amount and discounts with a minus sign, so summing quantity, amount and discounts gives the remaining purchase (texts and unit price come from the sale line): 3 pieces at 1,00 with 0,30 off, less 1 piece with 0,10 off, stores 2 pieces, 2,00, 0,20 off. Which sale line a storno cancels is the chain plug-in's reading. Coupons and deposit refunds are positive entries, so a payout below zero is a negative cash or card amount.
- **Discounts as two amounts, not a type.** One Kaufland item can carry both a `Štedite` discount (already in the price) and a `Kaufland Card` line (separate), so each is summed into its own column and the texts are joined. No sample needs a child table.
- **Total** is the printed amount payable, after bonus points, coupons and deposit refunds, so it equals card plus cash; it may be negative. It cannot replace the line check, because it is not the sum of the lines (Müller prints it after bonus points). All 208 legacy receipts with payments satisfy total = card + cash. The receipt stays in the SQLite job with its total; the database does not keep it, and the Resolver contract may expose card plus cash as the amount paid.
- **Reference fields.** Receipt number, address and loyalty card are nullable: a photo may not show them, and Lidl prints no card. They are never part of a key, since OCR misreads the receipt number. Currency is a one-value CHECK, so a second currency is a deliberate change.
- **Feed outlives the receipt.** The feed is a log, so it has no FK: a `deleted` event has to remain after its receipt is gone. The writer role never deletes, so it needs no DELETE grant for the cascade.
- **`created_at`** is a database-side audit time (`now()`), not domain time, so it does not go through the clock port.
- **DST.** The ambiguous autumn hour takes the first (summer) offset, which is Python's default `fold=0`. A nonexistent spring time takes the winter offset. No shop is open at 02:30.
- **Kinds as text + CHECK.** The writer needs no USAGE on enum types, and adding a kind is one constraint change.
- **The violation rerun** is reachable only if a second writer runs, such as a manual scratch run beside the service. It costs about five lines.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run <check>'` for ruff check, ruff format --check, mypy and pytest -- expected: all pass.
- `uv run pytest -m integration` against a throwaway `postgres:18.6` -- expected: migration and writer tests pass.
- `docker build`, then a `zagreb_to_utc` call in the image -- expected: no `ZoneInfoNotFoundError`.
