# Locator digest: tests/ @ 7c1c47c

Receipt fields per src/retail_receipts_import/domain/receipt.py:147-158 @ 7c1c47c: chain_id, store_name (required, min_length=1), branch_number, receipt_number, store_address, loyalty_card_number (optional str|None), currency (Literal "EUR"), purchased_at, total, lines, settlements; source: buyer_name/kind/ref (receipt.py:235-237).

## Q3 touches

store_name
- tests/spar_samples.py:32 (pass1_response), :43 (response): "SYNTHETIC STORE".
- tests/test_pipeline.py:144 (test_happy_path_stores_the_receipt): asserts stored store_name. :275, :282, :297, :354 (test_blank_store_name_is_none): unsupported-chain cases and blank "   ". :405, :407 (test_unreadable_response_is_invalid_and_writes_nothing): store_name=" " as invalid input.
- tests/test_loop.py:408 (test_second_unsupported_in_a_row_ends_the_job_and_tells_both): "KONZUM" in an "other" pass1.
- tests/test_notify.py:84-88 (test_unsupported_chain_clears_the_reaction_and_tells_both): store_name passed into finish().
- tests/test_receipt.py:69 (_receipt), :134, :147: "SPAR".
- tests/test_receipts_writer.py:66 (_receipt); :230, :246 (test_schema_enforces_both_unique_keys, test_schema_refuses_bad_chain_ids): raw INSERT naming store_name; :298 (test_round_trip_keeps_every_field_and_reference): "Kaufland".
- tests/test_spar_fixtures.py:67 (test_pipeline_stores_recorded_spar_samples): compares with raw.store_name.
- tests/test_pass1.py:17 (test_pass1_schema_restricts_chain_to_active_and_sentinels): store_name in pass1 schema.

store_address
- tests/spar_samples.py:44 (response): "Test street 1, 10000 Zagreb".
- tests/test_receipts_writer.py:301, :315-316 (test_round_trip_keeps_every_field_and_reference): "Ilica 1, Zagreb" and SELECT readback.

loyalty_card_number
- tests/test_receipts_writer.py:302, :316 (test_round_trip_keeps_every_field_and_reference): "**** 1234" and readback. Only test touching it. No fixture file contains it.

receipt_number
- tests/spar_samples.py:45 (response): "100/2000/300".
- tests/test_pipeline.py:146 (test_happy_path_stores_the_receipt): asserts "100/2000/300". :404 (test_unreadable_response_is_invalid_and_writes_nothing): "100-2000-300" as invalid input.
- tests/test_receipts_writer.py:300, :315 (test_round_trip_keeps_every_field_and_reference): "R-0001234".

Other fields
- branch_number: tests/test_pipeline.py:145 "2000"; tests/test_receipts_writer.py:299, :315 "007".
- purchased_at: tests/test_pipeline.py:148; tests/test_receipt.py:143 (test_purchased_at_must_be_utc_to_the_minute); tests/test_dedup.py:208; tests/test_receipts_writer.py:60, :303.
- chain_id: tests/test_receipt.py:123-126 (test_chain_id_must_be_a_reference_slug); tests/test_receipts_writer.py:240-249 (test_schema_refuses_bad_chain_ids); tests/test_pipeline.py:143, :330; tests/test_loop.py:263.
- currency: tests/test_receipt.py:129-137 (test_currency_is_eur_only); tests/test_receipts_writer.py:231, :247, :316.
- total: tests/test_receipt.py:167-181; tests/test_pipeline.py:443 (test_total_not_matching_payments_is_invalid); tests/test_receipts_writer.py:105 (test_total_mismatch_writes_nothing); tests/test_loop.py:391-395.
- buyer_name: tests/test_intake.py:132 (test_buyer_name_falls_back_to_the_user_id); tests/test_receipt.py:247; tests/test_notify.py:23; tests/test_dedup.py:104.
- tests/fixtures JSON line counts for store_name|store_address|loyalty_card_number|receipt_number|branch_number: spar/0100, 1402, 2600, 7088: expected 4, pass1 1, pass2 3 each; unknown_chain/pass1 1. loyalty_card_number appears in no fixture file.

## Q6 pinned by

- tests/test_receipt.py: _receipt sets store_name (:57); pins chain_id slug, currency EUR, purchased_at UTC to the minute. No test pins store_name min_length, store_address, receipt_number, branch_number or loyalty_card_number format.
- tests/test_receipts_writer.py: test_schema_enforces_both_unique_keys, test_schema_refuses_bad_chain_ids (NOT NULL/chain checks via INSERT); test_round_trip_keeps_every_field_and_reference (round trip of store_name, branch_number, receipt_number, store_address, loyalty_card_number).
- tests/test_pipeline.py: test_happy_path_stores_the_receipt; test_blank_store_name_is_none (blank -> None); test_unreadable_response_is_invalid_and_writes_nothing (receipt_number "100-2000-300", store_name " ", missing fields, empty/non-JSON -> invalid, nothing written); test_other_chain_is_unsupported_with_store_name.
- tests/test_pass1.py: test_pass1_schema_restricts_chain_to_active_and_sentinels.
- tests/test_notify.py: test_unsupported_chain_clears_the_reaction_and_tells_both (store_name "KONZUM" or None).
- tests/test_loop.py: test_second_unsupported_in_a_row_ends_the_job_and_tells_both.
- tests/test_spar_fixtures.py: test_pipeline_stores_recorded_spar_samples (every expected.json field vs pipeline output); test_registry_keys_are_the_plugins_own_ids.

## Q2 Spar fixtures

- tests/fixtures/spar/{0100,1402,2600,7088}/{expected.json,pass1.json,pass2.json}: four recorded receipts. 0100 expected: store "SPAR SUPERMARKET ZG-BAKIĆEVA", branch 87085, receipt 56786/87085/102, address Vojina Bakića 1, purchased 2026-03-22T11:47Z.
- tests/fixtures/unknown_chain/pass1.json: pass1 for an unrecognized chain.
- tests/spar_samples.py: synthetic builders (item, discount, payment, pass1_response, response) with "SYNTHETIC STORE", "Test street 1, 10000 Zagreb", "100/2000/300", made-up OIB.

Not found: any test pinning loyalty_card_number format/requiredness beyond the writer round trip; any test pinning store_address format.
