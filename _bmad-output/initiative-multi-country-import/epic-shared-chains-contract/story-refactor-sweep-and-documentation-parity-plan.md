---
title: 'Refactor sweep and documentation parity'
type: 'chore'
ticket: '1.5'
created: '2026-11-04'
status: 'built'
baseline_revision: 'da443fb'
route: 'oneshot'
route_source: 'auto'
risk: 'low'
review: 'none'
review_source: 'pinned'
lenses_ran: []
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `docs/adding-a-chain.md` still describes the seller OIB check as unconditional, but the pipeline now enforces it only when the chain has `tax_numbers`.

**Approach:** Align the three stale spots in the guide (flow diagram, fixture test list, pre-submission checklist) with the code; confirm the standard check suite passes.

</frozen-after-approval>

## Implementation Notes

Oneshot: docs-only edit of a few lines. Check suite (ruff, format, mypy strict, pytest: 643 passed) was green before the edit; code needs no cleanup.

## Plan Change Log

## Review Triage Log
