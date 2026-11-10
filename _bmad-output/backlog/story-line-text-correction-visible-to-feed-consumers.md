---
id: 4
type: story
title: "A correction of a line's printed text is visible to feed consumers"
parent: none
covers: []
after: [3]
assignee: ""
hitl: true
risk: high
---

# A correction of a line's printed text is visible to feed consumers

## Description

The stored procedures that correct a line's printed text change the line's item key, but the feed records no event for it. Consumers that track the feed with a cursor (the Resolver, canonical-products) cannot see that a line's text or item key changed, so their links to that line go stale.

The owner decides how the change is announced: a new event type, or a deleted and stored pair for the receipt. The choice is a contract change.

## Acceptance Criteria

Verify: after a printed-text correction, a consumer reading the feed from its previous cursor sees an event for the affected receipt and, reading the receipt's lines, gets the new text and item key.

## Boundaries

- The proposal goes to the owner with reasoning and the alternatives considered before any code is written.
- A change to the feed event types is a contract change: the feed contract version is raised and the change is announced to consumers.
- Receipts that are not corrected produce no new events.

## References

- outgoing contract — docs/contracts/receipt_feed_v1.md
- correction procedures — migrations/0006_admin_procedures.sql
- item key — _bmad-output/backlog/story-receipt-lines-deterministic-product-uuid.md

## Notes

- Open question: new event type, or a deleted then stored pair for the receipt. A new type breaks consumers that reject unknown events; the pair needs no new type but replays the whole receipt.
- Decision: 2026-11-10, owner: announce as new feed event `corrected` in `resolver_v1`; no consumers exist, so no backward compatibility, no `resolver_v2`, contract stays 1.2.0 (change recorded in Changes and reading rules).
- Done: 2026-11-10, migration 0008 applied to grocery-tracker-dev; one line corrected and restored (feed seq 55 and 56, both `corrected`), `resolver_v1.receipt_lines` showed the new text and `item_key`, then the original ones.
- Assumption: risk is high and hitl is true because the feed contract changes; the owner confirms or corrects. A high-risk ticket also needs one check outside its own criteria; the owner names it.
