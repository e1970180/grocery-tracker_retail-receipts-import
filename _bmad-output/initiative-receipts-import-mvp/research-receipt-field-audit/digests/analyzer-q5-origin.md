# Analyzer digest Q5: field origin in planning documents @ 7c1c47c

Paths under `_bmad-output/initiative-receipts-import-mvp/`. SPEC = spec-receipts-import/spec-receipts-import.md, OUT = spec-receipts-import/receipt-outcomes.md, ADD = brief-receipts-import/addendum.md, ARCH = architecture-receipts-import/architecture-receipts-import.md, P4A = epic-receipts-pipeline/story-receipt-model-and-storage-plan.md, memlogs = `.memlog.md` in the spec-, brief- and architecture- folders. These documents state intent; they are not evidence of what the code does.

Shape: SPEC and ADD name almost none of the stored field names. P4A sets the field list (owner decisions 2026-10-22 and 2026-10-23). ARCH AD-17 fixes the model's existence and four properties only. ARCH defers the column-level model and the resolver_v1 field list.

Load-bearing claims:
- P4A:30-31 says the reference fields exist "because the Resolver needs them".
- P4A:174 says they are nullable and never part of a key.
- P4A:118 and P4A:123 say the owner confirmed branch_number nullable.
- ARCH:340 and ARCH:343 defer the column model and the resolver_v1 field list.

## chain_id
- SPEC:24 (CAP-2, "chain"); SPEC:64 supported chains.
- ARCH:131 (AD-6): plug-in sets chain_id from its own key, never from model text; seller-OIB cross-check added by owner 2026-10-23.
- ARCH:231 (AD-18): reference table `chains_v1`, chain_id a stable ASCII slug, receipt tables hold chain_id with no FK. ARCH:240 (Conventions): lowercase slugs (kaufland, lidl, dm, mueller, spar). architecture memlog:40: slugs frozen "because part of dedup key".
- P4A:39 [owner 2026-10-23]: never printed or model text; only a reference slug, never `other` or `unreadable`. P4A:90 model validator; P4A:97 CHECK `^[a-z][a-z0-9_]{0,31}$`, no FK per AD-18.
- Reader: dedup key (chain_id, purchased_at), ARCH:149 and P4A:97. Required.

## store_name
- First as "printed store name" in pass 1: ARCH:119 (AD-4); architecture memlog:40 "pass 1 also returns printed store name for the admin".
- ARCH:131 (AD-6): "The printed store name goes into the admin message." The only stated reader, and it concerns pass 1 / an unsupported chain. OUT:11 says the admin gets a Telegram message for an unsupported chain and does not mention store name.
- Not in SPEC; not in ADD.
- P4A:90 lists store_name in NormalizedReceipt, no reason given. P4A:97 lists `store_name text`, with no NULL marker and no NOT NULL (unlike `currency ... NOT NULL`). P4A:118's nullable list names only branch_number, receipt_number, store_address, loyalty_card_number.
- No document says the Resolver reads store_name. P4A:31 lists what the Resolver needs ("receipt number, store address, currency, masked loyalty card and buyer"); store_name is absent.

## branch_number
- SPEC:24 (CAP-2) "branch". ADD:9, 20, 25 per chain: Kaufland PJ####, Lidl IBR/PJ "Keep the leading zeros", DM alphanumeric middle segment of receipt number. ADD:9: Kaufland branch ID must match the receipt-number middle segment.
- P4A:90: keeps leading zeros, may be alphanumeric. P4A:97: text NULL. Rename branch -> branch_number at P4A:128.
- Owner 2026-10-23 (P4A:124): "stays nullable ... a photo may not show it". No stated reader.

## receipt_number
- ADD:43-45 (dedup lesson): legacy dropped the receipt number from the key because OCR misreads it and an `UNKNOWN` sentinel collided. ADD:9 Kaufland format `NNNNN/BBBB/X`; ADD:25 DM `9619/K05F/5`.
- ARCH:149 (AD-8) and architecture memlog:13: receipt number never part of the dedup key.
- First stored: P4A:31 [owner 2026-10-23] "A receipt also stores its receipt number, store address, currency, masked loyalty card and buyer, because the Resolver needs them." P4A:132: added after comparison with the legacy schema.
- P4A:90, :97: nullable text. P4A:118 nullable in model and schema. P4A:97: in neither unique key. P4A:174: nullable because "a photo may not show" it; never part of a key since OCR misreads it.
- No detail on what the Resolver does with it.

## store_address
- SPEC:56 (Constraints, Extraction): images leave the host "including the items, branch address and masked loyalty-card number" (disclosure only). Same in spec memlog:21.
- First stored: P4A:31 (reason: "the Resolver needs them"); P4A:132 added after the legacy-schema comparison. P4A:90, :97 nullable text; P4A:118 nullable; P4A:174 "a photo may not show" it. No stated Resolver use beyond "needs them".

## loyalty_card_number
- SPEC:56: masked loyalty-card number is in the images sent to Gemini. ADD:21 (Lidl): "No loyalty-card number is printed."
- P4A:31 stored "masked loyalty card ... because the Resolver needs them". Rename loyalty_card -> loyalty_card_number at P4A:128.
- P4A:90: optional str, as printed, "may be masked". P4A:97/:118 nullable. P4A:174: nullable because "a photo may not show" it "and Lidl prints no card"; not part of any key.
- No document says required.

## currency
- SPEC:65 "EUR only"; SPEC:75 non-goal "Multiple currencies".
- ARCH:242 (Conventions Money): "Only EUR; the currency column is constrained to EUR (owner decision 2026-10-23)". P4A:31 says the column amends the earlier "only EUR, no currency column" convention.
- P4A:90 `Literal["EUR"]` default "EUR"; P4A:97 `currency text NOT NULL CHECK (= 'EUR')`. P4A:174: "a second currency is a deliberate change". Listed among fields the Resolver needs (P4A:31).

## purchased_at
- SPEC:24 "purchase date and time"; ADD:10 Kaufland date from fiscal URL; SPEC:89 unreadable date is a no-valid-result case.
- ARCH:218 (AD-17): converted Europe/Zagreb -> aware UTC once, in domain. ARCH:149 (AD-8): dedup key (chain, timestamp to the minute), owner 2026-10-22 (Spar prints no seconds), superseding to-the-second (architecture memlog:13 vs :58). ARCH:243: contract timestamps ISO-8601 UTC with `Z` plus Zagreb local time with offset.
- P4A:92: aware UTC, zero seconds/microseconds. P4A:97 `purchased_at timestamptz`, unique (chain_id, purchased_at).

## total
- Not in SPEC as a field. OUT:13 (owner 2026-10-23): printed total vs card plus cash mismatch is a failure row. ADD:40: for cash payments, record the receipt total and ignore the change.
- P4A:38 [owner 2026-10-23]: second check total = card + cash +/-0.01, failing as `total_settlement_mismatch`; "The total is then derivable from the settlements, so it is not stored." P4A:103 writer never writes the total; P4A:129 owner dropped the total column; P4A:173 total stays in the SQLite job; the Resolver contract may expose card plus cash as the amount paid.
- P4A:90 NormalizedReceipt still has `total`.

## lines
- SPEC:27 (CAP-3): keeps what was printed, plus the regular price before discount and the effective price paid. ADD:34-39 pricing logic. ARCH:125 (AD-5): model returns printed values only; code derives regular/effective.
- P4A:88 (model) and :98 (table): printed_text, quantity (> 0, numeric(12,3)), unit, unit_price, printed_amount, included_discount and separate_discount (default 0, >= 0), discount_text; regular_amount and effective_amount GENERATED STORED. P4A:158, :172: single discount "kind" replaced by two amounts because a Kaufland item can carry both (ADD:13).
- kind and cancels_line: model only (P4A:88), not stored. Storno/return rules P4A:34 (netted into the sale line, never stored); P4A:33 return-only receipt not stored. ADD:26 (DM STORNO RETKA: "drop both") is earlier, different wording; P4A:171: which line a storno cancels is the plug-in's reading.
- P4A:35 line_id UUIDv7; ARCH:241. P4A:170: stored lines can exceed settlements when a receipt has a return; the Resolver contract must say so.

## settlements
- SPEC:30-31 (CAP-4): card, cash, bonus points, coupons, deposit refunds; amount may be negative. ADD:30-32 Müller bonus points.
- P4A:88: kinds card, cash, bonus_points, coupon, deposit_refund; printed_text; signed amount (bonus_points/coupon/deposit_refund > 0; card and cash may be negative). P4A:99 table keyed (receipt_id, settlement_no). P4A:171, :178 rationale.

## buyer_name
- Not in SPEC, ADD, ARCH. P4A:31 [owner 2026-10-23]: "The buyer comes from the source, not the image: for Telegram it is the sender's name." Listed among fields the Resolver needs. P4A:92 ReceiptSource.buyer_name non-empty. P4A:97 `buyer_name text` (no NULL marker). P4A:132 added after the legacy-schema comparison.

## source_kind / source_ref
- ARCH:157 (AD-9) and architecture memlog:12: store the intake source reference on the receipt row so a dedup conflict from the same source is the job's own earlier write. Owner 2026-10-23: kind + reference text; Telegram ref `<chat_id>:<message_id>`.
- P4A:35, :92, :97: source_kind text with no CHECK; unique (source_kind, source_ref). P4A:30 (owner 2026-10-22): own-write lookup moved into 4a. P4A:104 lookup order.

## payload_version
- ARCH:220 (AD-17): job row carries it; mismatch on resume sends the job to extract_pending without consuming an attempt. P4A:89 `PAYLOAD_VERSION = 1`; P4A:90. Not a PostgreSQL column (P4A:97).

## seller_oib
- ARCH:131 (AD-6): plug-in rejects as `invalid` when the printed seller OIB is not one of the chain's OIBs in the reference (owner 2026-10-23). ARCH:231 (AD-18): chains_v1 gains OIBs from 1.1.0. P4A:39, :127. Not a field in NormalizedReceipt or in the receipts table (P4A:90, :97).

## resolver_v1
- SPEC:50-52 (CAP-11): contract in docs/contracts/, semver, recorded in docs/api-versions.md. SPEC:91: handoff mechanism deferred to architecture.
- ARCH:181 (AD-12): read-only views in a `resolver_v<major>` schema exposing the feed (bigint `seq` + receipt_id) and "the stored receipt data"; Resolver has SELECT on that schema only. Architecture memlog:20: feed + views, LISTEN/NOTIFY only a hint.
- ARCH:343 (Deferred): "Contract field list for resolver_v1" written with the CAP-11 story; ARCH:340: column-level model deferred to the storage story.
- No document read lists resolver_v1 fields. Statements of what the Resolver needs: P4A:31 (receipt number, address, currency, masked loyalty card, buyer), P4A:170, P4A:173, ARCH:243.

## Conflicts and tensions between documents
1. Dedup key granularity: SPEC:91 and architecture memlog:13 (to the second) vs ARCH:149, P4A:30, architecture memlog:58 (to the minute); memlog:58 states it supersedes.
2. "No currency column" (earlier ARCH Conventions, quoted in P4A:31) vs ARCH:242 (column with CHECK). Resolved in later text.
3. SPEC:67 "no manual-correction path" vs P4A:32 (admin delete, owner 2026-10-23).
4. SPEC CAP-5 (SPEC:33-34) names only items vs settlement; OUT:13 / P4A:38 add the total check.
5. ADD:26 "drop both" for DM storno vs P4A:34 netting; ADD:3 labels the addendum "reference material, not a decision".
6. store_name: pass-1 "printed store name" (ARCH:119, :131) is defined for the admin message; P4A:90 puts it in the persisted model and table without a stated reason; absent from the P4A:31 Resolver list; nullability not stated in P4A:97/:118 unlike the four reference fields.
7. SPEC:24 (CAP-2) lists "chain, branch" as extraction targets; P4A:124 makes branch_number nullable.
8. P4A:90 keeps `total` in the model while P4A:38/:103 do not store it.

## Not found
- No explicit "required" statement for store_name, and no stated reader of store_name besides the admin message in AD-6.
- No reason for store_address and loyalty_card_number beyond "the Resolver needs them" (P4A:31); no consumer behavior described.
- No resolver_v1 column list; docs/contracts/ not read by this analyzer.
- seller_oib: no stored or model field in these documents.
- brief and spec memlogs: nothing on store_name, stored address, receipt number, buyer, currency, OIB; spec memlog:21 repeats the data-leaves-host list; brief memlog:10 says unrecognized store/date goes to manual correction (later superseded by SPEC:89 and OUT:14).
- Not read: ARCH lines 20-114 and 183-195; deferred-work.md (outside the granted list).
