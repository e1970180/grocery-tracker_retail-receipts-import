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
- Decision: breakdown of 16 entries approved, above the typical 8–12 range because one owner builds one service and the initiative keeps one epic (owner, 2026-10-21).
- Decision: entry 4 is the tracer bullet (a Spar receipt from Telegram to PostgreSQL with the success reaction). It follows the platform baseline (entries 1–2), as Boundaries require, and the chain reference contract (entry 3), which the spine's Deferred section puts before the first plug-in (owner, 2026-10-21).
- Decision: the tracer builds the full NormalizedReceipt and receipt schema for every discount and settlement kind in the addendum, so chain plug-ins add no migration and resolver_v1 1.0.0 is not frozen before their fields exist (owner, 2026-10-21).
- Decision: sequencing after the tracer runs in three lanes: 5 → 6 → 7 → 12 → 13 (jobs, notify, Gemini and PostgreSQL adapters); 8 → 9 → 10 → 11 (chain plug-ins, chained because they share the registry); 14 (Resolver contract). The refactor sweep (15) and the production acceptance demo (16) close the epic (owner, 2026-10-21).
- Decision: sample receipts for all five chains are in `doc-inbox/fixtures/` (non-normative, git-ignored, personal data): Spar and DM as PDF e-receipts only, Kaufland as PDFs, Lidl as PNG images, Müller as JPEG/PNG photos (owner, 2026-10-21).
- Assumption: Spar stays the tracer chain, proven with a Spar PDF; the photo path is first proven on Lidl or Müller. The folder mixes Spar and Interspar, so the chain reference needs Interspar as a printed alias of `spar`.
- Observation: the `.gemini.json` and `.gemma4.json` files beside the samples are earlier model outputs, not hand-verified records. Examples: the Spar sample `…091826431051` lists a deposit as a payment, and the DM sample of 17:30:54 has its seconds dropped, which would break the dedup key. Each chain story derives its expected record from the receipt itself, and the owner confirms it.
- Decision: the Telegram half of the tracer (intake, queue, job states, loop, success reaction, dev-bot verify) is split off from entry 4 and waits in `deferred-work.md` for its own entry (owner, 2026-10-22).
- Dropped: entry 4 "Tracer: a Spar receipt end to end", split into 4a "Receipt model and storage" and 4b "Spar receipt from PDF to dev", 4a before 4b (owner, 2026-10-22).
- Decision: lanes after the split, superseding the 2026-10-21 lane line: A = 4b → 17 → 5 → 6 → 7 → 12 → 13; B = 4b → 8 → 9 → 10 → 11; C = 4a → 14 (owner, 2026-10-22).
- Decision: entry 17 "Telegram receipt to dev end to end" is the tracer bullet, superseding the 2026-10-21 decision naming entry 4; it takes the Telegram half from `deferred-work.md` and the dev-bot verify (owner, 2026-10-22).
- Decision: no production until the whole project is developed; entry 16 owns the first production deployment, with the production database and roles, the production chains_v1 rows and the Resolver login role; one bot serves dev and production, as story 2 recorded (owner, 2026-10-22).
- Decision: the dedup key is the purchase timestamp to the minute for every chain; AD-8 amended (owner, 2026-10-22).
- Decision: own-write recognition (AD-9) moves from entry 7 to 4a, because a rerun of its own write violates both unique keys at once; entry 7 is now "Deduplication pre-check" (owner, 2026-10-22).
