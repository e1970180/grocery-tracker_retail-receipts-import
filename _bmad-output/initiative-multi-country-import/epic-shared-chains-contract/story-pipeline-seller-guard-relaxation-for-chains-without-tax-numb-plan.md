---
title: 'Pipeline seller guard relaxation for chains without tax numbers'
type: 'feature'
ticket: '3'
created: '2026-11-03'
status: 'built'
baseline_revision: '11349c7098dc484ac8f4fc3091151350b5a5328b'
route: 'oneshot'
route_source: 'auto'
risk: 'medium'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Pass 2 in `app/pipeline.py` (`_extract`) rejects every receipt whose printed OIB is not in `known_chain.tax_numbers`. A chain with an empty `tax_numbers` can therefore never be imported, although `chains_v1` now allows it.

**Approach:** Run the seller guard only when `known_chain.tax_numbers` is non-empty. A chain with tax numbers keeps today's behavior, including rejecting a missing or mismatched printed OIB. Add pipeline tests for both cases.

</frozen-after-approval>

## Implementation Notes

Oneshot: about 5 changed source lines in one function plus two tests. The change is local to `_extract`, and the existing guard tests (`test_wrong_seller_oib_is_invalid_without_oib_in_detail`, `test_missing_seller_oib_is_invalid`) already cover the chain-with-tax-numbers side. Plan: wrap the guard in `if known_chain.tax_numbers:`, update its comment, and add tests in `tests/test_pipeline.py` using a `KnownChain("spar", ..., "HR", ())` reference. One test uses a matching or absent printed OIB (accepted), and one uses a wrong printed OIB (also accepted, since the guard is skipped).
