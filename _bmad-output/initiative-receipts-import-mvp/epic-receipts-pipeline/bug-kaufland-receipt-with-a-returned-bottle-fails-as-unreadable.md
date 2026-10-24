---
id: 22
type: bug
title: "Kaufland receipt with a returned bottle fails as unreadable"
parent: epic-receipts-pipeline
covers: [CAP-3, CAP-4]
after: [9]
assignee: ""
refined: true
hitl: false
risk: medium
severity: P2
---

# Kaufland receipt with a returned bottle fails as unreadable

## Description

A family member sends a valid Kaufland receipt that has a returned beer bottle among the items. The sender gets the failure reaction and the "no valid result" message, and the admin gets a copy of the file. The receipt should be stored with the returned bottle recorded as a deposit refund settlement (`SettlementKind.DEPOSIT_REFUND`), analogous to other `ambalaža` rows, and its checks matching to the cent.

## Reproduction

1. Dev database, 2026-10-24, trial import of 50 samples (ticket 16): sample `doc-inbox/fixtures/Kaufland receipts/20260427_231253.pdf`, receipt 137297/4430/6 of 03.07.25 10:19:55, card 61,23.
2. The receipt prints `Boca za pivo * 0,16 c` (a bottle bought) and later `Boca za pivo *  4 * 0,16  -0,64 c` (four bottles returned, at VAT rate c), next to the usual deposit rows `amb.- staklo * 2 * 0,10 -0,20 F` and `ambalaža - PET * 4 * 0,10 -0,40 F`.
3. Pass 2 returns that row as text "Boca za pivo *", quantity 4, unit price 0,16, amount -0,64 (response kept in `scratch/diagnose-pass2.json`, not in git).
4. Actual: `UnreadableReceipt("receipt fails the model (1 errors)")`, cause "a sale line's amounts and discounts cannot be negative"; outcome `no_valid_result`. Same result on a second run.
5. Expected: the receipt is stored; the -0,64 row is recorded as a deposit refund settlement (0,60 deposit rows + 0,64 beer bottle return = 1,24 deposit refund), lines total 62,47 equals settlements total (card 61,23 + deposit refunds 1,24 = 62,47), and total equals 62,47.

## Cause Hypothesis

The Kaufland normalizer takes as deposit refunds only rows starting with "amb." or "ambalaža". Any other row with a quantity becomes a sale line, whatever its sign, and a negative row without a quantity becomes a discount on the item above it. A returned product or returnable bottle row with a quantity and negative amount has no deposit-refund path.

## Acceptance Criteria

1. **A returned-bottle receipt is stored**
   **Given** the recorded pass-2 response of sample `20260427_231253.pdf`
   **When** it is normalized and checked
   **Then** the -0,64 returned bottle row is recorded as a deposit refund settlement (`SettlementKind.DEPOSIT_REFUND`) with amount 0,64, lines sum to 62,47, settlements sum to 62,47 (card 61,23 + deposit refunds 1,24), total is 62,47, and both consistency and total checks pass
2. **Other negative rows keep their meaning**
   **Given** the recorded Kaufland fixtures, with their "amb."/"ambalaža" deposit rows and "Štedite" discounts
   **When** the suite runs
   **Then** their expected records are unchanged
3. **Tests cover the condition found and fixed**
   **Given** the test suite
   **When** it runs
   **Then** a fixture test built from the sample's recorded response fails on the defect and passes on the fix, and one covers a negative row with a quantity that is not a known return or deposit refund, which is refused with a reason naming the row
4. **Or: no change is needed, with proof**
   **Given** the reproduction
   **When** it is run on the current code
   **Then** the receipt is already stored, or the report was mistaken, with the evidence recorded in Notes — this supersedes 1, 2 and 3

## References

- parent — _bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/epic-receipts-pipeline.md
- spec — _bmad-output/initiative-receipts-import-mvp/spec-receipts-import/spec-receipts-import.md, CAP-3, CAP-4
- spec companion — _bmad-output/initiative-receipts-import-mvp/spec-receipts-import/receipt-outcomes.md, the "no valid result" row
- trial evidence — _bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-first-production-deployment-and-acceptance-demo-plan.md, Implementation Notes
- sample data — doc-inbox/fixtures/Kaufland receipts/20260427_231253.pdf (git-ignored, personal data)
- diagnosis response — scratch/diagnose-pass2.json (local scratch, git-ignored)

## Notes

- Decision: 2026-10-24, owner: a returned beer bottle line (such as "Boca za pivo * 4 * 0,16 -0,64") is treated as a deposit refund settlement (SettlementKind.DEPOSIT_REFUND), analogous to other ambalaža rows, settling part of the purchase.
- Observation: 2026-10-24: the printed "Povratna naknada: 1,50" is an informational bookkeeping line indicating the government deposit included in beverages bought on this receipt; it is already ignored by the normalizer's _is_info filter.
- Assumption: other Kaufland receipts with returned bottles fail the same way; only this one sample was seen.
