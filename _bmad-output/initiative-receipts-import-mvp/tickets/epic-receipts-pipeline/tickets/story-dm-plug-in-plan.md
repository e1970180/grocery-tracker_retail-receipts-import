---
title: 'DM plug-in'
type: 'feature'
ticket: '10'
created: '2026-10-24'
status: 'done'
baseline_revision: '85ac00db17accaf945bb76bdb85aa363e0964abd'
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

**Problem:** Pass 1 already names `dm`, but no DM plug-in exists, so every DM receipt ends as `Unsupported`.

**Approach:** Add a `dm` plug-in to `PLUGINS` (pass-2 schema, prompt, normalizer, pass-1 time hint, OIB read) applying DM's printing rules, and prove it on recorded responses of the nine owner-supplied DM PDFs against hand-written, owner-confirmed records.

## Boundaries & Constraints

**Always:** Gemini copies printed strings; the plug-in computes. An item is a name row followed by `Q kom x P A V` (V = VAT class, ignored): one line, unit None. `STORNO RETKA` is followed by the cancelled item repeated with negative quantity and amount: one `LineKind.STORNO` line whose `cancels_line` is the latest earlier sale line with the same folded, stripped text and absolute unit price not yet cancelled; none found → unreadable. A full storno nets to zero, so the model drops both lines. Purchase time is the header line `DD.MM.YYYY HH:MM` above the receipt number, never the card slip `Datum:`/`Vrijeme:`. `receipt_number` is the value after `Broj računa:`/`Br. računa:` (`9619/K05F/5`); branch is its middle segment (`K05F`); fewer than three segments → unreadable. `store_name` None (only the legal entity is printed); `store_address` is the shop line (`Ulica Vice Vukova 6, 10000 ZAGREB`) when printed, never the head office `10090 ZAGREB, Kovinska 5a`. `total` is `Ukupno`. Payments are printed negative: `MASTERCARD EUR -15,80` → card 15.80; `GOTOVINA EUR -4,00` with `Povrat novaca EUR 0,75` → cash 3.25. The PDV table, `dm active beauty bod` lines and the card slip never enter lines or settlements, and no schema field asks for card-slip data or the top barcode.

**Decisions (owner, 2026-10-24):** Code is written by Antigravity (`agy`, Gemini 3.8 Flash, High) in print mode, run from this session; review stays here. Live runs are approved: the one-time recording of the nine samples (18 Gemini calls). A storno cancelling more than was sold keeps today's path: the model refuses it and the receipt ends as `no_valid_result` with the existing texts; the deferred user-guide entry stays open. The plan is kept whole at about 2,100 tokens.

**Never:** No migration, contract, `chains_v1`, `texts/messages.toml` or outcome-enum change. No change to `pipeline.py`, `pass1.py`, `receipt.py`, the Gemini client, or Spar's, Lidl's or Kaufland's behavior. No other chain.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Card | `Maybelline korekt /podočnjak` / `1 kom x 7,90 7,90 1` ×2, `Ukupno 15,80`, `MASTERCARD EUR -15,80` | two lines 7.90, card 15.80, total 15.80 | none |
| Storno | two `Balea Med gel` 1,10, `STORNO RETKA` + `-1 kom x -1,10 -1,10`, `Balea Pr.krema` 3,30, `Ukupno 4,40` | three printed sale lines + storno cancelling line 2; stored lines 1.10 and 3.30 | storno with no matching earlier sale: unreadable |
| Cash with change | `GOTOVINA EUR -4,00`, `Povrat novaca EUR 0,75` | cash 3.25 | change without exactly one cash row: unreadable |
| Branch | `Br. računa: 38588/K08H/1` | branch `K08H`, receipt_number `38588/K08H/1` | missing or two segments: unreadable |
| Header time | header `15.12.2025 14:28`, slip `Vrijeme: 14:31` | 2025-12-15 14:28 Zagreb → UTC | unreadable date/time: unreadable |
| Unknown payment | `AMEX EUR -3,00` | — | unknown payment label: unreadable |
| Unknown negative row | negative row not after `STORNO RETKA` | — | unreadable |

</frozen-after-approval>

## Code Map

- `domain/chains/kaufland/{__init__,schema,prompt,normalize}.py` -- the pattern to copy: plug-in dataclass, `seller_oib` via the pass-2 model, both `ValidationError` guards around `normalize` (lines and settlements built inside the second), error-count-only messages.
- `domain/chains/printed.py` -- reuse `fold`, `money` (accepts a leading minus), `quantity` (does not: strip the minus, parse, negate on storno rows), `stripped`; `DATE` already matches `DD.MM.YYYY`. Add nothing chain-specific.
- New `domain/chains/dm/{__init__,schema,prompt,normalize}.py` -- `DM`, `chain_id="dm"`. Schema: `seller_oib`, `store_address`, `receipt_number`, `purchase_date`, `purchase_time`, `total`, `lines` (text, quantity, unit_price, amount, signed as printed), `payments` (text, amount). The model may return `STORNO RETKA` as its own row with an empty or `0,00` amount: skip it before `money()` and mark the next row as storno; a negative row without that marker is unreadable. Storno line: negative `quantity`, `printed_amount`, `unit_price` as printed (`Money` allows negatives). Payment labels as `fold()` gives them: `GOTOVINA` cash, `POVRAT NOVACA` change, `MASTERCARD`, `MAESTRO`, `VISA`, `DINERS`, `KARTICA` card.
- `domain/receipt.py` -- `LineKind.STORNO`, `cancels_line` (1-based), `stored_lines` netting, over-storno raises in the model. Do not change.
- `domain/chains/registry.py` -- `PLUGINS` gains `DM`.
- `tests/test_pass1.py:37-39`, `tests/test_pipeline.py:276-277` -- the chain without a plug-in becomes `mueller` (`KnownChain("mueller", "Müller", ("MÜLLER", "Müller", "Muller"), ("84698789700",))`). `tests/test_alerts.py:23-24,127,140,149` and `tests/test_loop.py:64-66` references gain a `dm` chain (OIB `94124811986`), or `missing plug-in: dm` alerts appear.
- `tests/test_spar_fixtures.py:35,42,136` -- `test_fixtures_hold_no_card_data` already scans all of `tests/fixtures/`; DM slips print `MID`, `TID`, masked PANs and a 19-digit barcode, none may appear.
- `tests/fixtures/dm/<receipt number first segment>/{pass1,pass2,expected}.json` -- nine cases: `212915` (`Broj računa` label), `24902` (cash + change), `14008` (K044), `40077` (shop address), `214478` (K01M), `48549` (storno), `38588` (shop address, two VAT rates), `9619`, `5999`.
- `scratch/record_dm.py` -- copy of `scratch/record_kaufland.py`: samples in `doc-inbox/fixtures/DM receipts/`, explicit file map, skips recorded files. `scratch/dm_scan.txt` holds the PDFs' text for writing `expected.json`.
- Do not change: `app/`, `adapters/`, `pass1.py`, `docs/contracts/`, `spar/`, `lidl/`, `kaufland/`, `migrations/`.

## Tasks & Acceptance

**Execution:**
- [x] `domain/chains/dm/*` -- schema, prompt, normalizer, plug-in -- DM printing rules
- [x] `domain/chains/registry.py` -- register `DM` -- makes DM supported
- [x] `tests/dm_samples.py`, `tests/test_dm_fixtures.py`, updated pass-1/pipeline/alerts/loop tests -- every matrix row on synthetic responses, time hint, OIB read -- offline proof
- [x] `scratch/record_dm.py` (orchestrator) -- owner-approved live recording -- fixtures from the real API
- [x] `tests/fixtures/dm/*/expected.json` (orchestrator) -- written by hand from `scratch/dm_scan.txt` before comparing with the normalizer; owner confirms -- hand-verified records

**Acceptance Criteria:**
- Given the nine recorded DM cases, when the fixture tests run offline, then each normalizes to its `expected.json` to the cent, total equals both the settlements and the lines' effective sum exactly, and the pipeline stores it with chain `dm` from the recorded pass 1.
- Given case `48549`, when normalized, then the stored lines are `Balea Med gel za tuš.300ml` 1.10 and `Balea Pr.krema/kovrče150ml` 3.30.
- Given the committed fixtures, when the card-data test runs, then no PAN, MID, TID or 13–19-digit number appears.
- Given the Spar, Lidl and Kaufland fixtures, when the suite runs, then they pass unchanged.

## Implementation Notes

- Implemented by Antigravity (`gemini-3.8-flash-high`, accept-edits, no shell commands) from `scratch/agy-prompt-10.md`; it ran no checks.
- Orchestrator fixes after the agy run: prompt, schema descriptions, time hint and two test comments rewrapped for E501 (prompt content unchanged); the placeholder skips in `test_dm_fixtures.py` removed once the fixtures existed.
- Recorded live with owner approval (2026-10-24): 18 calls, 9 cases.
- `expected.json` typed by hand (`scratch/write_dm_expected.py`) from the PDF text layer before comparing (`scratch/diff_dm.py`). Lines, storno, cash, times and branches matched on the first comparison. `store_address` differed on 7 cases: the shop address is printed in the header image, which the text layer lacks; each was confirmed by viewing the image (`scratch/dm_images.py`) and the hand records corrected. Two of the nine print the address in the text layer too.
- Deviation from the Code Map: the model copies the image address on two lines (`Av. Dubrovnik 16\n10000 ZAGREB`), the text layer on one; `_store_address` joins lines with `, ` so one shop gives one string. Test added.
- Live `48549` pass 2 copied the storno quantity as `1` against the printed `-1` (amount and unit price kept the minus); the normalizer negates storno quantities, so the record holds.
- Verification (WSL): ruff, format, mypy clean; `pytest` 537 passed. No writer or schema change, so the integration suite was not rerun.

## Plan Change Log

## Review Triage Log

Quick lens, pass 1: medium 0, low 5, false 2, rejected low 3.

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | AC2 not tested on the recorded `48549` | low | patch | No test called `stored_lines()` on the fixture. Added `test_recorded_storno_stores_only_the_lines_that_stand`. |
| 2 | `STORNO RETKA` marker with a non-zero amount silently dropped | false | reject | Reproduced (`scratch/repro_dm_review.py`): a marker carrying the amount with no storno row after it ends unreadable; a following storno row carries the money itself. |
| 3 | A head office line drops the shop address too | low | patch | Reproduced: `Ulica Vice Vukova 6\n10090 ZAGREB, Kovinska 5a` gave None. Now only the Kovinska line is dropped; test added. |
| 4 | Payment signs discarded with `abs()` | false | reject | A sign misread gives the right amount; a refund to card would need return lines, which DM rows refuse as negative rows without a marker, and both checks compare exact sums. |
| 5 | Zero `Povrat novaca` on a card receipt is unreadable | low | patch | Reproduced. Change now applies only when non-zero, as in Kaufland; test added. |
| 6 | DM `DATE`/`TIME` copied from Kaufland, accept YY and seconds | low | reject | Harmless tolerance for pass 1, which misread dates on Lidl and Kaufland; the fix narrows a tested path for no named harm. |
| 7 | Live `48549` storno quantity recorded as `1`, printed `-1` | low | patch | Read the fixture: amount and unit price keep the minus, quantity does not. The normalizer negates storno quantities as the Code Map says; recorded in Implementation Notes. |
| 8 | `DmLine.amount` defaults to `0,00`, so a missing amount gives items_settlement_mismatch instead of no_valid_result | low | reject | The receipt is refused either way, with an admin copy; making it required changes the request schema after the recording. |
| 9 | Unplanned inline-storno prefix and card-slip filters | low | patch | Reproduced: `STORNO RETKA Denkmit` was accepted as a storno. Both deleted; a copied slip row now makes the receipt unreadable. |
| 10 | Task checkboxes unticked | low | reject | Fix edits this build's plan; ticked as bookkeeping. |

After patches (WSL): ruff, format, mypy clean; `pytest` 538 passed.

## Design Notes

The storno stays a row with `cancels_line` rather than being dropped in the plug-in: the 4a model nets it, sums it into the consistency check and refuses an over-storno.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all pass

**Manual checks:**
- Owner confirms the nine `expected.json` against the PDFs. -- confirmed by the owner, 2026-10-24, including the seven shop addresses read from the header image, the ", " join of a two-line address, and accepting the live `48549` storno quantity without re-recording.
