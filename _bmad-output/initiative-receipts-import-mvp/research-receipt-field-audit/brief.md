---
type: codebase
repository_commit: 7c1c47c08b67c806e1be785d96941b1fcee64de9
short_commit: 7c1c47c
branch: main
file_budget: 15
history_budget: 10
validation: normal
---

# Brief

Commit: `7c1c47c08b67c806e1be785d96941b1fcee64de9` (short `7c1c47c`), branch `main`.
File budget per analyzer: 15. History budget per historian: 10 commits.
Validation: normal.

Paths left out of every search (relative to the repository root): `_bmad-output/`, `_bmad/`, `.claude/`, `.agents/`, `.agent/`, `doc-inbox/`, `skills-lock.json`.
Two named exceptions, granted only to the question that lists them: Q4 (fixtures) and Q5 (planning documents).

## Questions

1. (how) Which fields do `NormalizedReceipt` and its nested types define in `src/retail_receipts_import/domain/receipt.py`, and which columns do the tables in `migrations/0002_receipts.sql` define? For each field and column: its type, whether it may be absent or empty, and every check that rejects or alters a value.
2. (how) How does the Spar chain fill each receipt field: the response schema sent to Gemini, the prompt, the normalizer, and the recorded fixtures under `tests/fixtures/spar/` (pass1, pass2, expected)? For each field: which source value feeds it, what happens when that value is missing, and what the fixtures actually contain for it.
3. (what touches) Which code reads or writes `store_name`, `store_address`, `loyalty_card_number`, `receipt_number`, and each other receipt field (writer, notification text, deduplication, jobs, pipeline, chain reader and `docs/contracts/chains_v1.*`)? List each touch point with how it uses the field.
4. (where) What is printed on the sample receipts of each chain (Lidl, Muller, Kaufland, DM, Spar) for: store name, store address, receipt/document number, loyalty card number, cashier/terminal, date and time, payment line? Report per chain, from 3 to 5 sampled files each, the printed label and an example shape, redacting any card number to its last 4 characters. Granted for this question only: the untracked working-tree folder `doc-inbox/fixtures/` (subfolders `Lidl/`, `Muller receipts/`, `Kaufland receipts/`, `DM receipts/`, `Spar + Interspar receipts/`); Lidl and Muller are images, read them visually; the rest are PDFs, extract text. These are working-tree files, not part of the commit.
5. (why) Where did each receipt field come from: the specification, its addendum, the architecture decision AD-17, the plan for the receipt model and storage (4a), and the owner decisions recorded in memlogs? For each field: the document and section that introduced it, and any recorded reason for it being required or optional. Granted for this question only: the documents under `_bmad-output/initiative-receipts-import-mvp/` named `spec-receipts-import/spec-receipts-import.md`, `spec-receipts-import/receipt-outcomes.md`, `brief-receipts-import/addendum.md`, `architecture-receipts-import/architecture-receipts-import.md`, `epic-receipts-pipeline/story-receipt-model-and-storage-plan.md`, and the `.memlog.md` files under `spec-receipts-import/`, `brief-receipts-import/`, `architecture-receipts-import/`. These are documents that state intent; report what they say with file and section/line, never as evidence of what the code does.
6. (how is it tested) Which tests pin each receipt field's presence, format or requiredness (`tests/test_receipt.py`, `tests/test_receipts_writer.py`, `tests/test_pipeline.py`, `tests/test_notify.py`, `tests/test_spar_fixtures.py`, others)? For each field: the test, what it asserts.
