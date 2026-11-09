-- Adds item_key: a deterministic UUIDv5 per (chain, printed text), so consumers can link every
-- line carrying the same item to one record without reading this project's code.
-- Needs public.unaccent_grocery_tracker and public.sanitize_text (provisioned by common) and
-- uuid-ossp; PostgreSQL 18 has no built-in UUIDv5.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" SCHEMA public;

-- The rule is frozen: published keys are stored by consumers, so a different rule ships as a
-- new function (item_key_v2), never as an edit of this one. The namespace is RFC 9562
-- NAMESPACE_URL, kept as a literal here so the whole rule reads in one place.
-- Unaccent runs first so that sanitize also collapses any spaces the transliteration leaves.
-- chain_id cannot contain ':', so the separator keeps the two parts unambiguous.
CREATE FUNCTION retail_receipts_import.item_key(chain text, printed_text text)
RETURNS uuid
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
STRICT
RETURN public.uuid_generate_v5(
    '6ba7b811-9dad-11d1-80b4-00c04fd430c8'::uuid,
    chain || ':' || public.sanitize_text(public.unaccent_grocery_tracker(printed_text))
);

ALTER TABLE retail_receipts_import.receipt_lines
    ADD COLUMN item_key uuid;

UPDATE retail_receipts_import.receipt_lines l
SET item_key = retail_receipts_import.item_key(r.chain_id, l.printed_text)
FROM retail_receipts_import.receipts r
WHERE r.receipt_id = l.receipt_id;

ALTER TABLE retail_receipts_import.receipt_lines
    ALTER COLUMN item_key SET NOT NULL;

-- A trigger rather than a generated column: the chain lives on the receipt, and a generated
-- column can only read its own row. Every insert recomputes the key, so a writer cannot supply
-- its own value; the printed_text correction procedures re-key through their UPDATE.
CREATE FUNCTION retail_receipts_import.set_receipt_line_item_key()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.item_key := retail_receipts_import.item_key(
        (SELECT r.chain_id
         FROM retail_receipts_import.receipts r
         WHERE r.receipt_id = NEW.receipt_id),
        NEW.printed_text
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER receipt_lines_set_item_key
    BEFORE INSERT OR UPDATE OF printed_text ON retail_receipts_import.receipt_lines
    FOR EACH ROW
    EXECUTE FUNCTION retail_receipts_import.set_receipt_line_item_key();

-- CREATE OR REPLACE VIEW refuses to rename, reorder or drop columns, so item_key goes last;
-- replacing rather than dropping keeps the Resolver role's grant.
CREATE OR REPLACE VIEW resolver_v1.receipt_lines AS
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
    effective_amount::text AS effective_amount,
    item_key
FROM retail_receipts_import.receipt_lines;
