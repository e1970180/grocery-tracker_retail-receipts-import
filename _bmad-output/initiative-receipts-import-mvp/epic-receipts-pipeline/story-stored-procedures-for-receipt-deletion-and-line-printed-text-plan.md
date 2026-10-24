---
title: 'Stored procedures for receipt deletion and line printed-text updates'
type: 'feature'
ticket: '23'
created: '2026-10-24'
status: done
baseline_revision: 'b03e14c830e04bab31d76a6bc1ada6cda374d530'
route: 'full'
route_source: 'pinned'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** If a receipt was stored with incorrect details or needs removal, there is no atomic way to delete it while notifying `resolver_v1` via its feed. Furthermore, correcting OCR typos in `printed_text` requires manual SQL that risks bypassing data invariants or permissions.

**Approach:** Implement stored procedures in `retail_receipts_import`:
1. `delete_receipt(receipt_id uuid)` (and overload by `(chain_id, purchased_at)`): takes an EXCLUSIVE lock on `receipt_feed`, deletes the receipt (cascading lines and settlements), and inserts a `'deleted'` feed event.
2. `update_line_printed_text(line_id uuid, new_text text)` (and overload by `(receipt_id, line_no, new_text)`): safely updates `printed_text` of a receipt line with validation.
Document usage and lifecycle in `docs/resolver-integration.md`, add a migration `0006_admin_procedures.sql`, and cover with integration tests.

## Boundaries & Constraints

**Always:**
- `delete_receipt` serializes sequence assignment by locking `retail_receipts_import.receipt_feed` in `EXCLUSIVE` mode within its transaction.
- `delete_receipt` inserts exactly one `'deleted'` event into `retail_receipts_import.receipt_feed` for the deleted `receipt_id`.
- `update_line_printed_text` validates that `new_text` is non-null and non-empty after trimming.
- Non-existent IDs raise clear PL/pgSQL exceptions.
- Integration tests verify behavior against real PostgreSQL.

**Decisions (owner, 2026-10-24):**
- Variant A adopted: pure stored procedures in PostgreSQL without mandatory Python CLI wrappers.
- Stored procedure for updating line `printed_text` added alongside `delete_receipt`.
- Documentation on how to use these procedures added to `docs/resolver-integration.md`.
- Code written in this session using Gemini 3.8 Flash.

**Never:**
- No breaking changes to `resolver_v1` views or contract definitions.
- No direct table-level `DELETE` privilege granted to the service writer `rri_writer`.

## I/O & Edge-Case Matrix

| Scenario | Input | Expected Output / Behavior | Error Handling |
|----------|-------|---------------------------|----------------|
| Delete existing receipt by ID | Valid UUID of existing receipt | Receipt deleted; lines/settlements cascaded; feed records `deleted` | — |
| Delete existing receipt by chain & time | Valid chain and purchase timestamp | Receipt resolved and deleted; feed records `deleted` | — |
| Delete non-existent receipt | Unknown UUID or chain/time | Nothing modified | Raises exception `Receipt ... not found` |
| Update printed text by line ID | Valid line UUID and non-empty text | `printed_text` updated in `receipt_lines` | — |
| Update printed text by receipt ID and line no | Valid receipt UUID, line_no, non-empty text | `printed_text` updated in `receipt_lines` | — |
| Update printed text with empty text | Whitespace or NULL | Nothing modified | Raises exception `printed_text cannot be null or empty` |
| Update non-existent line | Unknown line UUID or line_no | Nothing modified | Raises exception `Receipt line ... not found` |

</frozen-after-approval>

## Code Map

- `migrations/0006_admin_procedures.sql` -- creates the stored procedures with overloads.
- `docs/resolver-integration.md` -- documents admin lifecycle management and stored procedure usage.
- `tests/test_admin_procedures.py` -- integration tests covering stored procedures execution and feed verification.

## Tasks & Acceptance

**Execution:**
- [x] Create `migrations/0006_admin_procedures.sql` with `delete_receipt` and `update_line_printed_text` procedures and overloads.
- [x] Add integration tests in `tests/test_admin_procedures.py` verifying deletion, cascading, feed events, text update, and error paths.
- [x] Update `docs/resolver-integration.md` with a detailed guide on using stored procedures and their impact on Resolver.
- [x] Run standard check suite in WSL (`ruff check`, `ruff format`, `mypy`, `pytest`, `pytest -m integration`).

**Acceptance Criteria:**
- Migration `0006_admin_procedures.sql` discovers and applies cleanly.
- `delete_receipt` removes receipt and inserts `'deleted'` event in `resolver_v1.feed`.
- `update_line_printed_text` updates `printed_text` in `resolver_v1.receipt_lines`.
- Both procedures raise descriptive errors on non-existent records or invalid input.
- Documentation in `docs/resolver-integration.md` accurately describes usage.
- All checks in WSL pass.

## Review Triage Log

Quick review, 2026-10-24:
- `migrations/0006_admin_procedures.sql`: Clean PL/pgSQL procedures, lock serialization on `receipt_feed`, cascading delete, input validation.
- `tests/test_admin_procedures.py`: 6 integration test cases covering happy and error paths, verified against real PostgreSQL 18.6 container.
- `docs/resolver-integration.md`: Added Section 8 detailing `delete_receipt` and `update_line_printed_text` signatures, internal mechanics, and Resolver consumer behavior.
- All checks pass cleanly.
