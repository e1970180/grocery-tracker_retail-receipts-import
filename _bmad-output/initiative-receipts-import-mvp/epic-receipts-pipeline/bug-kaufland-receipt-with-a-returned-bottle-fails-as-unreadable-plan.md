---
title: 'Kaufland receipt with a returned bottle fails as unreadable'
type: 'bugfix'
ticket: '22'
created: '2026-10-24'
status: done
baseline_revision: '512a5393471cb3e3a71991287c6070f722802311'
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

**Problem:** On a Kaufland receipt with a returned beer bottle (`Boca za pivo * 4 * 0,16 -0,64`), the normalizer creates a sale line with a negative amount, which the receipt domain model rejects with `no_valid_result`.

**Approach:** Treat negative beer bottle lines as deposit refund settlements (`SettlementKind.DEPOSIT_REFUND`), analogous to `amb.` and `ambalaža` deposit refund rows, and reject unrecognized negative rows with a quantity.

## Boundaries & Constraints

**Always:** A negative Kaufland row matching `Boca za pivo` (or `amb.` / `ambalaža`) becomes a `deposit_refund` settlement with `amount = abs(refund_amount)`. Positive `Boca za pivo` lines remain sale lines. A negative row with a quantity that is not a known deposit refund raises `UnreadableReceipt` naming the row. The total is the value of goods (`Za platiti` + sum of all deposit refunds). Both `check_consistency` and `check_total` must pass with zero difference.

**Decisions (owner, 2026-10-24):**
- A returned beer bottle row (such as `Boca za pivo * 4 * 0,16 -0,64`) is treated as a deposit refund settlement (`SettlementKind.DEPOSIT_REFUND`), analogous to other `ambalaža` rows, settling part of the purchase.
- The printed informational line `Povratna naknada: 1,50` indicates government deposit included in beverages and continues to be ignored by `_is_info`.
- Code is written by a subagent using Gemini 3.8 Flash (High); review stays in the parent session.

**Never:** No migration, contract, `chains_v1`, pass-1, Gemini client or prompt/schema change. No change to Spar, Lidl, DM, or Müller normalizer behavior. No change to existing Kaufland fixtures or their `expected.json`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Returned beer bottles | `Boca za pivo * 4 * 0,16 -0,64` | `deposit_refund` settlement of 0.64 EUR | none |
| Bought beer bottle | `Boca za pivo * 1 * 0,16 0,16` | sale line with qty 1, price 0.16, amount 0.16 | none |
| Mixed deposit refunds | `amb.- staklo` -0.20, `ambalaža - PET` -0.40, `Boca za pivo` -0.64 | three `deposit_refund` settlements summing to 1.24 EUR | none |
| Real sample 20260427_231253 | 18 goods lines (sum 62.47), 3 deposit refunds (sum 1.24), Card 61.23 | total 62.47, settlements 62.47, lines 62.47; exact match | none |
| Unknown negative item with qty | `Nepoznati artikl * 2 * 1,00 -2,00` | — | `UnreadableReceipt` naming the row |
| Standard deposit row | `ambalaža - PET * 14 * 0,10 -1,40` | `deposit_refund` settlement of 1.40 EUR | none |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/domain/chains/kaufland/normalize.py:146-185` -- `_lines`: recognize negative `boca za pivo` rows as deposit refunds; keep positive `boca za pivo` rows as items; reject negative rows with a quantity that are not a known deposit refund with `UnreadableReceipt`.
- `tests/kaufland_samples.py` -- helpers for building synthetic Kaufland responses for tests.
- `tests/test_kaufland_fixtures.py` -- fixture and unit tests for Kaufland normalization: add tests for returned beer bottles, the full recorded pass-2 response of sample `20260427_231253.pdf`, and rejection of unknown negative items with quantity.

## Tasks & Acceptance

**Execution:**
- [x] `src/retail_receipts_import/domain/chains/kaufland/normalize.py` -- recognize negative bottle return rows as `deposit_refund` settlements and reject unknown negative item rows -- fixes unreadable receipt bug
- [x] `tests/test_kaufland_fixtures.py` -- add tests for returned bottles, sample `20260427_231253.pdf`, and unknown negative item rejection -- verifies fix and prevents regression

**Acceptance Criteria:**
- Given the recorded pass-2 response of sample `20260427_231253.pdf`, when normalized and checked, then lines sum to 62.47 EUR, settlements sum to 62.47 EUR (card 61.23 + deposit refunds 1.24), total is 62.47 EUR, and both consistency and total checks pass with 0 difference.
- Given an unknown item with a quantity and negative amount, when normalized, then `UnreadableReceipt` is raised naming the row text.
- Given all existing Kaufland fixtures and synthetic matrix tests, when the test suite runs, then all existing tests pass unchanged.

## Implementation Notes

- Implemented by subagent (`Gemini 3.8 Flash High`):
  - `src/retail_receipts_import/domain/chains/kaufland/normalize.py`: recognized negative `Boca za pivo` rows as deposit refund settlements (`SettlementKind.DEPOSIT_REFUND`), positive rows remain sale lines, unknown negative rows with quantity raise `UnreadableReceipt`.
  - `tests/kaufland_samples.py`: added `SAMPLE_20260427_231253_PASS2`.
  - `tests/test_kaufland_fixtures.py`: added unit tests covering returned bottles, mixed deposit refunds, standard deposit rows with quantity, unknown negative item rejection, and end-to-end normalization of sample `20260427_231253.pdf` against exact balance checks.
- Full check suite passed in WSL: ruff check, ruff format --check, mypy (strict), pytest (615 passed, 45 deselected).
- Review by quick lens: 0 findings.

## Plan Change Log

## Review Triage Log

Quick lens, 2026-10-24: verdict counts high 0, medium 0, low 0, false 0, maybe-false 0. No issues found.

## Design Notes

In Croatian retail (Kaufland), returnable glass beer bottles have a refundable deposit (kaucija, 0.16 EUR) printed as `Boca za pivo`. When bottles are returned at the store, the return slip or cashier entry prints `Boca za pivo * <qty> * 0,16 -<amount>` at VAT rate c. While regular government packaging deposit (povratna naknada, rate F) prints as `amb.- staklo` or `ambalaža - PET`, both function economically as deposit refunds against the purchase total.
