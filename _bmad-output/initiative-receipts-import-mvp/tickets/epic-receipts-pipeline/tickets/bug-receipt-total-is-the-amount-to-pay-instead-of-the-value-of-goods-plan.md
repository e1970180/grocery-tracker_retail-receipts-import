---
title: 'Receipt total is the value of goods; exact settlement checks'
type: 'bugfix'
ticket: '20'
created: '2026-10-24'
status: done
baseline_revision: '612e2132d0d0db0238e2eec4a2068f254c0d197e'
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

**Problem:** On receipts with deposit refunds the total is the printed amount to pay, and `check_total` compares it with card plus cash only; both checks also forgive 0.01 EUR. So the total is wrong, a missing or misread deposit refund is invisible to the total check, and a 1-cent misread is written.

**Approach:** The total becomes the value of goods: Lidl and Kaufland set it to the printed amount to pay plus the deposit refunds they already collect. `check_total` compares the total with the sum of all settlements; both checks require an exact match. Mismatch texts are reworded; fixtures with deposit refunds get the new total.

## Boundaries & Constraints

**Always:** A plug-in derives the total as printed amount to pay + settlements printed outside it (today: `deposit_refund`), so a misread `Za platiti`/`za platiti` still fails `check_total`. Both checks return the signed difference when it is non-zero, else `None`. Sender `total_settlement_mismatch`: "Не удалось обработать чек: сумма товаров не сходится с суммой оплат. Администратор получил копию." Admin `total_settlement_mismatch`: "Стоимость товаров не сходится с суммой оплат (карта, наличные, тара, купоны, бонусы)." Admin `items_settlement_mismatch`: "Сумма позиций не сходится с суммой оплат." Fixtures without deposit refunds keep their `expected.json` byte for byte.

**Decisions (owner, 2026-10-24):** Code is written by Antigravity (`agy`, `gemini-3.8-flash-high`) via `agy-delegate`, run from this session; review stays here. Storing the total and exposing it in `resolver_v1` is entry 21, not this bug.

**Never:** No migration, contract, `chains_v1`, pass-1, Gemini client or prompt/schema change. No change to Spar's normalizer behavior. No new settlement kind. No `pass2.json` re-recording.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Kaufland deposits | 17582: `Za platiti 75,93`, cash 75,93, refunds 0,70+0,10+1,40 | total 78.13; both checks pass | none |
| Kaufland card + cash + deposits | 36863: `Za platiti 14,99` | total 16.39 | none |
| Lidl deposits | 94695: `za platiti 16,82`, refund 3,60 | total 20.42 | none |
| Refund beats purchase (synthetic) | lines 1,00, refund 3,00, `Za platiti -2,00`, cash -2,00 | total 1.00, cash -2.00 | none |
| Misread amount to pay | Lidl or Kaufland: lines and payments agree, amount to pay off by 0,01 | — | `check_total` returns ±0.01; pipeline `Invalid(TOTAL_SETTLEMENT_MISMATCH)` |
| Lines off by a cent | lines 2.00, card 2.01 | — | `check_consistency` returns -0.01; writer raises `ItemsSettlementMismatch`, nothing written |
| Total off by a cent | lines 2.00, card 2.00, total 2.01 | — | `check_total` returns 0.01; writer raises `TotalSettlementMismatch` |
| Exact match | lines 2.00, card 2.00, total 2.00 | written | none |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/domain/receipt.py:30-31` -- delete `TOLERANCE` and its comment. `:55-68` exception docstrings and `TotalSettlementMismatch` message: drop "beyond the tolerance", "card plus cash" → "settlements". `:260-282` `check_consistency` returns `difference or None`; `check_total` sums every settlement (no kind filter) and returns `difference or None`; docstrings say why (a real receipt agrees to the cent).
- `src/retail_receipts_import/domain/chains/kaufland/normalize.py:57` and `lidl/normalize.py:48` -- `total=money(raw.total, "total") + sum(r.amount for r in deposit_refunds)`; a one-line comment why. `deposit_refunds` is already in scope in both.
- `src/retail_receipts_import/app/pipeline.py:232` -- detail string → `"total minus settlements is {difference}"`.
- `texts/messages.toml:16,24,25` -- the three texts above.
- `tests/fixtures/kaufland/17582/expected.json`, `kaufland/36863/expected.json`, `lidl/94695/expected.json` -- `total` 78.13, 16.39, 20.42. No other fixture changes.
- `tests/test_receipt.py:184-204` -- replace the "one cent passes, two fail" tests with "exact passes, one cent fails" for both checks; the negative-card test now counts the coupon in the total (card -3 + cash 5 + coupon 1 → total 3.00 passes, 2.00 fails by 1.00 or similar).
- `tests/test_receipts_writer.py:98-120` (integration) -- mismatch tests use 0.01; `test_one_cent_difference_is_written` becomes exact match written and 0.01 refused.
- `tests/test_kaufland_fixtures.py:255-295` -- deposit matrix test asserts total 2.90; refund-beats-purchase asserts total 1.00. Add a Kaufland test: response whose `total` is off by 0,01 from card + cash → `check_total` == ±0.01.
- `tests/test_lidl_fixtures.py` -- same misread-amount-to-pay test on a Lidl synthetic response (`tests/lidl_samples.py` helpers); a deposit-row synthetic case asserting total = za platiti + refund.
- `tests/test_pipeline.py` -- one case: a Lidl or Kaufland response off by 0,01 ends `Invalid(TOTAL_SETTLEMENT_MISMATCH)`. `tests/test_loop.py:392-399` stays as is.
- Do not change: `spar/`, `pass1.py`, `adapters/` (writer already calls both checks), `docs/contracts/`, `migrations`.
- `_bmad-output/.../architecture-receipts-import/architecture-receipts-import.md:125,140` and `overview.html:86` -- orchestrator rewords: total is the value of goods; cash records the amount paid net of change; exact match, no ±0.01.

## Tasks & Acceptance

**Execution:**
- [x] `src/retail_receipts_import/domain/receipt.py` -- exact checks; `check_total` over all settlements -- core of the fix
- [x] `src/retail_receipts_import/domain/chains/{lidl,kaufland}/normalize.py` -- total = amount to pay + deposit refunds -- value of goods
- [x] `src/retail_receipts_import/app/pipeline.py`, `texts/messages.toml` -- detail string and owner texts
- [x] `tests/fixtures/{kaufland/17582,kaufland/36863,lidl/94695}/expected.json` -- new totals, hand-computed from the matrix
- [x] `tests/test_receipt.py`, `tests/test_receipts_writer.py`, `tests/test_kaufland_fixtures.py`, `tests/test_lidl_fixtures.py`, `tests/test_pipeline.py` -- matrix rows; each new test fails on the baseline
- [x] architecture doc and overview (orchestrator) -- reworded rule

**Acceptance Criteria:**
- Given the recorded fixtures, when the suite runs offline, then the three deposit cases hold their new totals, every other `expected.json` is unchanged, and every fixture's total equals both its settlements sum and its lines' effective sum exactly.
- Given the new tests, when run against `baseline_revision`, then each of the deposit total, 0.01-refusal and refund-beats-purchase tests fails; on the fix they pass.
- Given `texts/messages.toml`, when the service loads it, then it starts, and the three texts read as above.

## Implementation Notes

- Implemented by Antigravity (`gemini-3.8-flash-high`, accept-edits, no shell commands) from `scratch/agy-prompt.md`; it ran no checks.
- Orchestrator fix: two integration tests built receipts under the old rule (total = card + cash), missed by the Code Map: `test_receipts_writer.py::test_round_trip_keeps_every_field_and_reference` total -3.20 → 6.30, `test_resolver_v1.py::test_stored_receipt_read_back_field_by_field` total 2.00 → 2.80 (coupon now counts).
- Orchestrator: architecture rule (`architecture-receipts-import.md` extraction rule and `invalid` class) and `overview.html` reworded.
- Verification (WSL): ruff, format, mypy clean; `pytest` 502 passed; `pytest -m integration` 43 passed on a throwaway `postgres:18.6` (localhost:55432).
- Baseline proof (`scratch/baseline-new-tests.sh`, current tests on `612e213` source): 16 failed, covering the three deposit fixtures, both deposit matrix tests, refund-beats-purchase, both misread tests, the three exact-check tests and both pipeline tests.

## Plan Change Log

## Review Triage Log

Quick lens, pass 1: medium 1, low 1, false 0, maybe-false 0.

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | Lidl total adds only refunds from `lines`; an `OTKUP AMBALA` row the model puts under `payments` becomes a `deposit_refund` settlement but not part of the total, so `check_total` refuses a valid receipt | medium | patch | Reproduced: `test_deposit_return_among_payments_counts_in_the_total` got total 1.99, expected 5.59. Lidl now sums `deposit_refund` from the final settlements (`_refunded`); test passes. Kaufland has no refund branch in payments. agy print mode cannot be re-engaged, so the orchestrator applied it. |
| 2 | `brief-receipts-import.md:31` still states the ±0.01 EUR tolerance, contradicting the reworded architecture | low | patch | Read the line; reworded to the exact-match rule with the owner decision date. |

After patches (WSL): ruff, format, mypy clean; `pytest` 503 passed; `pytest -m integration` 43 passed on a throwaway `postgres:18.6`.

## Design Notes

With total = amount to pay + refunds, `check_total` reduces to amount to pay = card + cash on Lidl and Kaufland, so the misread check survives; on Spar (card/cash only) it is unchanged. `check_consistency` then guarantees lines = total. Müller bonus points will follow the same rule in its plug-in.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all pass
- same with `uv run pytest -m integration` and `RRI_TEST_DATABASE_URL` set to the throwaway dev database -- expected: writer tests pass

**Manual checks:**
- Owner confirms totals 78.13, 16.39, 20.42 match the goods sum on the three receipts. -- confirmed by the owner, 2026-10-24.
