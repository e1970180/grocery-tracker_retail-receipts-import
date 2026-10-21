---
id: SPEC-receipts-import
companions:
  - receipt-outcomes.md
  - ../brief-receipts-import/addendum.md
sources:
  - ../brief-receipts-import/brief-receipts-import.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Receipts Import MVP

## Why

A family shopping at Croatian grocery chains wants every purchase recorded as clean, structured data in its own PostgreSQL database on the home LAN. Croatian chains price in layers: shelf promotions, loyalty-card discount lines, receipt-level coupons, bottle deposits and refunds, bonus-point payments. Each chain prints these differently. Manual entry is tedious, and naive OCR gets totals wrong in ways that surface late. A working legacy pipeline exists on n8n. This project replaces it with a self-contained Python service that removes the platform dependency. The service starts greenfield, with a data model designed for clarity, and feeds a new downstream Resolver that categorizes receipts.

## Capabilities

- **CAP-1**
  - **intent:** An allowlisted family member, identified by Telegram user ID, submits a receipt in a private chat as a photo or as a document (image or PDF).
  - **success:** A photo, an image document and a PDF from an allowlisted user in a private chat are each accepted. The same content from a non-allowlisted user or from a group chat is not processed.
- **CAP-2**
  - **intent:** The service extracts one structured receipt from each submission: chain, branch, purchase date and time, line items, discounts and settlement. It does this for clean digital receipts and crumpled paper photos of supported chains.
  - **success:** For a fixture receipt of each supported chain, the extracted chain, branch, timestamp, items and settlement match a hand-verified expected record. Chain-specific traps from the addendum are handled correctly.
- **CAP-3**
  - **intent:** Every line item keeps what was printed, plus the regular price before discount and the effective price actually paid.
  - **success:** For a shelf-promotion line and for a line with a separate discount line, the stored regular and effective amounts follow the addendum's pricing logic to the cent.
- **CAP-4**
  - **intent:** Each receipt records how it was settled: card, cash, bonus points, receipt-level coupons and deposit refunds. A settlement amount may be negative.
  - **success:** These fixtures are each stored with their full settlement breakdown: a Müller receipt with bonus points, a receipt with a coupon, and a receipt whose deposit refund exceeds the purchase (negative payout).
- **CAP-5**
  - **intent:** The service verifies that items and settlement agree before writing, to catch extraction errors.
  - **success:** The tolerance is ±0.01 EUR. A receipt off by 0.02 EUR is not written and takes the failure path. A receipt off by 0.01 EUR is written.
- **CAP-6**
  - **intent:** The same purchase sent more than once is stored once, and the sender is told it was already recorded.
  - **success:** Sending the same receipt twice, including as a different photo of the same paper, leaves exactly one stored receipt. The second send gets the duplicate reaction and the configured duplicate message.
- **CAP-7**
  - **intent:** A receipt, its items and its settlement are stored together or not at all.
  - **success:** A failure injected mid-write leaves no partial receipt, items or settlement in the database.
- **CAP-8**
  - **intent:** For every receipt, the sender and the admin learn the outcome as defined in `receipt-outcomes.md`.
  - **success:** Each row of the outcome matrix is shown by a test or demo that produces the stated reaction, message and admin notification. Failure notifications include the reason and a copy of the file.
- **CAP-9**
  - **intent:** A receipt survives an extraction-service outage and a service restart, and is processed once the service returns. A receipt that keeps getting no valid result stops after a bounded number of attempts.
  - **success:** With extraction unavailable, the sender sees the in-progress reaction. After a restart and the service's return, the receipt is stored without being resent. A receipt that repeatedly gets no valid result takes the failure path after the bounded attempts.
- **CAP-10**
  - **intent:** Errors the service catches in its own operation reach the admin in Telegram, not only the logs.
  - **success:** An induced internal error (for example, database unreachable) produces an admin Telegram alert.
- **CAP-11**
  - **intent:** The downstream Resolver learns that a receipt was stored, through a contract this project owns.
  - **success:** The contract exists in `docs/contracts/`, is semver-versioned from its first release and is recorded in `docs/api-versions.md`. A stored receipt is observable through it. The MVP is not done without it.

## Constraints

- **Extraction.** Use Gemini Flash only. The pricing tier is the admin's operational choice, so cost depends on that tier. Receipt images leave the host, including the items, branch address and masked loyalty-card number. While the service is unavailable, retries follow its own signals, such as the wait time in a 429 response, not a fixed schedule.
- **Telegram intake.** Telegram intake is built in this project. The Telegram reference pack in `doc-inbox/` is requirements only, never imported code.
- **Telegram as an external service.**
  - Data and cost: receipt files are already in Telegram, because the family sends them there. The service adds only reply texts and the admin's file copy. Cost is zero.
  - Telegram outage: intake pauses, and Telegram holds unfetched updates for about 24 h.
  - Outgoing reactions, messages and alerts follow Telegram's retry rules (the 429 `retry_after`, at most 5 attempts). After that they are only logged.
  - A failed notification never blocks or rolls back a database write. There is no durable notification queue.
- **Local receipt file.** The service keeps a local copy of a receipt file only until the receipt reaches a final outcome: stored, duplicate, or failed after the admin copy is sent. The original stays in Telegram.
- **Supported chains.** Kaufland, Lidl, DM, Müller and Spar. A receipt from any other chain is not written.
- **Scope of the deployment.** EUR only. PostgreSQL over the LAN. Scale is about 2 receipts a day, and nothing is built beyond that scale.
- **User-facing texts.** All texts shown to users and the admin live in a file outside the code.
- **Data model.** The data model is designed fresh, with self-explanatory names. The legacy schema is a reference for meaning only. There is no legacy migration and no compatibility.
- **Recovery.** Recovery from any failure is resending a better photo or file. There is no manual-correction path.

## Non-goals

- Raw JSON receipts as input.
- Categorization; the Resolver does it.
- Spending analytics and visualization.
- Multiple currencies.
- Migrating legacy data, or compatibility with the legacy schema or workflow.
- Manual-correction tooling.
- Measuring extraction accuracy or the 99% unattended rate.
- Re-extracting past receipts from stored originals.
- Guaranteed delivery of notifications through a long Telegram outage.

## Success signal

- While the extraction service is available, a family member sends a receipt and sees the success reaction, and the receipt is in PostgreSQL within 10 minutes. 99% of receipts get there unattended; this is a target and is not measured.
- Across extraction outages and restarts, no accepted receipt is lost and no purchase is stored twice. Every failure reaches both the sender and the admin, with a reason, unless Telegram stays down past its retry rules.

## Assumptions

- A receipt whose store or purchase date cannot be read is a no-valid-result case (bounded attempts, then failure). It is not an unknown-chain case.
- The admin is one Telegram user: the owner.
- These technical choices are deferred to architecture: the identifier scheme, the deduplication key (see the legacy lesson in the addendum), the attempt limit for no-valid-result, and the Resolver handoff mechanism.
