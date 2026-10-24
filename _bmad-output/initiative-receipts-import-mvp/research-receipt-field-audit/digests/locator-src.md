# Locator digest: src/ @ 7c1c47c

(The locator also opened files; claims below are unverified until an analyzer and verifier confirm them.)

## Q1 model vs schema

- src/retail_receipts_import/domain/receipt.py:144 (NormalizedReceipt) @ 7c1c47c: payload_version Literal[1]; chain_id str (validator _chain_is_known_slug :160, slug regex, not in RESERVED_IDS); store_name str min_length=1 (required); branch_number, receipt_number, store_address, loyalty_card_number str|None; currency Literal["EUR"] default "EUR"; purchased_at PurchasedAt (AwareDatetime, UTC, zero seconds/microseconds, :132-141); total Money (Decimal, 12 digits, 2 places); lines list[ReceiptLine] min_length=1; settlements list[Settlement] min_length=1; extra="forbid", frozen. Validator _netting_is_sound :168 calls stored_lines() :184.
- receipt.py:71 (ReceiptLine): kind LineKind default SALE; cancels_line int|None; printed_text min_length=1; quantity Quantity (12,3); unit str|None; unit_price Money|None; printed_amount Money; included_discount/separate_discount Money default 0; discount_text str|None; _signs_follow_kind :86.
- receipt.py:117 (Settlement): kind SettlementKind; printed_text min_length=1; amount Money; _sign_follows_kind :124.
- receipt.py:230 (ReceiptSource): kind SourceKind (telegram), ref min_length=1, buyer_name min_length=1.
- receipt.py:260 check_consistency (TOLERANCE 0.01, :31); receipt.py:271 check_total.
- migrations/0002_receipts.sql: see locator-migrations-docs.md. source_kind/source_ref have no DB CHECK; store_name has no emptiness CHECK.
- src/retail_receipts_import/domain/jobs.py:43 Job.payload_version int|None (job-level).

## Q2 Spar fill path

- src/retail_receipts_import/domain/chains/spar/schema.py:27 (SparPass2): seller_oib str|None (:28); store_name str required (:31); store_address str|None (:32); receipt_number str|None default null (:33); purchase_date, purchase_time str required (:36-37); total str required (:38); lines (:39); payments (:40). SparLine :10; SparPayment :22. No card-slip field.
- src/retail_receipts_import/adapters/gemini/client.py:58 (GeminiClient): response_json_schema=schema.model_json_schema().
- src/retail_receipts_import/domain/chains/spar/__init__.py:18-19 (SparPlugin): pass2_prompt, pass2_schema; :24 seller_oib(); :32 normalize() passes chain id from the plugin.
- src/retail_receipts_import/domain/chains/spar/prompt.py:3 (PASS2_PROMPT): store_name from the line under MB/OIB, never "SPAR HRVATSKA D.O.O." (:8-10); store_address line under store line (:11); date/time from the "Vaša kupnja dana" line (:12-13); receipt_number after "Broj računa:" (:14); excludes card slip, ZKI, JIR (:25-26).
- src/retail_receipts_import/app/pipeline.py:213 (_extract): generate with plugin.pass2_prompt/pass2_schema; :226/:230 check_consistency, check_total.
- src/retail_receipts_import/domain/chains/spar/normalize.py:28 (normalize): schema failure -> UnreadableReceipt (:33). NormalizedReceipt built :35-46:
  - store_name = raw.store_name.strip() (:38); empty fails min_length -> UnreadableReceipt (:47-48).
  - branch_number = _branch(raw.receipt_number) (:39, :72): split on "/", needs 3 all-digit segments else UnreadableReceipt; returns middle segment; None when receipt_number missing.
  - receipt_number = _stripped (:40, :66): empty/None -> None.
  - store_address = _stripped (:41): empty/None -> None.
  - purchased_at = zagreb_to_utc(...) (:42, :83); total = _money (:43, :96).
  - lines = _lines (:119); settlements = _settlements (:174).
  - currency not read from the response (default EUR, receipt.py:154).
  - loyalty_card_number: not read by SparPass2 or normalize; always None.
  - seller_oib: read only by SparPlugin.seller_oib (spar/__init__.py:24-30); not in the receipt.
- spar/normalize.py:51 (normalize_pass1_time).
- src/retail_receipts_import/domain/chains/pass1.py:11-13 (Pass1Response): store_name str|None default None, pass 1 only.

## Q3 readers/writers

- Writer: src/retail_receipts_import/adapters/postgres/receipts.py:38-40 (INSERT_RECEIPT) lists receipt_id, chain_id, store_name, branch_number, receipt_number, store_address, loyalty_card_number, currency, purchased_at, buyer_name, source_kind, source_ref; :44-46 INSERT_LINE; :49-50 INSERT_SETTLEMENT; :53 INSERT_FEED_STORED; :126-129 write_receipt runs check_consistency, check_total; :138 inserts receipt.stored_lines(); :172-190 _insert_receipt; :197-214 _insert_lines; :219-229 _insert_settlements.
- Dedup: receipts.py:33-35 (FIND_BY_DEDUP_KEY) chain_id + purchased_at only; :83 find_by_dedup_key; :90 find_other_source; :151 _existing. app/pipeline.py:124 (precheck) calls ports.find_other_source (:136). app/service.py:41 wiring.
- Notification: app/notify.py:116-142 reads store_name from Unsupported (app/jobs.py:284 passes result.store_name to _finish :355; :362, :375); notify.py:138 appends store_name to admin text when present. Unsupported store_name from pass 1 (app/pipeline.py:195-196, stripped, None if empty). notify.py:140 uses item.buyer_name.
- Job state: app/jobs.py:330 _kept_receipt, :350 _source -> telegram_source (domain/receipt.py:240); :239 payload_version=PAYLOAD_VERSION; adapters/queue/sqlite.py:24-67 jobs table (buyer_name, receipt_json, payload_version, receipt_id); :105; :195-203.
- Chain reader: adapters/postgres/chains.py:15 QUERY (chain_id, display_name, aliases, seller_oibs, active from chains_v1); :98-109 _row_fault. app/alerts.py:57, :67. app/pipeline.py:173-178, :203. domain/chains/pass1.py:24 create_pass1_schema.

Not found in src/: any reader of loyalty_card_number; any reader of branch_number other than the INSERT; any reader of currency other than INSERT/default; any code reading store_address back; any use of a `deleted` feed event (only 'stored' is inserted, receipts.py:53); any read of receipt_feed. regular_amount (receipt.py:109) has no src caller; effective_amount used at :265 and :218.
