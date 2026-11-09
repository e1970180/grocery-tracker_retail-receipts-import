---
id: 2
type: story
title: "The outgoing contract has a descriptive name"
parent: none
covers: []
after: []
assignee: ""
hitl: true
risk: low
---

# The outgoing contract has a descriptive name

## Description

The contract this project publishes to external consumers gets a descriptive name. The agent proposes the name and the owner approves it before anything is renamed.

## Acceptance Criteria

Verify: the owner has approved a proposed name, and the contract carries that name.

## References

- contracts — docs/contracts/ (vendored ones are in docs/contracts/external/)

## Notes

- Open question: whether the outgoing contract is docs/contracts/resolver_v1.md (its header says this project is the provider); to be confirmed with the owner.
- Open question: whether the rename also covers the contract's version identifier and the places that refer to it; to be settled with the owner together with the name.
- Assumption: hitl is true because the owner approves the proposed name.
