-- Receipts as the pipeline stores them. Storno and return lines are netted or dropped before
-- the write, so every stored line is a purchase; the feed is a log that outlives its receipt.

CREATE TABLE retail_receipts_import.receipts (
    receipt_id uuid PRIMARY KEY,
    chain_id text NOT NULL
        CHECK (chain_id ~ '^[a-z][a-z0-9_]{0,31}$' AND chain_id NOT IN ('other', 'unreadable')),
    store_name text NOT NULL,
    branch_number text,
    receipt_number text,
    store_address text,
    loyalty_card_number text,
    currency text NOT NULL CHECK (currency = 'EUR'),
    purchased_at timestamptz NOT NULL,
    buyer_name text NOT NULL,
    source_kind text NOT NULL,
    source_ref text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT receipts_chain_purchased_key UNIQUE (chain_id, purchased_at),
    CONSTRAINT receipts_source_key UNIQUE (source_kind, source_ref)
);

CREATE TABLE retail_receipts_import.receipt_lines (
    line_id uuid PRIMARY KEY,
    receipt_id uuid NOT NULL
        REFERENCES retail_receipts_import.receipts (receipt_id) ON DELETE CASCADE,
    line_no integer NOT NULL,
    printed_text text NOT NULL,
    quantity numeric(12,3) NOT NULL CHECK (quantity > 0),
    unit text,
    unit_price numeric(12,2),
    printed_amount numeric(12,2) NOT NULL,
    included_discount numeric(12,2) NOT NULL CHECK (included_discount >= 0),
    separate_discount numeric(12,2) NOT NULL CHECK (separate_discount >= 0),
    discount_text text,
    regular_amount numeric(12,2)
        GENERATED ALWAYS AS (printed_amount + included_discount) STORED,
    effective_amount numeric(12,2)
        GENERATED ALWAYS AS (printed_amount - separate_discount) STORED
        CHECK (effective_amount >= 0),
    CONSTRAINT receipt_lines_receipt_line_key UNIQUE (receipt_id, line_no)
);

CREATE TABLE retail_receipts_import.receipt_settlements (
    receipt_id uuid NOT NULL
        REFERENCES retail_receipts_import.receipts (receipt_id) ON DELETE CASCADE,
    settlement_no integer NOT NULL,
    kind text NOT NULL CHECK (kind IN ('card', 'cash', 'bonus_points', 'coupon', 'deposit_refund')),
    printed_text text NOT NULL,
    amount numeric(12,2) NOT NULL,
    PRIMARY KEY (receipt_id, settlement_no)
);

CREATE TABLE retail_receipts_import.receipt_feed (
    seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    receipt_id uuid NOT NULL,
    event text NOT NULL CHECK (event IN ('stored', 'deleted')),
    CONSTRAINT receipt_feed_event_key UNIQUE (receipt_id, event)
);
