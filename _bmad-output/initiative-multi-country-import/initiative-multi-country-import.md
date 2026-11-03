---
type: initiative
title: "Multi-country receipt import and shared chain reference"
parent: none
covers: ["R1", "R2", "R3", "R4", "R5", "R6"]
after: []
assignee: ""
risk: high
---

# Multi-country receipt import and shared chain reference

## Description

Expands the receipt import pipeline beyond Croatia to handle retail receipts from multiple countries, currencies, and tax identification formats, and transitions ownership and management of the retail chain reference table to the shared `grocery-tracker/common` project with in-place relaxation of tax identifier constraints.

## Outcome

Family members can submit receipts from different countries and currencies to the Telegram bot, which are recognized and stored accurately in PostgreSQL, while the chain reference table is maintained centrally by `common` with optional tax numbers and country codes.

## Requirements

- R1: Transition chain reference table ownership and DDL management to `grocery-tracker/common` as provider; update `chains_v1` consumer contract in-place.
- R2: Add country code (`country_code`) to chains without foreign keys, referencing valid values from `public` without constraints.
- R3: Generalize seller identification in `chains_v1` from mandatory 11-digit OIB to optional tax numbers (`tax_numbers`), making tax numbers nullable/optional for chains outside Croatia or without strict tax IDs.
- R4: Adapt receipt import pipeline and seller guard to check tax numbers only when configured for a chain, without failing receipts when tax numbers are absent.
- R5: Support country and currency detection during receipt intake and Gemini extraction (pass 1 and pass 2).
- R6: Support multi-currency storage, receipt totals, and integration testing across different national receipt formats.

## Done when

1. The `chains_v1` contract in `docs/contracts/` is updated in-place with optional `tax_numbers` and `country_code`, documented as owned by `grocery-tracker/common`.
2. The service reads `public.chains_v1` with optional tax numbers; a chain with no tax numbers processes valid receipts without being rejected by the seller guard.
3. Receipts from at least one non-Croatian country (with non-EUR currency or non-OIB tax ID) are processed end-to-end, stored in PostgreSQL, and verified.
4. Full check suite (mypy strict, ruff, pytest, pytest integration) passes against the updated schema.

## Boundaries

- Touch point: `grocery-tracker/common` — owns the shared `chains` table migration and reference data; consumed read-only via `chains_v1` contract; owner: epic-shared-chains-contract
- Touch point: `public` schema reference — provides country codes read-only without foreign key constraints; owner: epic-shared-chains-contract

## References

- contract — docs/contracts/chains_v1.md
- ddl — docs/contracts/chains_v1.sql
- versions — docs/api-versions.md

## Notes

- Decision: 2026-11-03: Generalize seller OIB into `tax_numbers`, country code taken from table in `public` without foreign key/relation (owner).
- Decision: 2026-11-03: Update `chains_v1` contract in-place without bumping major view version (owner).
- Decision: 2026-11-03: Create new initiative `initiative-multi-country-import` split into shared chains contract and multi-country pipeline epics (owner).
