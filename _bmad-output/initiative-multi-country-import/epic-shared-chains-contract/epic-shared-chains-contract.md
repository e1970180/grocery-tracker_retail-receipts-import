---
type: epic
title: "Shared chains contract and optional tax identifier"
parent: initiative-multi-country-import
covers: ["R1", "R2", "R3", "R4"]
after: []
assignee: ""
risk: high
---

# Shared chains contract and optional tax identifier

## Description

Updates the `chains_v1` consumer contract in-place to generalize seller identification to optional `tax_numbers`, add `country_code`, and transition ownership and DDL management of the `chains` table to `grocery-tracker/common`. Adapts the PostgreSQL chain reference adapter, pipeline seller guard, and test suite to support chains with or without tax identifiers.

## Outcome

The service reads chains from the shared reference owned by `common`, supporting chains with or without tax identifiers across different countries without breaking existing Croatian chain imports.

## Requirements

- E1 (R1): In-place contract update for `chains_v1` in `docs/contracts/chains_v1.md`, `chains_v1.sql`, and `docs/api-versions.md`, documenting `grocery-tracker/common` as the table and migration owner.
- E2 (R2): Add `country_code` text column to `chains_v1` view and reference DDL, sourced from `public` without foreign keys.
- E3 (R3): Replace mandatory 11-digit `seller_oibs` rule with optional `tax_numbers` array in `chains_v1` (nullable or empty allowed; Croatian chains keep 11-digit OIBs).
- E4 (R4): Update `adapters/postgres/chains.py` (`KnownChain` model, query, and row validation) to parse `country_code` and optional `tax_numbers`.
- E5 (R4): Update `app/pipeline.py` seller guard to enforce tax number matching only when `known_chain.tax_numbers` is non-empty.
- E6 (R4): Update fixtures, unit tests, and integration tests for chains with and without tax numbers.
- E7: Refactor sweep and code health checks.

## Done when

1. `docs/contracts/chains_v1.md` reflects the in-place updated specification, documenting `grocery-tracker/common` ownership, optional `tax_numbers`, and `country_code`.
2. The PostgreSQL adapter loads active chains with `country_code` and optional `tax_numbers`, rejecting malformed rows but allowing empty/null tax numbers.
3. The seller guard in the pipeline validates receipts against `tax_numbers` when present, and allows valid receipts without rejection when a chain has no tax numbers.
4. All existing chain tests (Spar, DM, Kaufland, Lidl, Müller) and new tests for optional-tax chains pass cleanly in `uv run pytest`.
5. Standard check suite (mypy strict, ruff, pytest) passes.

## Boundaries

- Touch point: `grocery-tracker/common` — owns `chains` DDL, migrations, and seed data.
- Touch point: `public` reference schema — provides country codes without FK constraints.

## References

- parent — _bmad-output/initiative-multi-country-import/initiative-multi-country-import.md
- contract — docs/contracts/chains_v1.md
- ddl — docs/contracts/chains_v1.sql
- versions — docs/api-versions.md

## Notes

- Decision: 2026-11-03: `chains_v1` modified in-place without bumping major view version (owner).
- Decision: 2026-11-03: OIB generalized to `tax_numbers`, country code added without foreign key constraint to `public` (owner).
