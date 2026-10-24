---
title: 'Lidl plug-in'
type: 'feature'
ticket: '8'
created: '2026-10-24'
status: 'ready-for-dev'
baseline_revision: ''
route: 'full'
route_source: 'auto'
risk: 'medium'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Pass 1 already names `lidl`, but no Lidl plug-in exists, so every Lidl receipt ends as `Unsupported`.

**Approach:** Add a `lidl` plug-in to `PLUGINS` (pass-2 schema, prompt, normalizer, pass-1 time hint and OIB read) that applies Lidl's printing rules, and prove it on recorded responses of six owner-supplied Lidl samples against owner-confirmed records.

## Boundaries & Constraints

**Always:** Gemini copies printed strings; the plug-in computes. A discount row (`POPUST XX%`, `Lidl Plus popust`, `Lidl akcija`) reduces the item printed above it as `separate_discount`. The footer `POPUST X,XX` after `za platiti`, the `Lidl Plus ušteda` box, the PDV table and `Pov. naknada` never enter lines or settlements; a bare `POPUST` row the model lists anyway, in lines or payments, is dropped. The branch is `PJ:`, falling back to the first `IBR:` segment, with leading zeros kept (`0198`). The purchase time is `Datum:` plus the time beside it (seconds dropped by `zagreb_to_utc`), never the card slip. No schema field asks for card-slip data. Owner approves the one-time live recording and confirms each `expected.json`.

**Decisions (owner, 2026-10-24):** Lidl Plus app screenshots only; a paper-photo fixture is deferred (`deferred-work.md`). Implementation is delegated to Antigravity (Gemini 3.8 Flash) in print mode, run from this session; review stays here. Lidl prints no shop name, only the legal entity, so the plug-in leaves `store_name` empty (`None`); it became optional in `2494b81` after the field audit (`research-receipt-field-audit/`). `store_address` and `receipt_number` are copied as printed.

**Never:** No migration, contract, `chains_v1` or `texts/messages.toml` change. No change to `pipeline.py`, `pass1.py`, the Gemini client or Spar's behavior. No other chain.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Item discount | `1 Kremšnita 3,29` then `POPUST 25% -0,83` | one line, printed 3.29, separate_discount 0.83, discount_text `POPUST 25%` | none |
| Footer trap | footer `POPUST 0,83` printed; model lists it in lines or payments anyway | dropped; receipt equals its record | none |
| Single item | `1 Kremšnita 3,29 C` | text `Kremšnita`, quantity 1; tax letter excluded | none |
| Weighed item | `Šljiva okrugla 3,77` with `0,946 kg x 3,99 EUR/kg` under it | quantity 0.946, unit kg, unit_price 3.99, printed 3.77 | none |
| Cash with change | `Novčanice 100,00`, `Ostatak novčanice -57,03` | one cash settlement 42.97 | change without one cash row is unreadable |
| Deposit return | `Otkup ambalaže -3,60 D` among the items | not a line and not a discount: a `deposit_refund` settlement of 3.60; `za platiti` stays the total | none |
| Price change | `Promjena cijene 0,00` under an item | dropped | non-zero: unreadable |
| Card | `Kartica 19,75` | card settlement 19.75 | unknown payment label is unreadable |
| Branch | `PJ: 0269`, `IBR: 0269/024832/05` | branch `0269` | neither readable as digits: unreadable |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/domain/chains/spar/{__init__,schema,prompt,normalize}.py` -- the pattern to follow; Spar's `_lines` (discount row attaches to the item above), `_settlements` (change off the single cash row), `_fold`, `_money`, `_quantity`, `normalize_pass1_time` carry over almost as is.
- New `src/retail_receipts_import/domain/chains/printed.py` -- move `MONEY`, `QUANTITY`, `DATE`, `_money`, `_quantity`, `_fold`, `_stripped` here (public names); Spar imports them, behavior unchanged.
- New `src/retail_receipts_import/domain/chains/lidl/{__init__,schema,prompt,normalize}.py` -- `LIDL = LidlPlugin()`, `chain_id="lidl"`. Schema: `seller_oib`, `pj`, `ibr`, `store_address` (the street line under `OIB…, PJ`, not the legal entity's address printed first); no store-name field, `store_name=None`; `receipt_number` (after `Br.rač.:`), `purchase_date`, `purchase_time`, `total` (`za platiti`), `lines`, `payments`. Time regex accepts `HH:MM` or `HH:MM:SS`. Cash labels `NOVCANIC`/`GOTOVIN`, change `OSTATAK` (printed negative, taken as its absolute value), card `KARTIC`.
- `src/retail_receipts_import/domain/chains/registry.py` -- `PLUGINS` gains `LIDL`.
- `tests/test_pass1.py:40`, `tests/test_pipeline.py:55` and its no-plug-in test -- use `dm` as the chain without a plug-in. `tests/test_pipeline.py:317` and `tests/test_loop.py:446` (Lidl answer against a Spar-only reference) must still give `other`.
- `app/alerts.py:60` alerts `missing plug-in` for every `PLUGINS` id absent from the reference: references in `tests/test_alerts.py:22,138` and `tests/test_loop.py` (`SPAR_ONLY`, `SPAR_WITHDRAWN`, defaults) gain a Lidl chain, or the expected alert texts change. Dev's reference already has `lidl` active.
- `tests/test_spar_fixtures.py` -- registry and card-field tests become chain-generic or get Lidl twins in `tests/test_lidl_fixtures.py`.
- `tests/fixtures/lidl/<Br.rač. first segment>/{pass1,pass2,expected}.json` -- six cases from `doc-inbox/fixtures/Lidl/`: `2003` (…183918389, POPUST 25%, card), `1465` (…184011934, Lidl akcija), `91418` (…183836022, cash with change, two weighed items), `31095` (…183944767, Lidl Plus popust on a weighed item, ušteda box), `297` (WhatsApp …11.23.49, three `Promjena cijene 0,00`), `94695` (WhatsApp …11.24.06, `Otkup ambalaže`, Lidl Plus popust, cash with change).
- `domain/receipt.py` -- `check_consistency` counts `deposit_refund`, `check_total` only card and cash, so `za platiti` 16,82 with cash 16,82 and refund 3,60 passes both. Do not change.
- `scratch/record_lidl.py` -- one call per pass per case (12 calls; mime `image/jpeg` for the WhatsApp files), skips recorded files, reference of all five chains as in `scratch/record_spar_pass1.py`, mime `image/png` through `images.prepare`.
- Do not change: `app/pipeline.py`, `domain/chains/pass1.py`, `adapters/`, `docs/contracts/`.

## Tasks & Acceptance

**Execution:**
- [ ] `domain/chains/printed.py`, `spar/normalize.py` -- move shared format helpers -- second plug-in reuses them
- [ ] `domain/chains/lidl/*` -- schema, prompt, normalizer, plug-in -- Lidl printing rules
- [ ] `domain/chains/registry.py` -- register `LIDL` -- makes Lidl supported
- [ ] `tests/test_lidl_fixtures.py`, `tests/lidl_samples.py`, updated pass-1/pipeline tests -- matrix rows on synthetic responses, time hint and OIB read -- offline proof
- [ ] `scratch/record_lidl.py` -- owner-approved live recording -- fixtures from the real API
- [ ] `tests/fixtures/lidl/*/expected.json` -- derive each from the image, owner confirms -- hand-verified records

**Acceptance Criteria:**
- Given the six recorded Lidl cases, when the fixture tests run offline, then each normalizes to its `expected.json` to the cent and the pipeline stores it with chain `lidl` from the recorded pass 1.
- Given the committed fixtures, when the card-data test runs, then no TID, MID, RRN, AID or card number appears.
- Given the Spar fixtures, when the suite runs after the helper move, then they pass unchanged.

## Implementation Notes

## Plan Change Log

## Review Triage Log

## Design Notes

Lidl prints a weighed item's amount on the name row and `qty kg x price EUR/kg` on the row under it; the prompt merges the two into one item entry. A single item prints `1 Name`; the prompt puts the `1` in quantity and strips it from text, as with `Name 2,99x 2`. Item discounts always carry text after `POPUST` (`POPUST 25%`) or are `Lidl Plus popust`/`Lidl akcija`, so a row whose folded text is exactly `POPUST` is the footer and is dropped; a synthetic test covers it in lines and in payments, since the recordings will likely not contain it.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all pass

**Manual checks:**
- Owner confirms the six `expected.json` against the images.
