---
id: 23
type: story
title: "Stored procedures for receipt deletion and line printed-text updates"
parent: epic-receipts-pipeline
covers: [CAP-4, CAP-11]
after: [14]
hitl: false
risk: medium
---

# Stored procedures for receipt deletion and line printed-text updates

## Description

Adds stored procedures delete_receipt (deletes the receipt and writes a 'deleted' feed event under EXCLUSIVE lock on receipt_feed) and update_line_printed_text in retail_receipts_import, documents their usage in docs/resolver-integration.md, and adds integration tests.

## Acceptance Criteria

Verify: Calling delete_receipt removes the receipt and records 'deleted' in resolver_v1.feed; update_line_printed_text updates the printed text; both procedures reject invalid or non-existent identifiers.

## References

- parent — _bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/epic-receipts-pipeline.md
