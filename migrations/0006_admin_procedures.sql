-- Stored procedures for administrative operations: deleting receipts and updating line printed_text.
--
-- 1. delete_receipt(uuid):
--    Locks retail_receipts_import.receipt_feed IN EXCLUSIVE MODE so concurrent sequence
--    assignments in the feed are strictly serialized.
--    Deletes the receipt from retail_receipts_import.receipts (cascading lines and settlements).
--    Emits a 'deleted' event into retail_receipts_import.receipt_feed.
--
-- 2. delete_receipt(text, timestamptz):
--    Convenience overload by (chain_id, purchased_at).
--
-- 3. update_line_printed_text(uuid, text):
--    Updates printed_text for a line in retail_receipts_import.receipt_lines with validation.
--
-- 4. update_line_printed_text(uuid, integer, text):
--    Convenience overload by (receipt_id, line_no, new_text).

CREATE OR REPLACE PROCEDURE retail_receipts_import.delete_receipt(
    p_receipt_id uuid
)
LANGUAGE plpgsql
AS $$
BEGIN
    -- 1. Serialize sequence assignment on the feed
    LOCK TABLE retail_receipts_import.receipt_feed IN EXCLUSIVE MODE;

    -- 2. Delete the receipt; lines and settlements are dropped by ON DELETE CASCADE
    DELETE FROM retail_receipts_import.receipts
    WHERE receipt_id = p_receipt_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Receipt % not found', p_receipt_id;
    END IF;

    -- 3. Insert deletion lifecycle event into the feed
    INSERT INTO retail_receipts_import.receipt_feed (receipt_id, event)
    VALUES (p_receipt_id, 'deleted');
END;
$$;

CREATE OR REPLACE PROCEDURE retail_receipts_import.delete_receipt(
    p_chain_id text,
    p_purchased_at timestamptz
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_receipt_id uuid;
BEGIN
    SELECT receipt_id INTO v_receipt_id
    FROM retail_receipts_import.receipts
    WHERE chain_id = p_chain_id AND purchased_at = p_purchased_at;

    IF v_receipt_id IS NULL THEN
        RAISE EXCEPTION 'Receipt for chain % at % not found', p_chain_id, p_purchased_at;
    END IF;

    CALL retail_receipts_import.delete_receipt(v_receipt_id);
END;
$$;

CREATE OR REPLACE PROCEDURE retail_receipts_import.update_line_printed_text(
    p_line_id uuid,
    p_new_text text
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_new_text IS NULL OR trim(p_new_text) = '' THEN
        RAISE EXCEPTION 'printed_text cannot be null or empty';
    END IF;

    UPDATE retail_receipts_import.receipt_lines
    SET printed_text = trim(p_new_text)
    WHERE line_id = p_line_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Receipt line % not found', p_line_id;
    END IF;
END;
$$;

CREATE OR REPLACE PROCEDURE retail_receipts_import.update_line_printed_text(
    p_receipt_id uuid,
    p_line_no integer,
    p_new_text text
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_line_id uuid;
BEGIN
    IF p_new_text IS NULL OR trim(p_new_text) = '' THEN
        RAISE EXCEPTION 'printed_text cannot be null or empty';
    END IF;

    SELECT line_id INTO v_line_id
    FROM retail_receipts_import.receipt_lines
    WHERE receipt_id = p_receipt_id AND line_no = p_line_no;

    IF v_line_id IS NULL THEN
        RAISE EXCEPTION 'Receipt line for receipt % line_no % not found', p_receipt_id, p_line_no;
    END IF;

    CALL retail_receipts_import.update_line_printed_text(v_line_id, p_new_text);
END;
$$;
