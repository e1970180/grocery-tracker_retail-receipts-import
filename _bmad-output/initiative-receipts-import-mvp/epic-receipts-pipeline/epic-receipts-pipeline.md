---
type: epic
title: "Receipts pipeline from Telegram to PostgreSQL"
parent: initiative-receipts-import-mvp
covers: [CAP-1, CAP-2, CAP-3, CAP-4, CAP-5, CAP-6, CAP-7, CAP-8, CAP-9, CAP-10, CAP-11]
after: []
assignee: ""
risk: high
---

# Receipts pipeline from Telegram to PostgreSQL

## Description

The whole service: Telegram intake, Gemini extraction, pricing, consistency, deduplication, atomic storage, outcome feedback, durable waiting, operational alerts, and the Resolver contract, deployed on the home server. The spec is the requirement source; its CAP ids are cited directly.

## Outcome

Family members send receipts and see the success reaction while the spec's success signal holds in daily use.

## Requirements

The spec's capabilities CAP-1 through CAP-11 and its companion `receipt-outcomes.md`; no epic-local ids.

## Done when

1. A fixture receipt of each supported chain is extracted and stored with items, regular and effective prices, and settlement matching the hand-verified record.
2. Every row of the outcome matrix is demonstrated on the deployed service with the stated reaction, message, and admin notification.
3. With extraction unavailable across a service restart, a waiting receipt is stored once after extraction returns, without being resent.
4. The Resolver contract is published in `docs/contracts/`, recorded in `docs/api-versions.md`, and a stored receipt is observable through it.
5. The service is deployed from `git clone + compose build`; an induced database outage produces an admin Telegram alert, and the standard check suite passes in CI.

## Boundaries

The whole initiative in one service; see the spec's non-goals. The platform baseline (compose, CI, config validation, texts file) is its opening stories.

## References

- parent — _bmad-output/initiative-receipts-import-mvp/initiative-receipts-import-mvp.md
- spec — _bmad-output/initiative-receipts-import-mvp/spec-receipts-import/spec-receipts-import.md, sections Capabilities and Constraints
- spec companion — _bmad-output/initiative-receipts-import-mvp/spec-receipts-import/receipt-outcomes.md
- addendum — _bmad-output/initiative-receipts-import-mvp/brief-receipts-import/addendum.md

## Notes

- Open question: identifier scheme, deduplication key, no-valid-result attempt limit, Resolver handoff mechanism, data model, durable-waiting mechanism; inception waits on the architecture document.
- Decision: inception after bmad-architecture (owner, 2026-10-21).
