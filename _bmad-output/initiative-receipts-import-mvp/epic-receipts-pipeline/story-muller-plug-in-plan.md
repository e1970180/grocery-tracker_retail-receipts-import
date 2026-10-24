---
title: 'Müller plug-in'
type: 'feature'
ticket: '11'
created: '2026-10-24'
status: 'done'
baseline_revision: 'ecc924ed443bfce48abe5975438ea1ac15b9efa7'
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

**Problem:** Pass 1 already names `mueller`, but no Müller plug-in exists, so every Müller receipt ends as `Unsupported`.

**Approach:** Add a `mueller` plug-in to `PLUGINS` (pass-2 schema, prompt, normalizer, pass-1 time hint, OIB read) applying Müller's printing rules, and prove it on recorded responses of the fifteen owner-supplied Müller images against hand-written, owner-confirmed records.

## Boundaries & Constraints

**Always:** Gemini copies printed strings; the plug-in computes. An item row is `Kom Artikl Cijena [Popust] Iznos` with a VAT letter glued to `Iznos` (`11,99a`, `0,10b`): strip one trailing letter before `money()`; unit None. `Popust` prints as a negative amount (`0,99 -0,10 0,89a`): `included_discount` is its absolute value, `unit_price` is `Cijena`, `printed_amount` is `Iznos`; every item row must satisfy `Kom × Cijena + Popust = Iznos` exactly, else unreadable. The text row printed under a discounted item (`Coupon 0,89 Blink`) is its `discount_text`, never a line. `POVRATNA NAKNADA` is an ordinary sale line; it prints no `Kom`, so a missing quantity is accepted only on that row and is 1 (the rule above then requires `Iznos = Cijena`). Item text: drop one trailing standalone ` *` (loyalty-exclusion marker; an inner `*` as in `BARFUSS UREA*BD KRE` stays) and collapse whitespace runs to one space. `Međuzbroj` rows are running subtotals: never lines. `total` is `ZA PLATITI` plus the `Müller bodovi` amount (the value of goods, so the total check still catches a misread `ZA PLATITI`). `Müller bodovi EUR X` is a `BONUS_POINTS` settlement of X. Payments print positive: `PLACANJE KARTICOM EUR X` card; `GOTOVINA EUR 50,00` with `POVRAT NOVCA EUR -34,40` → cash 15.60. Purchase time is the footer line `DD.MM.YYYY HH:MM` beside the `F76H…#…` code, never the card slip `DATUM`/`VRIJEME`. `receipt_number` is the value after `RB :` (`18101/4981/3`); branch is its middle segment; fewer than three segments → unreadable. `store_name` is the shop line under the company address (`Zagreb EKZ Arena`); `store_address` the next line without the phone (`Ulica Vice Vukova 6, 10000 Zagreb`), never the company line `Oreškoviceva 6H/1, 10 020 Zagreb`. `** Ponovni ispis računa **` changes nothing. The PDV table (with its `Zbroj` and `1 POVRATNA` rows), the points note, the `Na ovu kupovinu dobili ste ukupni popust` note, the card slip, ZKI/JIR, the footer code and the barcode never enter lines or settlements, and no schema field asks for them.

**Decisions (owner, 2026-10-24):** Code is written by Antigravity (`agy`, Gemini 3.8 Flash, High) in print mode, run from this session; review stays here. Live runs are approved: the one-time recording of the fifteen images (30 Gemini calls). `Popust` is read as above from the one discounted sample (`Attachment-1.png`); a discount shape it does not show fails the row rule and is unreadable. The total is derived from `ZA PLATITI`, following the 1.20 rule (amount to pay plus the settlements printed outside it). The plan is kept whole above 1600 tokens.

**Never:** No migration, contract, `chains_v1`, `texts/messages.toml` or outcome-enum change. No change to `pipeline.py`, `pass1.py`, `receipt.py`, `printed.py`, the Gemini client, or Spar's, Lidl's, Kaufland's or DM's behavior. No filter or tolerance beyond this plan.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Bonus + deposit | lines 1,39 / 3,85 / 0,95 / `POVRATNA NAKNADA *` 0,10b, `Müller bodovi EUR 3,01`, `ZA PLATITI 3,28`, card 3,28 | 4 lines (deposit `POVRATNA NAKNADA` 0.10), bonus 3.01 + card 3.28, total 6.29 | none |
| Discount | `1 BLINK SPUŽVASTA KRP 0,99 -0,10 0,89a`, `Coupon 0,89 Blink` | unit 0.99, printed 0.89, included 0.10, discount_text `Coupon 0,89 Blink` | `Kom × Cijena + Popust ≠ Iznos`: unreadable |
| Cash with change | `GOTOVINA 50,00`, `POVRAT NOVCA -34,40` | cash 15.60 | change without exactly one cash row: unreadable |
| Footer time | footer `15.03.2025 19:17`, slip `VRIJEME: 19:18:09` | 2025-03-15 19:17 Zagreb → UTC | unreadable date/time: unreadable |
| Branch | `RB :143667/4972/4` | branch `4972`, receipt_number `143667/4972/4` | missing or two segments: unreadable |
| Deposit without price match | no `Kom`, `Cijena 0,10`, `Iznos 0,20` | — | unreadable |
| Missing quantity | item other than `POVRATNA NAKNADA` without `Kom` | — | unreadable |
| Unknown payment | `AMEX EUR 3,00` | — | unreadable |
| Negative item | item `Iznos -1,00` | — | unreadable |

</frozen-after-approval>

## Code Map

- `domain/chains/dm/{__init__,schema,prompt,normalize}.py` -- the pattern to copy: plug-in dataclass, `seller_oib` via the pass-2 model, both `ValidationError` guards, error-count-only messages, `_receipt_number_and_branch`, the change folding in `_settlements`. Müller's signs are reversed (payments positive, change negative); its change label is `POVRAT NOVCA`.
- `domain/chains/printed.py` -- reuse `fold`, `money`, `quantity`, `stripped`. `fold` keeps `Đ`, so match `MEĐUZBROJ` and `MEDUZBROJ`.
- New `domain/chains/mueller/` -- `MUELLER`, `chain_id="mueller"` (the seeded slug; the samples folder and plan file say `muller`, code never does). Schema: `seller_oib` (footer `OIB:`), `store_name`, `store_address`, `receipt_number`, `purchase_date`, `purchase_time`, `amount_to_pay` (`ZA PLATITI`), `lines` (text, quantity, unit_price, discount, amount, discount_note), `payments` (text, amount — the amount alone, without `EUR`; `Müller bodovi` is a payment row). Payment labels by `fold()`: `GOTOVINA` cash, `POVRAT NOVCA` change, `KARTIC` card, `BODOVI` bonus points.
- `domain/chains/registry.py` -- `PLUGINS` gains `MUELLER`.
- `tests/test_pass1.py:37-39`, `tests/test_pipeline.py:57,276-277` -- the chain without a plug-in becomes a test-only slug (e.g. `tommy`, passes `is_chain_id`, not reserved), so `Unsupported` stays covered.
- `tests/test_lidl_fixtures.py` -- the image pattern for the pipeline fixture test (`image/jpeg` and `image/png`, `images.prepare`); DM's fake `%PDF-fixture` does not apply.
- `tests/test_spar_fixtures.py` `test_fixtures_hold_no_card_data` -- already scans all fixtures; Müller slips print PANs, TID/MID, RRN, and the footer code holds a 14-digit run.
- `tests/fixtures/mueller/<RB first segment>[-copy]/{pass1,pass2,expected}.json` -- fifteen cases, eleven receipts: `18101` (`muller1.jpeg`), `18101-full` (`muller 25.36 (full) .png`), `76391` (`muller2.jpeg`: bonus + deposit), `76391-png` (`Attachment-.png`), `37833` (`muller 4.jpeg`: bonus, footer 19:17 vs slip 19:18), `456` (`muller 5.jpeg`, reprint), `99102` (`muller 6.jpeg`), `99102-png` (`Attachment-3.png`), `66233` (`muller 7.jpeg`: double space), `66233-png` (`Attachment-2.png`), `148305` (`muller 8.jpeg`: cash + change), `143667` (`muller 8.41.jpeg`: bonus, footer 15:38 vs slip 15:39), `143667-full` (`muller 8.41 (full).png`), `143667-png` (`Attachment-4.png`), `74630` (`Attachment-1.png`: discount).
- `scratch/record_mueller.py` -- copy of `scratch/record_lidl.py`: samples in `doc-inbox/fixtures/Muller receipts/`, explicit file map with per-file mime, skips recorded files.
- Do not change: `app/`, `adapters/`, `pass1.py`, `printed.py`, `receipt.py`, `docs/contracts/`, `spar/`, `lidl/`, `kaufland/`, `dm/`, `migrations/`.

## Tasks & Acceptance

**Execution:**
- [ ] `domain/chains/mueller/*` -- schema, prompt, normalizer, plug-in -- Müller printing rules
- [ ] `domain/chains/registry.py` -- register `MUELLER` -- makes Müller supported
- [ ] `tests/mueller_samples.py`, `tests/test_mueller_fixtures.py`, updated pass-1/pipeline tests -- every matrix row on synthetic responses, time hint, OIB read -- offline proof
- [ ] `scratch/record_mueller.py` (orchestrator) -- owner-approved live recording -- fixtures from the real API
- [ ] `tests/fixtures/mueller/*/expected.json` (orchestrator) -- typed by hand from the images before comparing with the normalizer; owner confirms -- hand-verified records

**Acceptance Criteria:**
- Given the fifteen recorded cases, when the fixture tests run offline, then each normalizes to its `expected.json` to the cent, total equals both the settlements and the lines' effective sum exactly, the pipeline stores it with chain `mueller` from the recorded pass 1, and each `pass1.json` time equals `expected.purchased_at`.
- Given case `76391`, when normalized, then the lines include `POVRATNA NAKNADA` 0.10, the settlements are bonus points 3.01 and card 3.28, and the total is 6.29.
- Given case `74630`, when normalized, then `BLINK SPUŽVASTA KRP` has unit price 0.99, printed amount 0.89, included discount 0.10 and discount text `Coupon 0,89 Blink`, and the total is 20.88.
- Given the copies (`-full`, `-png`) of one receipt, when normalized, then every copy gives the same record as its first case.
- Given the committed fixtures, when the card-data test runs, then no PAN, MID, TID or 13–19-digit number appears.
- Given the Spar, Lidl, Kaufland and DM fixtures, when the suite runs, then they pass unchanged.

## Implementation Notes

- Implemented by Antigravity (`gemini-3.8-flash-high`, accept-edits, no shell commands) from `scratch/agy-prompt-11.md`; it ran no checks. The first run ended with no output because agy called its denied command tool; the rerun forbade that tool explicitly.
- Orchestrator fixes after the agy run: the placeholder skips in `test_mueller_fixtures.py` removed once the fixtures existed; tests added for AC2 (`76391`), AC3 (`74630`) and the copies giving one record; the unused `pass1_response` helper removed; `test_alerts.py` and `test_loop.py` references gain a `mueller` chain, or `missing plug-in: mueller` alerts appear; ruff format.
- Recorded live with owner approval (2026-10-24): 30 calls, then 15 more. The first pass 2 of `143667` dropped `Müller bodovi`, because the agy prompt asked only for payment rows under `ZA PLATITI` while the bonus row is printed above it. The prompt now names that row; all fifteen pass 2 files were re-recorded with it (pass 1 kept, its prompt unchanged).
- `expected.json` typed by hand (`scratch/write_mueller_expected.py`) from the images before comparing (`scratch/diff_mueller.py`). Two hand errors corrected after comparing: payment labels print with `EUR` (`PLACANJE KARTICOM EUR`, as DM keeps `MASTERCARD EUR`), and `PFEILRING` (read as `PFEIFRING`; confirmed on an enlarged crop, `scratch/crop_mueller.py`). After that all fifteen matched, and every pass 1 gives chain `mueller` and the footer minute.
- Verification (WSL): ruff, format, mypy clean; `pytest` 595 passed. No writer or schema change, so the integration suite was not rerun.

## Plan Change Log

## Review Triage Log

Quick lens, pass 1: medium 0, low 5 patched, low 2 rejected, false 1.

| # | Finding | Verdict | Route | Evidence |
|---|---------|---------|-------|----------|
| 1 | `DATE`/`TIME` copied from DM accept `YY` and `HH:MM:SS`, so a copied slip time is stored a minute off | low | patch | Reproduced (`scratch/repro_mueller_review.py`): `19:18:09` gave 18:18 UTC in pass 2 and pass 1. Now `printed.DATE` and a strict `HH:MM`; the slip time is unreadable in pass 2 and None in pass 1; tests added. |
| 2 | `_store_name` turns a copied company line into None | low | reject | Reproduced, but `store_name` is optional and None stores no wrong value; all fifteen live responses copied the shop line; deleting the filter would store the company as the shop. |
| 3 | Amount without its VAT letter and a positive change row are accepted | low | reject | Neither changes money: the letter carries no amount and the change is subtracted either way, and both checks compare exact sums. Same call as DM review finding 4. |
| 4 | Schema guard uses `\b`, so `pan_number` would pass, and omits `chain` | low | patch | Reproduced: `pan_number` not caught. Now Spar's pattern, which matches no current field. |
| 5 | `test_matrix_discount` puts `Kom` into the item text | low | patch | Read: text `1 BLINK SPUŽVASTA KRP` contradicts the matrix and AC2. Text is now `BLINK SPUŽVASTA KRP`. |
| 6 | `tests/mueller_samples.py` docstring claims the header copies case 18101 | low | patch | Read: date, time and amount come from other cases. Docstring now says why the module exists. |
| 7 | Comments restate the plan's rules | low | patch | The `Kom x Cijena` comment now says why the columns are checked; the `DATE`/`TIME` comments went with finding 1. |
| 8 | Copy test compares byte-identical `pass2.json` in four of five groups | false | reject | Identical responses for different image files are the convergence the criterion asks for; `76391-png` differs in spacing and still meets. |

After patches (WSL): ruff, format, mypy clean; `pytest` 595 passed.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all pass

**Manual checks:**
- Owner confirms the fifteen `expected.json` against the images. -- confirmed by the owner, 2026-10-24, including the total as ZA PLATITI plus Müller bodovi, the payment labels with `EUR`, and `PFEILRING`.
