---
type: epic
title: "Multi-country receipt pipeline and currency handling"
parent: initiative-multi-country-import
covers: ["R5", "R6"]
after: []
assignee: ""
risk: high
---

# Multi-country receipt pipeline and currency handling

## Description

Adds country and currency detection to pass 1 and pass 2 prompts, updates receipt storage and settlement to support multiple currencies and national receipt formats, and adds integration tests for receipts from multiple countries.

## Outcome

The pipeline accepts and accurately processes receipts originating from multiple countries in their local currencies, verified end-to-end.

## Requirements

- E1 (R5): Pass 1 detection extended with country and currency extraction.
- E2 (R5): Plug-in protocol and prompt templates support country-specific formats and tax identifiers.
- E3 (R6): Receipt model, PostgreSQL storage, and resolver feed support multiple currencies and country metadata.
- E4 (R6): End-to-end fixtures and integration tests for multi-country receipts.
- E5: Refactor sweep and documentation.

## Done when

1. Pass 1 detects chain, country, and currency for receipts from supported countries.
2. The receipt storage model and resolver feed reflect currency and country accurately.
3. End-to-end test suite processes receipts from supported non-Croatian retailers with full verification.
4. Standard check suite passes.

## Boundaries

- Touch point: Telegram Bot API — intake of receipts in any supported currency.
- Touch point: Gemini API — extraction with multi-country prompts.

## References

- parent — _bmad-output/initiative-multi-country-import/initiative-multi-country-import.md
- spec — docs/contracts/resolver_v1.md

## Notes

- Waits on epic-shared-chains-contract because: multi-country receipts rely on the country-aware chain reference with optional tax numbers.
