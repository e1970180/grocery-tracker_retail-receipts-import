# Locator digest: migrations, docs, top-level files @ 7c1c47c

Q1 (columns, constraints, indexes, comments):

- migrations/0001_describe_schema.sql:2 (COMMENT ON SCHEMA retail_receipts_import) @ 7c1c47c. Only statement in 0001: a schema comment saying the schema and roles are provisioned outside migrations. No tables.
- migrations/0002_receipts.sql:1-3 (header comment) @ 7c1c47c. Storno and return lines are netted or dropped before write, so every stored line is a purchase; the feed outlives its receipt.
- migrations/0002_receipts.sql:4-21 (CREATE TABLE retail_receipts_import.receipts) @ 7c1c47c. Columns: receipt_id uuid PK; chain_id text NOT NULL, CHECK slug regex and NOT IN ('other','unreadable'); store_name text NOT NULL (:8); branch_number text; receipt_number text (:10); store_address text (:11); loyalty_card_number text (:12); currency text NOT NULL CHECK = 'EUR'; purchased_at timestamptz NOT NULL; buyer_name text NOT NULL; source_kind text NOT NULL; source_ref text NOT NULL; created_at timestamptz NOT NULL DEFAULT now(). UNIQUE receipts_chain_purchased_key (chain_id, purchased_at); UNIQUE receipts_source_key (source_kind, source_ref). Nullable: branch_number, receipt_number, store_address, loyalty_card_number.
- migrations/0002_receipts.sql:23-42 (CREATE TABLE receipt_lines) @ 7c1c47c. Columns: line_id uuid PK; receipt_id uuid NOT NULL FK ON DELETE CASCADE; line_no integer NOT NULL; printed_text text NOT NULL; quantity numeric(12,3) NOT NULL CHECK > 0; unit text; unit_price numeric(12,2); printed_amount numeric(12,2) NOT NULL; included_discount numeric(12,2) NOT NULL CHECK >= 0; separate_discount numeric(12,2) NOT NULL CHECK >= 0; discount_text text; regular_amount GENERATED (printed_amount + included_discount) STORED; effective_amount GENERATED (printed_amount - separate_discount) STORED CHECK >= 0. UNIQUE receipt_lines_receipt_line_key (receipt_id, line_no).
- migrations/0002_receipts.sql:44-52 (CREATE TABLE receipt_settlements) @ 7c1c47c. receipt_id uuid NOT NULL FK ON DELETE CASCADE; settlement_no integer NOT NULL; kind text NOT NULL CHECK IN ('card','cash','bonus_points','coupon','deposit_refund'); printed_text text NOT NULL; amount numeric(12,2) NOT NULL; PRIMARY KEY (receipt_id, settlement_no).
- migrations/0002_receipts.sql:54-59 (CREATE TABLE receipt_feed) @ 7c1c47c. seq bigint GENERATED ALWAYS AS IDENTITY PK; receipt_id uuid NOT NULL (no FK, so the feed outlives the receipt); event text NOT NULL CHECK IN ('stored','deleted'); UNIQUE receipt_feed_event_key (receipt_id, event).
- No explicit CREATE INDEX in 0001 or 0002; only implicit PK/UNIQUE indexes. No COMMENT ON TABLE or COLUMN in 0002.

Q3 (touches in migrations, docs, top-level):

- store_name, store_address, loyalty_card_number, receipt_number appear only in migrations/0002_receipts.sql:8, :11, :12, :10 (CREATE TABLE receipts) @ 7c1c47c. No hits in docs/, README.md, texts/, AGENTS.md, pyproject.toml, compose.yaml, Dockerfile, .env.example, .github/.
- docs/contracts/chains_v1.md:11-12 @ 7c1c47c. Chains reference is not written by this service; no receipt table has a foreign key to it.
- docs/contracts/chains_v1.md:22, :24, :25, :40, :42, :59, :67 @ 7c1c47c. chains columns (chain_id, aliases "names as printed on receipts", seller_oibs "OIBs printed on fiscal receipts"); not receipt-table columns.
- docs/contracts/chains_v1.sql:6-9 (CREATE TABLE public.chains), :30-32 (CREATE VIEW public.chains_v1), :34 (INSERT INTO public.chains) @ 7c1c47c. Columns chain_id, display_name, aliases, seller_oibs, active.
- docs/api-versions.md, texts/messages.toml: no hits for receipt columns.
- README.md:50-52 (migrate section) @ 7c1c47c. Mentions schema_migrations and roles only.

Searched, found nothing: ADR files (`adr-*.md`) and decision folders at 7c1c47c: none.
Not searched: src/ and tests/ (other locators' areas).
