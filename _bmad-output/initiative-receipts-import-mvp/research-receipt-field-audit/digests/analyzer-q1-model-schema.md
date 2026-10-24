# Analyzer digest Q1: model and schema @ 7c1c47c

R = src/retail_receipts_import/domain/receipt.py, M = migrations/0002_receipts.sql. Two files read in full. Not run.

## Model (R)
- Module docstring R:1-5 (module): Money is Decimal, "because floats would drift from the numeric(12,2) columns". Money = Decimal max_digits=12, decimal_places=2 (R:33); Quantity max_digits=12, decimal_places=3 (R:34). PAYLOAD_VERSION=1 (R:25). TOLERANCE 0.01 (R:30-31), comment "off by a cent after rounding; anything larger is a misread". STORE_TIMEZONE Europe/Zagreb (R:27-28).
- Enums: SettlementKind card/cash/bonus_points/coupon/deposit_refund (R:37-42); LineKind sale/storno/return (R:45-48); SourceKind telegram only (R:51-52). ItemsSettlementMismatch R:55-60; TotalSettlementMismatch R:63-68 (defined; raised nowhere in these two files).

NormalizedReceipt (R:144-182), extra=forbid, frozen (R:145):
- payload_version Literal[1], required (R:147).
- chain_id str, required (R:148); _chain_is_known_slug R:160-166 rejects a value that is not a reference slug or is in RESERVED_IDS.
- store_name str, min_length=1 (R:149).
- branch_number, receipt_number, store_address, loyalty_card_number: str|None = None, no other check (R:150-153).
- currency Literal["EUR"] = "EUR" (R:154).
- purchased_at PurchasedAt (R:141, 155): _utc_to_the_minute R:132-138 rejects non-UTC offset and nonzero seconds/microseconds; naive datetimes rejected by AwareDatetime.
- total Money, required (R:156). lines list[ReceiptLine] min_length=1 (R:157). settlements list[Settlement] min_length=1 (R:158).
- _netting_is_sound R:168-182 (load-bearing): rejects cancels_line target out of range (R:174-175), at or after own position (R:176-177), or not a SALE line (R:178-179); then calls stored_lines() so a bad receipt fails in the model, not inside the write (R:180-181).

ReceiptLine (R:71-114): kind default SALE (R:74); cancels_line (R:75-76); printed_text min_length=1 (R:77); quantity (R:78); unit (R:79); unit_price Money|None (R:80); printed_amount (R:81); included_discount, separate_discount default 0 (R:82-83); discount_text (R:84). _signs_follow_kind R:86-106 (load-bearing): SALE rejects cancels_line, quantity <= 0, any negative amount (R:91-96); STORNO requires cancels_line (R:98-99); RETURN rejects cancels_line (R:100-101); storno/return reject quantity >= 0 and any amount > 0 (R:102-105). regular_amount = printed + included (R:108-110); effective_amount = printed - separate (R:112-114). unit_price has no sign check; unit and discount_text have no validator.

Settlement (R:117-129): kind, printed_text min_length=1, amount Money. _sign_follows_kind R:124-129 rejects amount <= 0 for kinds other than card/cash; zero allowed for card/cash.

ReceiptSource (R:230-237): kind SourceKind, ref min_length=1, buyer_name min_length=1; not a field of NormalizedReceipt. telegram_source builds ref f"{chat_id}:{message_id}" (R:240-245).

stored_lines() R:184-227 (load-bearing): returns purchased lines with each storno netted into its sale line; return lines and lines netted to zero quantity are dropped; raises ValueError for netting below zero (R:216-217), effective_amount < 0 (R:218-219), zero quantity with money left (R:220-222), no lines left (R:225-226).

zagreb_to_utc R:248-257: rejects tz-aware input, zeroes seconds and microseconds.

check_consistency R:260-268 (load-bearing): sum of effective_amount over all lines (storno/return included) minus sum of all settlement amounts; returns difference when abs > TOLERANCE else None; does not raise and does not use total. check_total R:271-282 (load-bearing): total minus sum of card and cash settlements; returns difference when abs > 0.01. Neither is called by a validator in R.

## Tables (M)
- Header comment M:1-2: storno and return lines are netted or dropped before the write, so every stored line is a purchase; the feed is a log that outlives its receipt.
- receipts (M:4-21): receipt_id uuid PK; chain_id text NOT NULL CHECK regex `^[a-z][a-z0-9_]{0,31}$` and NOT IN ('other','unreadable') (M:6-7); store_name text NOT NULL (no length check, M:8); branch_number, receipt_number (M:10), store_address (M:11), loyalty_card_number (M:12) text NULL; currency text NOT NULL CHECK = 'EUR' (M:13); purchased_at timestamptz NOT NULL (no minute/UTC check); buyer_name text NOT NULL; source_kind text NOT NULL (no CHECK); source_ref text NOT NULL; created_at default now(). UNIQUE (chain_id, purchased_at) M:19; UNIQUE (source_kind, source_ref) M:20.
- receipt_lines (M:23-42): see locator-migrations-docs.md; quantity CHECK > 0 (M:29); discounts CHECK >= 0 (M:33-34); generated regular_amount (M:36-37) and effective_amount with CHECK >= 0 (M:38-40); UNIQUE (receipt_id, line_no) M:41. No kind or cancels_line columns; no CHECK on printed_amount sign.
- receipt_settlements (M:44-52): kind CHECK of five values (M:48); amount NOT NULL, no sign check; PK (receipt_id, settlement_no).
- receipt_feed (M:54-59): seq identity PK; receipt_id without FK; event CHECK IN ('stored','deleted'); UNIQUE (receipt_id, event). No model counterpart.

## Mapping model -> columns
- Stored on receipts under the same names: chain_id, store_name, branch_number, receipt_number, store_address, loyalty_card_number, currency, purchased_at. From ReceiptSource: kind -> source_kind, ref -> source_ref, buyer_name -> buyer_name. DB-only: receipt_id, created_at.
- Not stored: payload_version (no column), total (no column; used by check_total only), the unnetted lines list, ReceiptLine.kind and cancels_line.
- Line/settlement columns map 1:1 plus DB-only ids and numbering. Which line_no numbering is used was not established here.

## Model rule vs column rule
- store_name, printed_text, source ref, buyer_name: model min_length=1; columns NOT NULL only.
- purchased_at: model requires UTC and zero seconds; column is plain timestamptz.
- chain_id: model uses is_chain_id plus RESERVED_IDS (domain/chains.py not read); column regex plus two excluded sentinels.
- source_kind: model enum (telegram only); column unconstrained text.
- Settlement amount: model rejects <= 0 for non-card/cash; column has no sign check.
- lines/settlements min_length=1: no DB counterpart. Uniqueness constraints exist only in the DB. check_total and check_consistency exist only in the model side.

Not found / limits: only the two named files read; domain/chains.py, repository insert code, callers of the checks, and later migrations not read.
