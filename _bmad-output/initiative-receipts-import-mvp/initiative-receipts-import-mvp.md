---
type: initiative
title: "Family receipts land in PostgreSQL unattended"
parent: none
after: []
assignee: ""
risk: high
sources: [brief-receipts-import/brief-receipts-import.md]
companions: [_bmad-output/initiative-receipts-import-mvp/receipt-outcomes.md, _bmad-output/initiative-receipts-import-mvp/brief-receipts-import/addendum.md]
---

# Family receipts land in PostgreSQL unattended

## Description

A family member sends a receipt photo or PDF to a private Telegram bot; the service extracts it with Gemini Flash, prices every line, checks consistency, and stores it once, atomically, in PostgreSQL on the LAN, telling the sender and the admin the outcome. It replaces the legacy n8n pipeline greenfield. The spec owns the capabilities, constraints, and non-goals.

## Outcome

The family stops typing receipts: the spec's success signal (success reaction and a stored receipt within 10 minutes while extraction is available; nothing lost or doubled across outages and restarts) holds in daily use.

## Requirements

- R1 (CAP-1): An allowlisted family member, identified by Telegram user ID, submits a receipt in a private chat as a photo or as a document (image or PDF). Success: A photo, an image document and a PDF from an allowlisted user in a private chat are each accepted. The same content from a non-allowlisted user or from a group chat is not processed.
- R2 (CAP-2): The service extracts one structured receipt from each submission: chain, branch, purchase date and time, line items, discounts and settlement. It does this for clean digital receipts and crumpled paper photos of supported chains. Success: For a fixture receipt of each supported chain, the extracted chain, branch, timestamp, items and settlement match a hand-verified expected record. Chain-specific traps from the addendum are handled correctly.
- R3 (CAP-3): Every line item keeps what was printed, plus the regular price before discount and the effective price actually paid. Success: For a shelf-promotion line and for a line with a separate discount line, the stored regular and effective amounts follow the addendum's pricing logic to the cent.
- R4 (CAP-4): Each receipt records how it was settled: card, cash, bonus points, receipt-level coupons and deposit refunds. Every settlement is a form of payment, deposit refunds included, and all settlements together equal the receipt total, which is the value of the goods (the lines' effective amounts), not the printed amount to pay. A settlement amount may be negative. Success: These fixtures are each stored with their full settlement breakdown and their total: a Müller receipt with bonus points, a receipt with a coupon, and a receipt whose deposit refund exceeds the purchase (negative payout). In each, the settlements sum to the total, the value of the goods. The stored total is readable through the Resolver contract.
- R5 (CAP-5): The service verifies that items and settlement agree before writing, to catch extraction errors. Success: The match is exact: on a real receipt the lines, the total and the settlements always agree, so any difference is an extraction error. A receipt off by 0.01 EUR is not written and takes the failure path. A receipt that matches to the cent is written.
- R6 (CAP-6): The same purchase sent more than once is stored once, and the sender is told it was already recorded. Success: Sending the same receipt twice, including as a different photo of the same paper, leaves exactly one stored receipt. The second send gets the duplicate reaction and the configured duplicate message.
- R7 (CAP-7): A receipt, its items and its settlement are stored together or not at all. Success: A failure injected mid-write leaves no partial receipt, items or settlement in the database.
- R8 (CAP-8): For every receipt, the sender and the admin learn the outcome as defined in `receipt-outcomes.md`. Success: Each row of the outcome matrix is shown by a test or demo that produces the stated reaction, message and admin notification. Failure notifications include the reason and a copy of the file.
- R9 (CAP-9): A receipt survives an extraction-service outage and a service restart, and is processed once the service returns. A receipt that keeps getting no valid result stops after a bounded number of attempts. Success: With extraction unavailable, the sender sees the in-progress reaction. After a restart and the service's return, the receipt is stored without being resent. A receipt that repeatedly gets no valid result takes the failure path after the bounded attempts.
- R10 (CAP-10): Errors the service catches in its own operation reach the admin in Telegram, not only the logs. Success: An induced internal error (for example, database unreachable) produces an admin Telegram alert.
- R11 (CAP-11): The downstream Resolver learns that a receipt was stored, through a contract this project owns. Success: The contract exists in `docs/contracts/`, is semver-versioned from its first release and is recorded in `docs/api-versions.md`. A stored receipt is observable through it. The MVP is not done without it.

## Constraints

- **Extraction.** Use Gemini Flash only. The pricing tier is the admin's operational choice, so cost depends on that tier. Receipt images leave the host, including the items, branch address and masked loyalty-card number. While the service is unavailable, retries follow its own signals, such as the wait time in a 429 response, not a fixed schedule.
- **Telegram intake.** Telegram intake is built in this project. The tested code of the Telegram reference pack in `doc-inbox/` may be copied into this project and owned here; it is never an external dependency.
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

## Done when

1. A receipt from each supported chain, sent by an allowlisted user, is stored with items and settlement and the sender sees the success reaction within 10 minutes.
2. Every row of the outcome matrix is demonstrated on the deployed service, including duplicate, unsupported chain, inconsistency, and no-valid-result.
3. With extraction unavailable and the service restarted, a waiting receipt is stored after extraction returns, without being resent, and stored once.
4. The Resolver contract is in `docs/contracts/`, recorded in `docs/api-versions.md`, and a stored receipt is observable through it.
5. The service runs on the home server from `git clone + compose build`, with an induced internal error reaching the admin in Telegram.

## Boundaries

One Python service in one repo with one owner; see the spec's non-goals. Tracer path: one allowlisted photo of one chain → Gemini → atomic write → success reaction.

- Touch point: Telegram Bot API — intake, reactions, messages; owner: epic-receipts-pipeline
- Touch point: Gemini API — extraction; owner: epic-receipts-pipeline
- Touch point: PostgreSQL on the LAN — database and roles the admin provisions; owner: epic-receipts-pipeline
- Non-goal: Raw JSON receipts as input.
- Non-goal: Categorization; the Resolver does it.
- Non-goal: Spending analytics and visualization.
- Non-goal: Multiple currencies.
- Non-goal: Migrating legacy data, or compatibility with the legacy schema or workflow.
- Non-goal: Manual-correction tooling.
- Non-goal: Measuring extraction accuracy or the 99% unattended rate.
- Non-goal: Re-extracting past receipts from stored originals.
- Non-goal: Guaranteed delivery of notifications through a long Telegram outage.

## References

- spec companion — _bmad-output/initiative-receipts-import-mvp/receipt-outcomes.md
- addendum — _bmad-output/initiative-receipts-import-mvp/brief-receipts-import/addendum.md (chain traps, pricing logic, dedup lesson, Telegram rules)
- companion — receipt-outcomes.md
- addendum — brief-receipts-import/addendum.md

## Notes

- Open question: identifier scheme, deduplication key, no-valid-result attempt limit, Resolver handoff mechanism, data model, and the durable-waiting mechanism are deferred to architecture by the spec; entries that depend on them wait.
- Decision: one epic for the whole initiative; one service, one repo, one owner, and durable waiting shapes the whole pipeline, so no split; platform baseline is its opening stories (owner, 2026-10-21).
- Decision: run bmad-architecture before epic inception to settle the deferred decisions (owner, 2026-10-21).
- Source conflict: AGENTS.md (Ruff 0.16, Python 3.14) vs pyproject.toml (`ruff==0.9.9`, ruff `target-version = "py313"`); fix in the platform baseline.
- Assumption: A receipt whose store or purchase date cannot be read is a no-valid-result case (bounded attempts, then failure). It is not an unknown-chain case.
- Assumption: The admin is one Telegram user: the owner.
- Assumption: These technical choices are deferred to architecture: the identifier scheme, the deduplication key (see the legacy lesson in the addendum), the attempt limit for no-valid-result, and the Resolver handoff mechanism.
