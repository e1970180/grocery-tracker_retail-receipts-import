---
title: 'PostgreSQL chain reference adapter for optional tax numbers and country code'
type: 'feature'
ticket: '2'
created: '2026-11-03'
status: done
baseline_revision: '6999c1dcd11864ba9b56235574361bb898eebe37'
route: 'full'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - '{project-root}/docs/contracts/chains_v1.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The adapter still reads `seller_oibs` from `public.chains_v1`, which `chains_v1` 1.2.0 no longer has; it also rejects chains without identifiers and ignores `country_code`.

**Approach:** Read `country_code` and `tax_numbers` instead of `seller_oibs`, validate rows by the 1.2.0 rules, and rename the field on `KnownChain`. The pipeline guard keeps its current behavior (only the field name changes there); relaxing it is the next ticket.

## Boundaries & Constraints

**Always:** Validation mirrors the contract: `country_code` is a non-NULL `^[A-Z]{2}$` string; `tax_numbers` NULL or empty means no identifiers (stored as `()`); otherwise a list of non-blank strings without commas, and for `HR` each exactly 11 ASCII digits. One bad row never fails the others.

**Never:** Change `app/pipeline.py` behavior, the contract, or the SQL. No new dependencies. No FK or country list lookup.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid HR | `HR`, 11-digit list | Active chain with both fields | None |
| No identifiers | NULL or `[]` | Chain with `tax_numbers == ()` | None |
| Non-HR free format | `DE`, `["DE123"]` | Accepted | None |
| Bad HR number | `HR`, `["12345"]` | Rejected `bad_tax_numbers` | Reported |
| Blank/NULL/comma element | `["", " "]`, `["a,b"]` | Rejected `bad_tax_numbers` | Reported |
| Bad country | `hr`, `HRV`, `""` | Rejected `bad_country_code` | Reported |
| NULL country | NULL | Rejected `null_field` | Reported |
| `tax_numbers` served as text | text column | Rejected `bad_tax_numbers` | Reported |
| Non-str country / non-list or nested tax_numbers / non-str element | `length()` int, scalar, 2-D array | Rejected `bad_country_code` / `bad_tax_numbers` | Reported |
| Padded non-HR element | `DE`, `[" DE1"]` | Accepted (only blank is banned) | None |
| HR mixing valid and invalid | `HR`, one good, one short | Rejected `bad_tax_numbers` | Reported |
| Both bad | bad country and bad tax numbers | `bad_country_code` wins (checked first; the HR rule depends on it) | Reported |

Fault order: slug, reserved, name, active, NULL country, aliases, country format, tax numbers. NULL `tax_numbers` is not a fault.

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/domain/chains/__init__.py` -- `KnownChain`: becomes `chain_id, display_name, aliases, country_code, tax_numbers` (view column order).
- `src/retail_receipts_import/adapters/postgres/chains.py` -- `QUERY`, `RejectReason` (`BAD_OIBS` -> `BAD_TAX_NUMBERS`, add `BAD_COUNTRY_CODE`), `_validate`, `_row_fault`.
- `src/retail_receipts_import/app/pipeline.py:237` -- rename `seller_oibs` to `tax_numbers` only; keep logic.
- `tests/test_chains_reader.py` -- `_add_unchecked_rows` and view-rewrite tests use `seller_oibs`; edge cases go here (integration, seeded from `docs/contracts/chains_v1.sql`).
- `tests/test_chains_reader.py` details: unchecked table/view/INSERT widen to 6 columns; `empty_oibs` and `null_oibs` rows become accepted (no longer rejected); three view rewrites and `test_text_seller_oibs_column_is_rejected_not_split` rename to `tax_numbers`.
- `docs/adding-a-chain.md:75,287` -- still say `seller_oibs` / 11-digit OIBs; update to `country_code` and optional `tax_numbers`.
- `_row_fault` gains a parameter; if ruff flags too many arguments, pass the row tuple instead of adding a suppression.
- Known gap until the next ticket: `pipeline.py` still rejects every receipt of a chain with empty `tax_numbers`.
- `KnownChain(...)` positional calls in `tests/test_{alerts,dedup,dm_fixtures,kaufland_fixtures,lidl_fixtures,loop,mueller_fixtures,pass1,pipeline,spar_fixtures}.py` -- insert `"HR"` as 4th argument.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/domain/chains/__init__.py` -- add `country_code`, rename `seller_oibs` to `tax_numbers` -- matches the view
- [ ] `src/retail_receipts_import/adapters/postgres/chains.py` -- new query columns, reasons and checks; NULL `tax_numbers` becomes `()` -- contract 1.2.0
- [ ] `src/retail_receipts_import/app/pipeline.py` -- field rename only -- keeps the build green
- [ ] `docs/adding-a-chain.md` -- replace the two stale mentions -- doc parity
- [ ] `tests/test_*.py` listed above -- add `"HR"` argument -- mechanical
- [ ] `tests/test_chains_reader.py` -- cover the matrix rows; seeded spar equals `KnownChain("spar", ..., "HR", ("46108893754",))` -- ticket verify

**Acceptance Criteria:**
- Given the 1.2.0 seed, when the reference is read, then five HR chains load with their OIBs and nothing is rejected.
- Given rows with NULL, empty, non-HR or malformed values, when read, then only the malformed ones are rejected with the reason in the matrix.
- Given `uv run ruff check`, `ruff format --check`, `mypy` and `pytest` (unmarked), when run in WSL, then all pass.

## Implementation Notes

## Plan Change Log

## Review Triage Log

- Quick lens, 1 finding. Fault order: NULL `country_code` checked after aliases, plan says before. Verdict low, real; patched (NULL check moved up) with a test. Nothing deferred.
- Integration tests in `test_chains_reader.py` were updated but not run: no `RRI_TEST_DATABASE_URL` in this environment.

## Verification

**Commands:**
- `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest` -- expected: all pass (WSL)
- `uv run pytest -m integration tests/test_chains_reader.py` -- expected: pass against a throwaway PostgreSQL via `RRI_TEST_DATABASE_URL`
