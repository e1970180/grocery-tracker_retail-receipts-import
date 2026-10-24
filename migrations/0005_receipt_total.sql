-- Adds the receipt total, backfills existing rows from settlements, and exposes total in resolver_v1.
-- Total is NOT NULL with no default so any writer omitting it fails immediately.

ALTER TABLE retail_receipts_import.receipts
    ADD COLUMN total numeric(12, 2);

-- Settlements, not stored lines: return lines are dropped before the write, while the
-- settlements still sum to the value of goods of the whole printed receipt.
UPDATE retail_receipts_import.receipts r
SET total = (
    SELECT sum(s.amount)
    FROM retail_receipts_import.receipt_settlements s
    WHERE s.receipt_id = r.receipt_id
);

ALTER TABLE retail_receipts_import.receipts
    ALTER COLUMN total SET NOT NULL;

-- CREATE OR REPLACE VIEW refuses to rename, reorder or drop columns, so total goes last;
-- replacing rather than dropping keeps the Resolver role's grant.
CREATE OR REPLACE VIEW resolver_v1.receipts AS
SELECT
    receipt_id,
    chain_id,
    store_name,
    branch_number,
    receipt_number,
    store_address,
    currency,
    to_char(purchased_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS purchased_at,
    to_char(purchased_at AT TIME ZONE 'Europe/Zagreb', 'YYYY-MM-DD"T"HH24:MI:SS')
        || '+'
        || to_char((purchased_at AT TIME ZONE 'Europe/Zagreb') - (purchased_at AT TIME ZONE 'UTC'), 'HH24:MI') AS purchased_at_local,
    buyer_name,
    total::text AS total
FROM retail_receipts_import.receipts;
