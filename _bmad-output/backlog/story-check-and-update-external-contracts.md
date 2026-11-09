---
id: 1
type: story
title: "The project matches the latest external contracts"
parent: none
covers: []
after: []
assignee: ""
hitl: false
risk: medium
---

# The project matches the latest external contracts

## Description

The external contracts the project uses are checked against the most current versions in docs/contracts/external/, and everything in the project that depends on them is updated to match.

## Acceptance Criteria

Verify: for each external contract the project uses, the version the project relies on is the one in docs/contracts/external/, and any difference found is either fixed or reported to the owner.

## Boundaries

- Vendored contracts in docs/contracts/external/ are read-only and are not edited.

## References

- most current external contracts — docs/contracts/external/

## Notes

- Assumption: risk is medium because the update may touch several files; the owner confirms or corrects.
- Assumption: this ticket comes first because the later tickets rely on the sanitize-text and unaccent-grocery-tracker contracts; the owner confirms the order.
