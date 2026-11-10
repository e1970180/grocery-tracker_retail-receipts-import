-- Announces a correction of a line's printed text as a feed event 'corrected', so consumers
-- tracking the feed by cursor learn that the receipt's lines (text and item_key) changed.
--
-- 'stored' and 'deleted' stay at most once per receipt; 'corrected' may repeat, so the
-- (receipt_id, event) uniqueness narrows to a partial unique index over the two lifecycle events.

ALTER TABLE retail_receipts_import.receipt_feed
    DROP CONSTRAINT receipt_feed_event_key;

ALTER TABLE retail_receipts_import.receipt_feed
    DROP CONSTRAINT receipt_feed_event_check;

ALTER TABLE retail_receipts_import.receipt_feed
    ADD CONSTRAINT receipt_feed_event_check
    CHECK (event IN ('stored', 'deleted', 'corrected'));

CREATE UNIQUE INDEX receipt_feed_lifecycle_key
    ON retail_receipts_import.receipt_feed (receipt_id, event)
    WHERE event IN ('stored', 'deleted');

-- Takes the same feed lock as delete_receipt so event sequence numbers stay in commit order.
-- An unchanged text writes no event: the receipt did not change for consumers. The
-- (uuid, integer, text) overload delegates here and needs no event logic of its own.
CREATE OR REPLACE PROCEDURE retail_receipts_import.update_line_printed_text(
    p_line_id uuid,
    p_new_text text
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_receipt_id uuid;
    v_old_text text;
BEGIN
    IF p_new_text IS NULL OR trim(p_new_text) = '' THEN
        RAISE EXCEPTION 'printed_text cannot be null or empty';
    END IF;

    LOCK TABLE retail_receipts_import.receipt_feed IN EXCLUSIVE MODE;

    SELECT receipt_id, printed_text INTO v_receipt_id, v_old_text
    FROM retail_receipts_import.receipt_lines
    WHERE line_id = p_line_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Receipt line % not found', p_line_id;
    END IF;

    IF v_old_text = trim(p_new_text) THEN
        RETURN;
    END IF;

    UPDATE retail_receipts_import.receipt_lines
    SET printed_text = trim(p_new_text)
    WHERE line_id = p_line_id;

    INSERT INTO retail_receipts_import.receipt_feed (receipt_id, event)
    VALUES (v_receipt_id, 'corrected');
END;
$$;
