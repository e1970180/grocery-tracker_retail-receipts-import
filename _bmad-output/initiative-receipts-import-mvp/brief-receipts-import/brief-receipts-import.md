---
title: "Product Brief: retail-receipts-import"
status: final
created: 2026-10-21
updated: 2026-10-21
---

# Product Brief: retail-receipts-import

## Executive Summary

A family shopping at grocery chains in Croatia wants every purchase recorded as clean, structured data in its own PostgreSQL database on the home LAN. A family member sends a photo or PDF of a receipt to a private Telegram bot. The service reads the receipt with a vision model, works out what each item really cost after discounts, and stores the receipt once and only once. The sender gets a reaction that says whether it worked.

A working pipeline already exists on n8n. This project replaces it with a self-contained Python service and starts from a clean slate. It does not migrate legacy data or keep compatibility with the legacy schema. A new downstream Resolver, also not yet written, will consume the stored receipts for categorization.

## The Problem

Croatian chains price in layers. A single receipt can mix shelf promotions already in the line price, loyalty-card discounts printed as separate lines, whole-receipt coupons, deposit charges and refunds for bottles, and payment with bonus points. Each chain prints these differently. Typing receipts in by hand is tedious. A naive OCR result gets the totals wrong in ways that are hard to notice later.

The legacy pipeline solved much of this, but it is tied to the n8n platform. The owner wants a fresh service without that dependency, built on a strong model, with a data model designed for clarity rather than inherited.

## The Solution

- **Intake.** A Telegram bot accepts receipts in private chats from an allowlist of family members, identified by Telegram user ID. A receipt arrives as a photo or as a document (image or PDF file). Anything else is ignored or rejected with a reaction.
- **Extraction.** A strong vision model reads the receipt. One extraction, guided by chain-specific prompts, yields store detection, line items, discounts, branch, purchase date and time, and how the bill was settled. Both clean digital receipts and crumpled paper photos are valid input.
- **Pricing.** For every line the service keeps what was printed and computes the regular price before discount and the effective price actually paid.
- **Settlement.** The receipt records how it was settled: card, cash, bonus points, receipt-level coupons, deposit refunds. A settlement amount can be negative when deposit refunds exceed the purchase and the cashier pays money back.
- **Deduplication.** The same purchase sent twice is stored once. On a duplicate, the sender sees a dedicated reaction and the message "Данный чек уже внесен в систему" (this receipt is already in the system).
- **Storage.** Each receipt is written to PostgreSQL over the LAN atomically, together with its items and settlement.
- **Feedback.** On success the sender sees a success reaction. On failure the sender sees a failure reaction and a message that explains the problem, and the admin gets a Telegram notification with a copy of the file. Recovery means resending a better photo or file; there is no manual-correction tool.
- **Consistency.** The service checks that items and settlement agree, to catch extraction errors. A receipt that fails the check is not written and takes the failure path. The exact tolerance is decided in the PRD.
- **Unknown chain.** A receipt from a chain not on the supported list is not written. The sender and the admin each get a Telegram message.
- **Extraction-service outages.** If the extraction service is unavailable, the sender sees an "in progress" reaction. Retries follow the service's own signals, such as the wait time in a 429 response. The receipt is never lost: it waits with no deadline, survives a restart of the service, and is processed once the service is back. If the service responds but gives no valid result, for any reason, including a receipt whose store or purchase date cannot be read, the receipt gets a limited number of attempts and then takes the failure path.
- **Operational alerts.** Errors the service catches in its own work are sent to the admin in Telegram, not only to logs.

## Who This Serves

- **Family members** (a handful of people) who photograph receipts and forget about them. Success means sending a receipt and seeing a success reaction.
- **The admin** (the owner), who runs the service, sees every failure along with the file, and owns the database.
- **The downstream Resolver** (a new project), which reads stored receipts for categorization.

## Success Criteria

- 99% of receipts are stored without anyone intervening. This is a target; building a way to measure it is out of scope.
- While the extraction service is available, a receipt reaches the database within 10 minutes of sending. Speed is not critical.
- No accepted receipt is lost, even through an extraction-service outage or a restart.
- No purchase is stored twice.
- Every failure reaches both the sender and the admin, with a reason.

## Scope

**In (MVP):**
- Telegram intake from allowlisted users: receipts sent as a photo or as a document (image or PDF file).
- Extraction through Gemini Flash on a paid tier.
- Chains seen so far: Kaufland, Lidl, DM, Müller, Spar.
- EUR only.
- Line-level discounts, receipt-level discounts, deposits, bonus points.
- Settlement amounts that may be negative.
- Deduplication.
- An atomic write to PostgreSQL.
- Reactions, failure explanations, admin notifications, Telegram alerts to the admin about service errors.
- Durable waiting and retry while the extraction service is unavailable.

**Out:**
- Raw JSON receipts as input.
- Categorization (the new Resolver handles it).
- Spending analytics and visualization.
- Multiple currencies.
- Migrating legacy data, or compatibility with the legacy schema or workflow.
- Manual-correction tooling.
- Measuring extraction accuracy.

## Constraints and Decisions

- **External service: Gemini Flash, paid tier.** The paid tier keeps receipt data out of model training.
  - Data leaving the host: receipt images, which include the purchased items, branch address, and masked loyalty-card number.
  - Cost: cents per month at about 2 receipts a day.
  - When Gemini is down or gives no valid result: see "Extraction-service outages" under The Solution.
- **Intake lives in this project.** The Telegram reference pack in `doc-inbox/` serves as requirements only, never as imported code.
- **User-facing texts.** All messages sent to users and the admin live in a file outside the code, so they can be edited without touching code.
- **Data model.** Designed fresh, with self-explanatory names. The legacy schema is a reference for meaning only.
- **Identifiers and the deduplication key.** Decided in architecture.
- **Scale.** About 2 receipts a day. Nothing beyond that scale is built.

## Open Questions

- **Handoff to the Resolver.** How does the new Resolver learn that a receipt was stored? This must be settled during the project, as a contract versioned from day one. The MVP is not done without it.

## Vision

The family's receipts become a reliable, queryable record of what they buy and what they really pay, the foundation for categorization and spending insight built by downstream projects.
