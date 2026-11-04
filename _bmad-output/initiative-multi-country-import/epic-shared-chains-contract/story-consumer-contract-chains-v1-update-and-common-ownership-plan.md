---
title: 'Consumer contract chains_v1 update and common ownership'
type: 'feature'
ticket: '1'
created: '2026-11-03'
status: done
baseline_revision: '39f305c3ef9889ccb47c02ff4ef6788b7c48215d'
route: 'oneshot'
route_source: 'auto'
risk: 'high'
review: 'thorough'
review_source: 'pinned'
lenses_ran: [blind-hunter, edge-case-hunter, verification-gap, intent-alignment]
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `chains_v1` assumes every chain has Croatian 11-digit `seller_oibs` and an admin-owned table; multi-country import needs a country and optional tax identifiers, and `grocery-tracker/common` now owns the table.

**Approach:** Update `docs/contracts/chains_v1.md`, `chains_v1.sql` and `docs/api-versions.md` in place (view name stays `chains_v1`, version 1.2.0): add `country_code`, replace `seller_oibs` with optional `tax_numbers`, and state that `common` owns the table, DDL and migrations while the SQL file stays a dev/test reference copy. Docs and SQL only; adapter, pipeline and tests are later tickets.

Decisions (owner delegated technical details): `country_code` is `NOT NULL`, matches `^[A-Z]{2}$`, no foreign key to `public`; `tax_numbers` may be NULL or an empty array, elements non-NULL and non-blank, and for `country_code = 'HR'` every element is exactly 11 digits; existing five rows get `HR`.

</frozen-after-approval>

## Implementation Notes

Oneshot: three docs/SQL files, under 100 lines. Risk raised from the ticket's medium to high because a consumer contract changes in place (project risk scale).

## Review Triage Log

- Semver/in-place break (blind, edge, intent): false/decided; owner chose in-place on 2026-11-03, recorded in Versioning.
- Code and tests still on seller_oibs (blind, verification-gap): medium, real; deferred to adapter/test tickets of this epic.
- adding-a-chain.md stale: low, deferred to sweep.
- Stale OIB wording, Kind row "owner", country_code phrasing, api-versions Role cell: low, patched.
- NULL vs empty tax_numbers, non-HR format, no-tax-number attribution: medium, patched in contract text.
- Comma inside tax number element: medium, patched in SQL (not executed).
- Invisible-character blanks, duplicate numbers across rows: maybe-false/low, not worth a constraint; duplicates deferred.
- HR chain with empty tax_numbers: false, owner decided empty allowed.
- CHECK constraints unexecuted: medium, deferred test ticket; no test DB available here.
