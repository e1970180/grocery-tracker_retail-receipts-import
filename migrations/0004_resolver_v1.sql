-- Resolver feed contract resolver_v1.
-- The resolver_v1 schema is provisioned with database privileges, not here.
-- Views list all columns explicitly and keep default security_invoker = false.

COMMENT ON SCHEMA resolver_v1 IS 'Resolver feed contract resolver_v1';

CREATE VIEW resolver_v1.feed AS
SELECT
    seq,
    receipt_id,
    event
FROM retail_receipts_import.receipt_feed;

CREATE VIEW resolver_v1.receipts AS
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
    buyer_name
FROM retail_receipts_import.receipts;

CREATE VIEW resolver_v1.receipt_lines AS
SELECT
    line_id,
    receipt_id,
    line_no,
    printed_text,
    quantity::text AS quantity,
    unit,
    unit_price::text AS unit_price,
    printed_amount::text AS printed_amount,
    included_discount::text AS included_discount,
    separate_discount::text AS separate_discount,
    discount_text,
    regular_amount::text AS regular_amount,
    effective_amount::text AS effective_amount
FROM retail_receipts_import.receipt_lines;

CREATE VIEW resolver_v1.receipt_settlements AS
SELECT
    receipt_id,
    settlement_no,
    kind,
    printed_text,
    amount::text AS amount
FROM retail_receipts_import.receipt_settlements;
