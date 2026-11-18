---
title: 'Kaufland plug-in'
type: 'feature'
ticket: '9'
created: '2026-10-24'
status: done
baseline_revision: '0601390efd0d0acb5dfa33bf197e2e7f9f1697d8'
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

**Problem:** Pass 1 already names `kaufland`, but no Kaufland plug-in exists, so every Kaufland receipt ends as `Unsupported`.

**Approach:** Add a `kaufland` plug-in to `PLUGINS` (pass-2 schema, prompt, normalizer, pass-1 time hint and OIB read) applying Kaufland's printing rules, and prove it on recorded responses of owner-supplied Kaufland PDFs against owner-confirmed records.

## Boundaries & Constraints

**Always:** Gemini copies printed strings; the plug-in computes. The PDF prints the receipt twice: one copy is transcribed, once. `Kaufland Card% -X,XX` (with or without a space before `%`) reduces the item above as `separate_discount`; `Štedite NN% ili X,XX EUR!` marks the item above as already reduced: `included_discount` X,XX. Negative rows starting `amb.`/`ambalaža` are `deposit_refund` settlements (absolute value). The purchase time is the fiscal line `Datum:DD.MM.YY VrijemeHH:MM:SS` (two-digit year is 20YY), never the card slip `DATUM: YY/MM/DD`. Branch is the digits after `PJ`; when the receipt number's middle segment (`21833/5230/6`) disagrees, the receipt is unreadable. `Međusuma`, `Suma`, `Povratna naknada`, a `… HRK` conversion row, the PDV table, `Kaufland Card:` line and `* bez prava na popust` never enter lines or settlements. Payments: `Kartica` card, `Euro … EUR` cash, `Za vratiti` change taken off the single cash row when non-zero. No schema field asks for card-slip data. `store_name` is the text after `PJnnnn,` (`Zagreb Blato`), `store_address` the street line under it.

**Decisions (owner, 2026-10-24):** Implementation is delegated to Antigravity (`agy`, Gemini 3.8 Flash, High) in print mode, run from this session; review stays here. `Popust na kupnju -X,XX` is a `separate_discount` on the item above, like `Kaufland Card%`; Kaufland has no coupon fixture, which goes to `deferred-work.md`. The refund-beats-purchase case is proven by a synthetic test only; the real fixture goes to `deferred-work.md` until such a receipt appears. `Kaufland Card: xxxxx8265` is stored in `loyalty_card_number` as printed (masked).

**Never:** No migration, contract, `chains_v1` or `texts/messages.toml` change. No change to `pipeline.py`, `pass1.py`, the Gemini client, Spar's or Lidl's behavior. No other chain.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Card discount | `K.Voda 7L 2 * 1,45 2,90` then `Kaufland Card% -0,88` | qty 2, unit_price 1.45, printed 2.90, separate 0.88 | none |
| Shelf promo | `Pileće… 0,774 kg * 1,40 1,08` then `Štedite 30% ili 0,46 EUR!` | printed 1.08, included 0.46, unit kg | Štedite with no item above: unreadable |
| Purchase discount | `K.kamilica2x70 1,84` then `Popust na kupnju -0,37` | printed 1.84, separate 0.37, discount_text `Popust na kupnju` | none |
| Loyalty card | `Kaufland Card: xxxxx8265` | `loyalty_card_number` `xxxxx8265` | absent: None |
| Deposit return | `ambalaža - PET * 14 * 0,10 -1,40` | `deposit_refund` 1.40, not a line | none |
| Refund beats purchase (synthetic) | lines 1,00, refunds 3,00, `Za platiti -2,00`, cash `-2,00` | stored; total -2.00, cash -2.00 | none |
| Cash with change | `Euro EUR 50,00`, `Za vratiti 6,33` | cash 43.67 | change > 0 without exactly one cash row: unreadable |
| Split payment | `Kartica 4,99`, `Euro EUR 10,00`, `Za vratiti 0,00` | card 4.99, cash 10.00 | unknown payment label: unreadable |
| Branch mismatch | `PJ5230`, `Račun 21833/4430/6` | — | unreadable |
| Fiscal time | `Datum:25.02.26 Vrijeme12:33:51`, slip `12:33:46` | 2026-02-25 12:33 Zagreb → UTC | unreadable date/time: unreadable |

</frozen-after-approval>

## Code Map

- `domain/chains/lidl/{__init__,schema,prompt,normalize}.py` -- the pattern: `_lines` item/discount attachment, deposit rows, `_settlements` change-off-cash, error-count-only messages, `seller_oib` through the pass-2 model.
- `domain/chains/printed.py` -- reuse `MONEY`, `fold`, `money`, `quantity`, `stripped`; add nothing chain-specific.
- New `domain/chains/kaufland/{__init__,schema,prompt,normalize}.py` -- `KAUFLAND`, `chain_id="kaufland"`. Schema: `seller_oib`, `pj_line` (`PJ5230,Zagreb Blato` as printed), `store_address`, `receipt_number` (after `Račun`), `purchase_date` (`DD.MM.YY`), `purchase_time` (`HH:MM:SS`), `total` (`Za platiti`), `lines` (text, quantity, unit, unit_price, amount; a `Štedite` row's amount is the EUR saved), `payments` (text, amount), `loyalty_card` (value after `Kaufland Card:`, masked as printed). Weighed and multi-quantity items print the name on one row and `qty [kg] * price amount` under it: one entry. `normalize_pass1_time` accepts `DD.MM.YY` and `DD.MM.YYYY`.
- `domain/chains/registry.py` -- `PLUGINS` gains `KAUFLAND`.
- `tests/test_pass1.py:37-39` -- unsupported example becomes `dm`. `tests/test_alerts.py`, `tests/test_loop.py` references (`CLEAN_REFERENCE`, `SPAR_AND_LIDL`, `SPAR_WITHDRAWN`) gain a Kaufland chain (OIB `47432874968`) or `missing plug-in: kaufland` alerts appear; `tests/test_pipeline.py:54` already lists it.
- `tests/test_spar_fixtures.py::test_fixtures_hold_no_card_data` -- confirm it scans `fixtures/kaufland/`; the PAN/TID/MID/RRN/AID of the slips must not appear.
- `tests/fixtures/kaufland/<Račun first segment>/{pass1,pass2,expected}.json` -- `21833` (Card% + Štedite, card), `56414` (six Štedite, cash change, Povratna naknada), `17582` (three deposit rows, cash), `19996` (single item, branch 4430), `42126` (Card %, card), `67409` (QR over the first copy, cash 50,02), `13882` (`Popust na kupnju`), `36863` (card + cash, Štedite, deposits).
- `scratch/record_kaufland.py` -- copy of `scratch/record_lidl.py`: mime `application/pdf`, samples in `doc-inbox/fixtures/Kaufland receipts/`, skips recorded files; 16 calls.
- `domain/receipt.py` -- negative `total` and card/cash already allowed; `check_consistency` counts refunds and coupons, `check_total` only card and cash. Do not change.
- Do not change: `app/`, `domain/chains/pass1.py`, `adapters/`, `docs/contracts/`, `lidl/`, `spar/`.

## Tasks & Acceptance

**Execution:**
- [x] `domain/chains/kaufland/*` -- schema, prompt, normalizer, plug-in -- Kaufland printing rules
- [x] `domain/chains/registry.py` -- register `KAUFLAND` -- makes Kaufland supported
- [x] `tests/kaufland_samples.py`, `tests/test_kaufland_fixtures.py`, updated pass-1/alerts/loop tests -- every matrix row on synthetic responses, time hint, OIB read -- offline proof
- [x] `scratch/record_kaufland.py` -- owner-approved live recording -- fixtures from the real API
- [x] `tests/fixtures/kaufland/*/expected.json` -- written by hand from each PDF, not from normalizer output; owner confirms -- hand-verified records

**Acceptance Criteria:**
- Given the eight recorded Kaufland cases, when the fixture tests run offline, then each normalizes to its `expected.json` to the cent and the pipeline stores it with chain `kaufland` from the recorded pass 1.
- Given the committed fixtures, when the card-data test runs, then no PAN, TID, MID, RRN or AID appears.
- Given the Spar and Lidl fixtures, when the suite runs, then they pass unchanged.

## Implementation Notes

- Implemented by Antigravity (`gemini-3.8-flash-high`, accept-edits, no shell commands); the first run produced nothing because headless agy auto-denies shell commands, the rerun forbade them.
- Orchestrator fixes after the agy run: `Međusuma` was not dropped (`fold` keeps `Đ`, which has no NFKD decomposition), now matched as `ME(Đ|DJ|D)USUMA`; the prompt told the model to read only the first copy, wrong for `67409` whose first copy is covered by the QR code, now "once, the other copy for a covered row"; the invented address example replaced by `Jaruščica 6`; prompt lines rewrapped for E501; `record_kaufland.py` globbed by receipt number, which misses the two date-named samples, now an explicit file map.
- Recorded live with owner approval (2026-10-24): 16 calls, 8 cases.
- `expected.json` written by hand from the PDF text before comparing with the normalizer (`scratch/diff_kaufland.py`). All values matched to the cent on the first comparison; the only difference was the cash label, written `Euro` by hand against the printed `Euro EUR` the model copied, corrected to the printed form.
- The offline fixture test's placeholder skip for unrecorded cases was removed; a count test asserts all eight case folders exist.
- Live pass 1 of `42126` returned `26.02.2023` for the printed `Datum:23.02.26`, the card slip's `26/02/23` read as DD/MM/YY; pass 2 read the fiscal line right. Same class as Lidl case 2003.

## Plan Change Log

## Review Triage Log

Quick lens, pass 1: medium 1, low 3, false 0, maybe-false 0.

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | `ReceiptLine`/`Settlement` built outside the `ValidationError` guard in `kaufland/normalize.py`, so a raw error with receipt content reaches the loop's `log.exception` | medium | patch | Reproduced (`scratch/repro_kaufland_review.py`): `amb.- staklo * 0,00` and quantity `0` raised `ValidationError`; `pipeline.py:217` catches only `UnreadableReceipt`. Line and settlement building moved inside the guard; `test_line_model_errors_are_unreadable` covers both. Lidl has the same structure: deferred. |
| 2 | Lidl payment and deposit wording (`OSTATAK`, `NOVCANIC`, `GOTOVIN`, `OTKUP AMBALA`, deposit rows in payments) accepted on Kaufland | low | patch | Reproduced: `Gotovina` was accepted as cash. Deleted; the split-payment test now rejects `Gotovina`. |
| 3 | `tests/kaufland_samples.py` docstring says made-up values; the default header copies case 21833 | low | patch | Docstring corrected. |
| 4 | `test_pass1.py` lost its Kaufland assertion with no positive replacement | low | patch | Added `kaufland` supported when active. |

## Design Notes

`Štedite 30% ili 0,46 EUR!` follows an item already printed at the reduced price, so its EUR figure is `included_discount` and the regular amount is printed + 0,46; the percentage is ignored. `Kaufland Card%` follows an item printed at full price, so it is subtracted as with Lidl's `POPUST`. Lidl's expected records were generated from the normalizer and compared afterwards (its review finding 1); here they are written from the PDF first.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all pass

**Manual checks:**
- Owner confirms the eight `expected.json` against the PDFs. -- confirmed by the owner, 2026-10-24, except the `total` of 17582 and 36863: the owner ruled that `total` is the value of goods and the settlements, deposit refunds included, sum to it; that cross-chain fix is its own bug ticket.
