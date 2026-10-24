-- Some retail chains print no shop name on their receipts, so store_name is optional.

ALTER TABLE retail_receipts_import.receipts ALTER COLUMN store_name DROP NOT NULL;
