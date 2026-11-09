---
id: 5
type: story
title: "Documentation and code describe the single environment on srv22"
parent: none
covers: []
after: []
assignee: ""
hitl: true
risk: high
---

# Documentation and code describe the single environment on srv22

## Description

The project documents two environments, dev and production, but the owner states that srv22 is both: there is one database (`grocery-tracker-dev`) and one live service. The split misleads agents and operators, who treat work on srv22 as harmless dev work, while it changes live data (the item key migration was applied there on 2026-11-09 under that assumption).

The documentation, the agent rules and the configuration check are brought in line with one environment. The owner decides two points before any change: the wording of the agent rule, and whether the `RRI_ENV` dev/prod switch is removed from the code or only explained.

## Acceptance Criteria

Verify: a search of the project docs, configuration and code, excluding vendored contracts in `docs/contracts/external/` and historical files in `_bmad-output/`, finds no statement that a second environment exists. The documented deployment steps match what runs on srv22. The standard check suite and CI pass.

## Boundaries

- The proposal, with the owner's two decisions, is settled before any edit.
- `docs/contracts/external/` is read-only and stays as vendored.
- Historical plans and memlogs in `_bmad-output/` are not rewritten, except the first production deployment story, which is reviewed because it may describe a second deployment that does not exist.
- The real names stay: database `grocery-tracker-dev`, roles `rri_dev_*`, `resolver_dev_reader`. Renaming them is an operation on the live database and is out of scope; the docs note that "dev" in these names is historical.
- No change to the live database or the server.

## References

- agent rules — AGENTS.md (lines on dev work, throwaway test databases, database target)
- environment switch — src/retail_receipts_import/config.py, .env.example, tests/test_config.py, tests/test_main.py, tests/conftest.py
- deployment — docs/deployment.md, docs/deploy/provision.sql, docs/deploy/after-migrate.sql, compose.yaml
- operators' guides — README.md (environment isolation section, role table, parameters), docs/resolver-integration.md, docs/adding-a-chain.md
- contracts that mention dev — docs/contracts/chains_v1.md, docs/contracts/chains_v1.sql, docs/contracts/receipt_feed_v1.md

## Notes

- Open question 1: the agent rule. Proposal: any write to the database on srv22 is a live operation and needs the owner's approval; automated tests use only a throwaway database whose name does not contain `grocery-tracker`.
- Open question 2: remove `RRI_ENV` and the `-dev` suffix check from the code (cleaner, touches configuration, tests and the startup log line), or keep it and document that only `dev` is used (cheaper, but the live database keeps a misleading label).
- Assumption: risk is high and hitl is true because an agent rule and the configuration check change; the owner confirms or corrects. A high-risk ticket also needs one check outside its own criteria; the owner names it.
