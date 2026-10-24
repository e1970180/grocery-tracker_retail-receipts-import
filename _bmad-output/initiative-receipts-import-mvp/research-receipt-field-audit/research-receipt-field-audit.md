---
title: 'Codebase research: receipt field audit'
type: codebase
ask: |-
  Which receipt fields are saved (NormalizedReceipt in domain/receipt.py, tables in migrations/0002_receipts.sql), what each means, where each came from, what Spar fills and what Lidl and other chains print, who reads each field (writer, notify, future resolver_v1), and whether store_name, store_address, loyalty_card_number and receipt_number are needed and needed as required, before resolver_v1 is frozen.
repository: 'D:/MyGitProjects/grocery-tracker/retail-receipts-import'
commit: '7c1c47c08b67c806e1be785d96941b1fcee64de9'
branch: 'main'
status: draft
validation: 'normal'
claims:
  verified: 22
created: '2026-10-24'
updated: '2026-10-24'
---

# Codebase research: receipt field audit

Readers: the plan step that decides the resolver_v1 field list, and a person checking one claim. This document states what the code, the fixtures and the planning documents say at commit 7c1c47c. It makes no recommendation; the recommendation table is a separate piece made afterwards. Full agent reports are in `digests/`. Questions 4 and 5 read sources outside the commit by owner grant: Q4 the untracked sample receipts in `doc-inbox/fixtures/`, Q5 the planning documents, which state intent and are not evidence of what the code does. The working tree held two uncommitted files in `_bmad-output/` that this research did not see.

## Questions

1. (how) Fields and columns: types, optionality, checks.
2. (how) How Spar fills each field.
3. (what touches) Who reads or writes each field.
4. (where) What each chain prints, from samples.
5. (why) Where each field came from in the planning documents.
6. (how is it tested) Which tests pin each field.

## 1. Fields and columns

`NormalizedReceipt` (extra fields forbidden, frozen) is defined at src/retail_receipts_import/domain/receipt.py:144-158 (NormalizedReceipt) @ 7c1c47c.

- Required: payload_version, fixed to 1 (src/retail_receipts_import/domain/receipt.py:147 (payload_version) @ 7c1c47c); chain_id, which must be a reference slug and not a reserved id (src/retail_receipts_import/domain/receipt.py:160-166 (_chain_is_known_slug) @ 7c1c47c); store_name, a string with min_length=1, so required and non-empty (src/retail_receipts_import/domain/receipt.py:149 (store_name) @ 7c1c47c); purchased_at, aware UTC with zero seconds (src/retail_receipts_import/domain/receipt.py:132-138 (_utc_to_the_minute) @ 7c1c47c); total (src/retail_receipts_import/domain/receipt.py:156 (total) @ 7c1c47c); lines and settlements, each with at least one entry (src/retail_receipts_import/domain/receipt.py:157-158 (settlements) @ 7c1c47c).
- Optional with no other check: branch_number, receipt_number, store_address and loyalty_card_number, each `str | None = None` (src/retail_receipts_import/domain/receipt.py:150-153 (loyalty_card_number) @ 7c1c47c). currency is `Literal["EUR"]` with default "EUR" (src/retail_receipts_import/domain/receipt.py:154 (currency) @ 7c1c47c).
- Source data is a separate type, not a field of the receipt: `ReceiptSource` holds kind, ref and buyer_name, the last two with min_length=1 (src/retail_receipts_import/domain/receipt.py:230-237 (ReceiptSource) @ 7c1c47c).
- Lines and settlements: line signs follow kind (src/retail_receipts_import/domain/receipt.py:86-106 (_signs_follow_kind) @ 7c1c47c); a settlement amount must be above zero for kinds other than card and cash (src/retail_receipts_import/domain/receipt.py:124-129 (_sign_follows_kind) @ 7c1c47c); `stored_lines` nets storno into sales, drops returns and zero-quantity lines, and raises when none remain (src/retail_receipts_import/domain/receipt.py:184-227 (stored_lines) @ 7c1c47c).
- `check_consistency` compares line effective amounts to all settlements within 0.01, and `check_total` compares `total` to card plus cash within 0.01; both return a difference and neither raises (src/retail_receipts_import/domain/receipt.py:260-268 (check_consistency) @ 7c1c47c; src/retail_receipts_import/domain/receipt.py:271-282 (check_total) @ 7c1c47c).

The `receipts` table is at migrations/0002_receipts.sql:4-21 (receipts) @ 7c1c47c: receipt_id uuid primary key; chain_id NOT NULL with a slug regex and `NOT IN ('other','unreadable')`; store_name NOT NULL with no length check (migrations/0002_receipts.sql:8 (store_name) @ 7c1c47c); branch_number, receipt_number, store_address and loyalty_card_number nullable (migrations/0002_receipts.sql:9-12 (loyalty_card_number) @ 7c1c47c); currency NOT NULL with CHECK = 'EUR' (migrations/0002_receipts.sql:13 (currency) @ 7c1c47c); purchased_at timestamptz NOT NULL; buyer_name, source_kind, source_ref NOT NULL; two unique keys, (chain_id, purchased_at) and (source_kind, source_ref) (migrations/0002_receipts.sql:19-20 (receipts_chain_purchased_key) @ 7c1c47c). Child tables are receipt_lines (migrations/0002_receipts.sql:23-42 (receipt_lines) @ 7c1c47c), receipt_settlements (migrations/0002_receipts.sql:44-52 (receipt_settlements) @ 7c1c47c) and receipt_feed, which has no foreign key so it outlives its receipt (migrations/0002_receipts.sql:54-59 (receipt_feed) @ 7c1c47c).

Mapping and differences, from digests/analyzer-q1-model-schema.md: the eight receipt fields above plus buyer_name, source_kind and source_ref are stored on `receipts`; payload_version, total, line kind and cancels_line have no column. The model's min_length=1 has no column counterpart; the UTC and zero-seconds rule on purchased_at is model only; source_kind is an enum in the model and unconstrained text in the column; the two unique keys exist only in the database.

Not found: any `CREATE INDEX` or table or column comment in the migration (migrations/0002_receipts.sql:1-59 (receipts) @ 7c1c47c); validators on unit, unit_price and discount_text. This question did not read the chain-id helpers or later migrations.

## 2. How Spar fills each field

Pass 2 sends the PDF with the Spar prompt and schema and normalizes the reply (src/retail_receipts_import/app/pipeline.py:213 (_extract) @ 7c1c47c; src/retail_receipts_import/domain/chains/spar/normalize.py:28-48 (normalize) @ 7c1c47c). Pass 1 asks only for chain, store name, date and time; its store name is used only for an unsupported chain and its date and time only for the resend pre-check (src/retail_receipts_import/app/pipeline.py:195-196 (_detect_chain) @ 7c1c47c; src/retail_receipts_import/app/pipeline.py:124-137 (precheck) @ 7c1c47c).

- chain_id: a constant "spar" from the plug-in key, never model text (src/retail_receipts_import/domain/chains/spar/__init__.py:32-34 (normalize) @ 7c1c47c).
- store_name: required in the response schema, "Store line under the company OIB line" (src/retail_receipts_import/domain/chains/spar/schema.py:31 (store_name) @ 7c1c47c); the prompt says the line under the MB and OIB line, never "SPAR HRVATSKA D.O.O." (src/retail_receipts_import/domain/chains/spar/prompt.py:9-10 (PASS2_PROMPT) @ 7c1c47c); it is stripped, and a missing or empty value makes the receipt unreadable (src/retail_receipts_import/domain/chains/spar/normalize.py:38 (normalize) @ 7c1c47c).
- store_address: optional, the line under the store line (src/retail_receipts_import/domain/chains/spar/schema.py:32 (store_address) @ 7c1c47c); blank becomes None (src/retail_receipts_import/domain/chains/spar/normalize.py:41 (normalize) @ 7c1c47c).
- receipt_number: optional, the value after "Broj računa:" as printed (src/retail_receipts_import/domain/chains/spar/schema.py:33-35 (receipt_number) @ 7c1c47c); blank becomes None (src/retail_receipts_import/domain/chains/spar/normalize.py:40 (normalize) @ 7c1c47c).
- branch_number: no prompt and no schema field; it is the middle segment of receipt_number (src/retail_receipts_import/domain/chains/spar/normalize.py:72-80 (_branch) @ 7c1c47c). A receipt_number that is not three numeric segments makes the whole receipt unreadable (src/retail_receipts_import/domain/chains/spar/normalize.py:78-79 (_branch) @ 7c1c47c), so an optional field can fail a receipt.
- loyalty_card_number: no source. It is not in the schema, the prompt or the normalizer, so Spar always stores NULL (src/retail_receipts_import/domain/receipt.py:153 (loyalty_card_number) @ 7c1c47c). The schema deliberately has no card-slip field so card numbers and terminal ids never leave the PDF (src/retail_receipts_import/domain/chains/spar/schema.py:1-4 (SparPass2) @ 7c1c47c).
- currency: no source, the model default (src/retail_receipts_import/domain/receipt.py:154 (currency) @ 7c1c47c).
- purchased_at: taken only from the line "Vaša kupnja dana DD.MM.YYYY. u HH:MM sati", never the card slip (src/retail_receipts_import/domain/chains/spar/prompt.py:12-13 (PASS2_PROMPT) @ 7c1c47c); Zagreb time converted to UTC at minute precision (src/retail_receipts_import/domain/receipt.py:248-257 (zagreb_to_utc) @ 7c1c47c).
- seller_oib is read by the plug-in but not stored; the pipeline returns Invalid when it is missing or not in the chain reference (src/retail_receipts_import/app/pipeline.py:221-223 (_extract) @ 7c1c47c).
- total, lines and settlements come from the UKUPNO amount, the item and discount rows and the payment rows (src/retail_receipts_import/domain/chains/spar/normalize.py:119-139 (_lines) @ 7c1c47c; src/retail_receipts_import/domain/chains/spar/normalize.py:174-203 (_settlements) @ 7c1c47c).

Fixtures (tests/fixtures/spar/0100, 1402, 2600 and 7088; expected.json and pass2.json): store_name is "SPAR SUPERMARKET ZG-BAKIĆEVA" in 0100 and "INTERSPAR ARENA ZAGREB" in the other three; store_address is "Vojina Bakića 1, 10000 Zagreb" and "V.Vukova 6, 10000 Zagreb"; receipt_number is "56786/87085/102", "31104/8714/153", "3169/8714/103" and "45984/8714/154"; branch_number is "87085" and "8714". No loyalty text appears in any of the twelve Spar fixture files. Currency is absent from every expected.json.

## 3. Who reads or writes each field

- Load-bearing: no code selects any stored receipt column other than receipt_id, source_kind and source_ref. The only SELECTs on `receipts` are the two lookups (src/retail_receipts_import/adapters/postgres/receipts.py:29-36 (FIND_BY_SOURCE) @ 7c1c47c).
- Load-bearing: loyalty_card_number, store_address, receipt_number, branch_number and currency are only inserted, never read (src/retail_receipts_import/adapters/postgres/receipts.py:38-41 (INSERT_RECEIPT) @ 7c1c47c; src/retail_receipts_import/adapters/postgres/receipts.py:183-188 (_insert_receipt) @ 7c1c47c). Nothing gives loyalty_card_number a value (src/retail_receipts_import/domain/chains/spar/normalize.py:35-46 (normalize) @ 7c1c47c).
- Dedup uses chain_id and purchased_at; the source columns only decide whether a hit is the job's own earlier write (src/retail_receipts_import/adapters/postgres/receipts.py:33-36 (FIND_BY_DEDUP_KEY) @ 7c1c47c; src/retail_receipts_import/adapters/postgres/receipts.py:151-163 (_existing) @ 7c1c47c). The pre-check uses the same pair from pass 1 (src/retail_receipts_import/app/pipeline.py:124-137 (precheck) @ 7c1c47c).
- store_name outside the table: for an unsupported chain it comes from pass 1 (src/retail_receipts_import/app/pipeline.py:195-196 (_detect_chain) @ 7c1c47c) and is appended as its own line to the admin message only (src/retail_receipts_import/app/notify.py:138-143 (_admin_text) @ 7c1c47c). The sender message has no store name (texts/messages.toml:14 (unsupported_chain) @ 7c1c47c). Stored and duplicate outcomes carry no receipt field in any message.
- buyer_name comes from the Telegram sender (src/retail_receipts_import/app/jobs.py:350-352 (_source) @ 7c1c47c), is stored on the receipt row, and is also read from the SQLite job for the second line of every admin message (src/retail_receipts_import/app/notify.py:140 (_admin_text) @ 7c1c47c).
- While a job is pending, the SQLite job holds the whole normalized receipt as JSON (src/retail_receipts_import/app/jobs.py:233-241 (_extract) @ 7c1c47c). Its only reader is the writer step (src/retail_receipts_import/app/jobs.py:330-336 (_kept_receipt) @ 7c1c47c); the content is cleared on finish (src/retail_receipts_import/adapters/queue/sqlite.py:208-230 (finish) @ 7c1c47c).
- The feed gets one `stored` row per write in the same transaction (src/retail_receipts_import/adapters/postgres/receipts.py:53 (INSERT_FEED_STORED) @ 7c1c47c); no code selects from it.
- Load-bearing: no `resolver_v*` view, schema or grant exists in migrations or code. It appears as a schema comment, "read by others only through resolver_v* views" (migrations/0001_describe_schema.sql:3 (retail_receipts_import) @ 7c1c47c), as a "Pending" row in the version table (docs/api-versions.md:6 (resolver_v1) @ 7c1c47c), and in a README note that roles are provisioned with the database (README.md:51-52 (migrate) @ 7c1c47c). No file under docs/contracts/ defines resolver_v1.
- Not found: an UPDATE or DELETE of receipt columns; a SELECT from receipt_lines, receipt_settlements or receipt_feed; a view or GRANT over the receipt tables.

## 4. What the sample receipts print

Sources: working-tree files in doc-inbox/fixtures, not in the commit; samples only (Lidl 5 of 34, Müller 5 of 10, Kaufland 4 of 208, DM 5 of 9, Spar 4 of 21). Full tables in digests/analyzer-q4-printed-fields.md.

| Field | Lidl | Müller | Kaufland | DM | Spar |
|---|---|---|---|---|---|
| Store name | only legal entity "Lidl Hrvatska d.o.o. k.d."; no shop name; shop number "PJ: 0269" next to OIB | company "Müller trgovina Zagreb d.o.o", then a mall name ("Zagreb EKZ Arena") | legal entity "Kaufland Hrvatska k.d."; shop "PJ5230,Zagreb Blato" | "dm-drogerie markt d.o.o." in 2 of 5 samples, none in 3 | company line, then a store line ("SPAR SUPERMARKET ZG-BAKIĆEVA", "INTERSPAR ARENA ZAGREB") |
| Shop address | last header line ("Julija Knifera 10, Zagreb"); printed again in the app footer | street with postcode and phone under the mall name | shop street only ("Jaruscica 6"), no postcode | in 2 of 5 samples; company address on all | line under the store line |
| Receipt number | "Br.raČ.:" `n/POSL<PJ>/digits`, plus "IBR:" | "RB :n/4981/3" | "Racun 279763/5230/4" | "Br. racuna: 5999/K05F/2" (label varies) | "Broj računa:3169/8714/103" |
| Loyalty card number | not printed; only Lidl Plus discount lines | not printed; "Müller bodovi" amounts | "Kaufland Card: xxxxx8265", masked | not printed; points text in one sample | not printed |
| Cashier or till | "Blagajnik <n>" | "Oznaka Operatera:<n>" | "Blagajnik: 115", "POS: 4" | "Blagajnik: <n>" | "Blag. 90010834 Kasa 103" |
| Date and time | "Datum: DD.MM.YYYY HH:MM:SS" | card block, plus a barcode caption without seconds | two forms in one receipt, yy/mm/dd and dd.mm.yy | header `dd.mm.yyyy hh:mm`, repeated four times | "Vaša kupnja dana … u HH:MM sati", no seconds |
| Payment | "Kartica", "Novčanice" with "Ostatak" | "PLACANJE KARTICOM", "GOTOVINA" | "Kartica", "Za platiti" | "MASTERCARD EUR -4,70" (negative) | "PLAĆANJE MASTERCARD", split tender in one |

Other observations from the samples: all Lidl sample files are app screenshots or forwarded images of a "Digitalni račun", not paper photos; Müller M1 and M5 are the same receipt; Kaufland PDFs repeat the receipt twice and print points in two places; file-name dates do not match printed dates in some Lidl and Kaufland files; one Lidl and one Kaufland sample are HRK-to-EUR transition receipts. Not found: a loyalty card number on Lidl, Müller, DM or Spar; cashier names; item article codes.

## 5. Where each field came from in the planning documents

Intent documents, not evidence of behavior. Full per-field record in digests/analyzer-q5-origin.md. Abbreviations: P4A = story-receipt-model-and-storage-plan.md, ARCH = architecture document, SPEC = spec, ADD = addendum.

- The spec and addendum name almost none of the stored fields; P4A sets the list from owner decisions on 2026-10-22 and 2026-10-23. ARCH AD-17 fixes the model's existence and four properties and defers the column-level model and the resolver_v1 field list (ARCH:340, ARCH:343).
- Load-bearing: P4A:30-31 says a receipt "also stores its receipt number, store address, currency, masked loyalty card and buyer, because the Resolver needs them"; the list was added after comparing with the legacy schema (P4A:132). P4A:174 says they are nullable and never part of a key because a photo may not show them, "and Lidl prints no card", and OCR misreads the receipt number (P4A:97, P4A:174; ARCH:149 for the key).
- store_name: first appears as the "printed store name" in pass 1 for the admin message (ARCH:119 AD-4; ARCH:131 AD-6). P4A:90 lists it in the persisted model and P4A:97 lists `store_name text` without a NULL marker, but it is absent from P4A:31's list of what the Resolver needs and from the nullable list at P4A:118. No document gives a reader other than the admin message.
- branch_number: SPEC:24 lists "branch" as an extraction target; owner on 2026-10-23 made it nullable because a photo may not show it (P4A:124).
- chain_id is required, part of the dedup key, and a reference slug that is never printed or model text (P4A:39, P4A:97, ARCH:231 AD-18). currency was added as a one-value CHECK column by owner decision (ARCH:242). total is not stored: it is derivable from the settlements (P4A:38, P4A:129).
- buyer_name is not in the spec, addendum or architecture; P4A:31 says it comes from the source, not the image.
- resolver_v1: ARCH:181 AD-12 says read-only views in a `resolver_v<major>` schema expose the feed and "the stored receipt data"; no document read lists its fields.
- Conflicts between documents: the dedup key to the second (SPEC:91) versus to the minute (ARCH:149); "no currency column" earlier versus the CHECK column later; the addendum's "drop both" for DM storno versus P4A:34 netting; SPEC:24 listing branch as a target versus P4A:124 making it nullable.
- Not found: an explicit "required" statement for store_name; a reader of store_name besides the admin message; a reason for store_address and loyalty_card_number beyond "the Resolver needs them"; any resolver_v1 column list.

## 6. How the fields are tested

From the tests locator; detail in digests/locator-tests.md.

- loyalty_card_number is touched by exactly one test, the writer round trip, with the value "**** 1234" (tests/test_receipts_writer.py:302 (test_round_trip_keeps_every_field_and_reference) @ 7c1c47c). No fixture file contains it.
- store_address is set as input in the same round trip (tests/test_receipts_writer.py:301 (test_round_trip_keeps_every_field_and_reference) @ 7c1c47c) and asserted on read-back (tests/test_receipts_writer.py:325 (test_round_trip_keeps_every_field_and_reference) @ 7c1c47c) and appears in the synthetic Spar sample (tests/spar_samples.py:44 (response) @ 7c1c47c). No test pins its format.
- receipt_number: the pipeline test asserts "100/2000/300" for a stored receipt (tests/test_pipeline.py:146 (test_happy_path_stores_the_receipt) @ 7c1c47c) and treats "100-2000-300" as an invalid input (tests/test_pipeline.py:404 (test_unreadable_response_is_invalid_and_writes_nothing) @ 7c1c47c).
- store_name: a blank value becomes None on the unsupported path (tests/test_pipeline.py:354 (test_blank_store_name_is_none) @ 7c1c47c); a stored receipt asserts it (tests/test_pipeline.py:144 (test_happy_path_stores_the_receipt) @ 7c1c47c); " " is an invalid pass-2 input (tests/test_pipeline.py:405 (test_unreadable_response_is_invalid_and_writes_nothing) @ 7c1c47c); the admin notification test passes it through (tests/test_notify.py:84-88 (test_unsupported_chain_clears_the_reaction_and_tells_both) @ 7c1c47c).
- The recorded Spar fixtures carry store_name, branch_number, receipt_number and store_address in expected.json, and the stored receipt is compared with the whole expected model (tests/test_spar_fixtures.py:107 (test_pipeline_stores_recorded_spar_samples) @ 7c1c47c).
- Not found: a test pinning the format or requiredness of loyalty_card_number, store_address or branch_number, or the min_length of store_name on the model.

## Open questions

- Which of the other 29 Lidl and 204 Kaufland samples print a store name or loyalty card number that the 4 to 5 sampled files do not? (Q4 sampled; a wider sweep would settle it.)
- What does the Resolver read? The planning documents say only "the Resolver needs them"; the next ask is a factual question to the Resolver contract the owner holds, once it exists in docs/contracts/.

## Prior documents

Research documents in the run folder tree: none before this one. Decision records (ADRs): none in the repository at 7c1c47c.
