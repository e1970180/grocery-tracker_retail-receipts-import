# Analyzer digest Q3: who touches receipt fields @ 7c1c47c

Paths under src/retail_receipts_import/ unless they start with tests/, migrations/, texts/, docs/ or README.md. Code read, not run.

## Load-bearing
- L1. No code SELECTs any stored receipt column other than receipt_id, source_kind and source_ref. The only SELECTs on retail_receipts_import.receipts are FIND_BY_SOURCE and FIND_BY_DEDUP_KEY (adapters/postgres/receipts.py:29-36).
- L2. loyalty_card_number, store_address, receipt_number, branch_number and currency are never read by code, including notify and message paths; they are only INSERTed (adapters/postgres/receipts.py:38-41, 183-188). Nothing gives loyalty_card_number a value; the Spar normalizer never sets it (domain/chains/spar/normalize.py:35-46).
- L3. The dedup key is (chain_id, purchased_at); the lookups compare source_kind/source_ref only; dedup never uses store_name, receipt_number or branch_number.
- L4. In the Unsupported path store_name comes from the pass-1 response and is appended as a bare line to the admin message only; the sender message does not contain it.
- L5. No `resolver_v*` view, schema or grant exists in migrations or code.

## Call sites
store_name
- domain/chains/pass1.py:13-15 (Pass1Response): optional field, store or branch name printed on the receipt; asked for at pass1.py:58.
- app/pipeline.py:195-196 (_detect_chain): for an unsupported chain, `(pass1.store_name or "").strip() or None` into Unsupported(chain_id, store_name) (dataclass pipeline.py:95-98).
- app/jobs.py:217-218, 284 (_detect_chain, _unsupported): final unsupported result calls `_finish(..., store_name=result.store_name)`.
- app/jobs.py:355-376 (_finish): passes store_name to `ports.notify.finished`; not written to the queue (queue.finish at jobs.py:364-366 gets none).
- app/notify.py:52, 62-66 (Notifier.finished): UNSUPPORTED_CHAIN reacts with None, sends the sender message (no store_name; _reply notify.py:102-108), and calls `_admin(..., store_name)`.
- app/notify.py:110-119 (Notifier._admin), 138-143 (_admin_text): lines = [admin message, item.buyer_name, "#<job_id>"] plus store_name if non-empty. FAILED reasons pass store_name=None (notify.py:75); `_admin_copy` passes None (notify.py:124).
- texts/messages.toml:14 sender_messages.unsupported_chain: "Чеки этой сети пока не поддерживаются." (no store_name). texts/messages.toml:23 admin_messages.unsupported_chain: "Чек неподдерживаемой сети." (store_name follows on its own line).
- domain/chains/spar/schema.py:31 (SparPass2.store_name) required; spar/prompt.py:9; spar/normalize.py:38 strip into NormalizedReceipt; domain/receipt.py:149 min_length=1; adapters/postgres/receipts.py:38, 183 INSERT only; migrations/0002_receipts.sql:8 NOT NULL; app/jobs.py:238 (_extract) serializes the normalized receipt, store_name included, into receipt_json.

store_address: spar/schema.py:32, spar/prompt.py:11, spar/normalize.py:41 `_stripped`, domain/receipt.py:152, receipts.py:39, 186 INSERT only, migrations/0002_receipts.sql:11 nullable.
receipt_number: spar/schema.py:33, spar/prompt.py:14, spar/normalize.py:40 and 72-80 (`_branch` raises UnreadableReceipt unless three numeric "/"-segments), domain/receipt.py:151, receipts.py:39, 185 INSERT only, migrations/0002_receipts.sql:10 nullable; no unique index on it.
branch_number: only computed in spar/normalize.py:39, 72-80; domain/receipt.py:150; receipts.py:38, 184 INSERT only; migrations/0002_receipts.sql:9 nullable.
loyalty_card_number: domain/receipt.py:153 default None; receipts.py:39, 187 INSERT only; migrations/0002_receipts.sql:12 nullable; no other production reference in src/; Spar schema and prompt do not mention it.
currency: domain/receipt.py:154 `Literal["EUR"] = "EUR"`, no plug-in sets it; receipts.py:39, 188 INSERT only; migrations/0002_receipts.sql:13 NOT NULL CHECK = 'EUR'.
buyer_name: domain/intake.py:38, 72, 137 (Accepted, _buyer_name) from the Telegram sender; adapters/queue/sqlite.py:28 (_SCHEMA_V1) jobs.buyer_name; sqlite.py:61, 105-112, 280; app/jobs.py:350-352 (_source) `telegram_source(chat_id, message_id, buyer_name=item.buyer_name)`; domain/receipt.py:237, 240-245; receipts.py:40, 190 INSERT only; migrations/0002_receipts.sql:15 NOT NULL; app/notify.py:140 (_admin_text) reads item.buyer_name from the SQLite-held Accepted, second line of every admin message, not read back from PostgreSQL.
source_kind / source_ref: domain/receipt.py:235-236, 240-245; receipts.py:29-31 (FIND_BY_SOURCE) and find_by_source 76-80; receipts.py:33-36 (FIND_BY_DEDUP_KEY) selects the same three columns; receipts.py:107 (find_other_source) and 161 (_existing) compare them (match = own write); receipts.py:166-169 (_stored_ref); receipts.py:40, 191-192 INSERT; migrations/0002_receipts.sql:16-17, 20 receipts_source_key UNIQUE.
Lines: spar/normalize.py:119-154 (_lines, _line) never sets included_discount (stays 0, receipt.py:82); domain/receipt.py:71-114, 184-227, 168-182, 260-268; receipts.py:138, 197-216 (write_receipt, _insert_lines) INSERT with line_id uuid7, generated amount columns skipped (receipts.py:43); migrations/0002_receipts.sql:23-42.
Settlements: spar/normalize.py:174-203; domain/receipt.py:117-129, 260-268, 271-282; app/pipeline.py:225-232 (_extract); receipts.py:126-129 (write_receipt) reruns both checks before SQL and raises ItemsSettlementMismatch / TotalSettlementMismatch; receipts.py:139, 219-232; migrations/0002_receipts.sql:44-52.
Feed: receipts.py:53, 140 INSERT (receipt_id, 'stored') in the receipt transaction; migrations/0002_receipts.sql:54-59; no code SELECTs from it.

## Dedup lookup
- receipts.py:33-36 and 83-87: `WHERE chain_id = %s AND purchased_at = %s`. receipts.py:90-109 (find_other_source): advisory early check; psycopg.Error returns None. app/pipeline.py:124-137 (precheck) uses pass-1 chain and date/time via normalize_pass1_time (spar/normalize.py:51-63). app/jobs.py:209-211: a hit finishes the job as DUPLICATE. app/service.py:40-41 binds write_receipt and find_other_source. receipts.py:151-163 (_existing) source first, then (chain_id, purchased_at), classifies OWN_WRITE or DUPLICATE; receipts.py:141-147 reruns it on UniqueViolation. migrations/0002_receipts.sql:19-20.

## SQLite job (receipt_json)
- adapters/queue/sqlite.py:54 (_UPGRADES[1]) adds pass1_json, receipt_json, payload_version. app/jobs.py:233-241 (_extract) writes `receipt.model_dump_json()` (store_name, branch_number, receipt_number, store_address, loyalty_card_number, currency, purchased_at, total, lines, settlements; not buyer_name or source). sqlite.py:189-206, 60-64, 292. app/jobs.py:330-336 (_kept_receipt) is the only reader: requires payload_version == PAYLOAD_VERSION, parses with NormalizedReceipt.model_validate_json, None on mismatch or ValidationError. app/jobs.py:253-267 (_write) uses it for pipeline.store. sqlite.py:208-230 (Queue.finish) NULLs the content; sqlite.py:67 (_NO_RECEIPT). pass1_json (with store_name) stored at jobs.py:213-215, read at 339-342, cleared on finish; the unsupported path does not save it.

## resolver_v*
- Exists only as statements or plans: migrations/0001_describe_schema.sql:3 schema comment "read by others only through resolver_v* views"; docs/api-versions.md:6 `resolver_v1 | Provider (feed read by the Resolver) | — | Pending | —`; README.md:51-52 (schema and three roles incl. Resolver read-only provisioned with the database, not by migrations); migrate.py:48 comment that grants are fixed by provisioning.
- Does not exist: no CREATE VIEW, GRANT or role creation for resolver_v* in migrations/ or src/; no file under docs/contracts/ defines resolver_v1. Only view-related file: docs/contracts/chains_v1.sql:30 (`CREATE VIEW public.chains_v1`, the other side's reference view).

## Other
- adapters/postgres/chains.py:15 (QUERY) selects from public.chains_v1; touches no receipt field. docs/contracts/chains_v1.md:12 says no receipt table has a foreign key to the reference. domain/outcomes.py:46-47 and texts.py:62 require the unsupported_chain key in both text sections. Stored and duplicate outcomes carry no receipt field (notify.py:57-58 reaction only).

## Not found
- No SELECT, UPDATE or DELETE of store_name, store_address, loyalty_card_number, receipt_number, branch_number, currency or buyer_name against PostgreSQL. No SELECT from receipt_lines, receipt_settlements or receipt_feed. No view or GRANT over receipt tables. Tests not searched.
