---
id: 20
type: bug
title: "Receipt total is the amount to pay instead of the value of goods"
parent: epic-receipts-pipeline
covers: [CAP-4, CAP-5]
after: [9]
assignee: ""
refined: true
hitl: false
risk: medium
severity: P2
---

# Receipt total is the amount to pay instead of the value of goods

## Description

On a receipt with deposit refunds, the receipt's total is the printed amount to pay, and the total check compares it with card plus cash only. The owner ruled that the total is the value of the goods and that every settlement, deposit refunds included, is a payment: all settlements together must equal the total exactly. Both checks also allow a 0.01 EUR difference today, while on a real receipt the sums always agree to the cent. Today the records hold the wrong total, the check cannot see a deposit refund that is missing or misread, and a 1-cent misread is written.

## Reproduction

1. Recorded Kaufland case 17582 (`tests/fixtures/kaufland/17582`): goods 78,13, `Za platiti 75,93`, cash 75,93, deposit refunds 0,70 + 0,10 + 1,40.
2. Actual: total 75.93; the total check compares 75.93 with cash 75.93.
3. Expected: total 78.13; the total check compares 78.13 with all settlements, 75.93 + 2.20.
4. Same shape: Kaufland 36863 (14.99, expected 16.39) and Lidl 94695 (16.82, expected 20.42).
5. A receipt whose lines miss the settlements by 0.01 EUR is written today.

## Cause Hypothesis

The receipt model's total check sums only card and cash settlements, both checks use a 0.01 tolerance, and the Lidl and Kaufland plug-ins copy the printed amount to pay into the total without adding the deposit refunds printed among the items.

## Acceptance Criteria

1. **The total is the value of the goods**
   **Given** a receipt with deposit refunds, such as recorded cases Kaufland 17582 and 36863 and Lidl 94695
   **When** it is extracted
   **Then** its total is the printed amount to pay plus its deposit refunds (78.13, 16.39, 20.42), equal to the sum of its lines' effective amounts
2. **Settlements equal the total exactly**
   **Given** a receipt whose settlements of every kind (card, cash, bonus points, coupons, deposit refunds) miss the total by 0.01 EUR or more
   **When** it is checked before the write
   **Then** it is not written; the sender sees "Не удалось обработать чек: сумма товаров не сходится с суммой оплат. Администратор получил копию." and the admin gets "Стоимость товаров не сходится с суммой оплат (карта, наличные, тара, купоны, бонусы)." with a copy of the file
3. **Lines equal the settlements exactly**
   **Given** a receipt whose lines' effective amounts miss the settlements by 0.01 EUR
   **When** it is checked before the write
   **Then** it is refused as `items_settlement_mismatch`, whose admin text no longer names a tolerance; a receipt matching to the cent is written
4. **A misread amount to pay is still caught**
   **Given** a Lidl or Kaufland response whose printed amount to pay disagrees with card plus cash by 0.01 EUR
   **When** it is checked
   **Then** it is refused as in criterion 2
5. **Receipts without deposit refunds are unchanged**
   **Given** the Spar fixtures and the Lidl and Kaufland fixtures without deposit refunds
   **When** the suite runs
   **Then** their expected records are unchanged and pass with the exact checks
6. **Tests cover the condition found and fixed**
   **Given** the test suite
   **When** it runs
   **Then** a test that fails on the defect and passes on the fix covers a deposit-refund receipt's total, one covers a 0.01 EUR difference refused by each check, and one covers a refund larger than the purchase (Kaufland's synthetic case: goods 1,00, refund 3,00, cash -2,00, total 1.00)

## References

- parent — _bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/epic-receipts-pipeline.md
- spec — _bmad-output/initiative-receipts-import-mvp/spec-receipts-import/spec-receipts-import.md, CAP-4, CAP-5
- spec companion — _bmad-output/initiative-receipts-import-mvp/spec-receipts-import/receipt-outcomes.md, the two "disagree" rows
- architecture — _bmad-output/initiative-receipts-import-mvp/architecture-receipts-import/architecture-receipts-import.md, the extraction rule ("A cash payment records the receipt total", "±0.01 EUR") and the `invalid` class ("beyond ±0.01 EUR")

## Notes

- Decision: the total is the value of the goods; all settlements, deposit refunds included, sum to it (owner, 2026-10-24).
- Decision: both checks require an exact match; any difference is an extraction error, superseding the ±0.01 EUR tolerance (owner, 2026-10-24).
- Decision: a plug-in derives the total as the printed amount to pay plus the settlements printed outside it (deposit refunds; Müller bonus points), so the check still catches a misread amount to pay (owner, 2026-10-24).
- Decision: the sender text in criterion 2 (owner, 2026-10-24).
- Decision: the admin texts drop "больше чем на 0,01 EUR" to match the exact rule (`total_settlement_mismatch` as in criterion 2; `items_settlement_mismatch` becomes "Сумма позиций не сходится с суммой оплат.") (owner, 2026-10-24).
- Decision: storing the total and exposing it in `resolver_v1` is entry 21, not this bug (owner, 2026-10-24).
- Decision: built before entry 10, so the DM plug-in follows the new rule (owner, 2026-10-24).
- Assumption: the architecture's extraction rule and `invalid` class are reworded to match.
