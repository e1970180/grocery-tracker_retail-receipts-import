-- Trims the writer to the rights the service uses, after a migrate run that created tables.
-- Idempotent; run as the schema owner (or the admin):
--   psql -h <host> -p <port> -U rri_dev_owner -d grocery-tracker-dev -v ON_ERROR_STOP=1 \
--        -v writer=rri_dev_writer -f docs/deploy/after-migrate.sql
-- The service reads receipts for the duplicate checks and only inserts everywhere else.

BEGIN;
REVOKE ALL ON ALL TABLES IN SCHEMA retail_receipts_import FROM :"writer";
GRANT SELECT, INSERT ON retail_receipts_import.receipts TO :"writer";
GRANT INSERT ON retail_receipts_import.receipt_lines, retail_receipts_import.receipt_settlements,
    retail_receipts_import.receipt_feed TO :"writer";
REVOKE ALL ON ALL SEQUENCES IN SCHEMA retail_receipts_import FROM :"writer";
GRANT USAGE ON SEQUENCE retail_receipts_import.receipt_feed_seq_seq TO :"writer";
COMMIT;
