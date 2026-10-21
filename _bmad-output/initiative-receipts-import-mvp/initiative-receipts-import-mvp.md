---
type: initiative
title: "Family receipts land in PostgreSQL unattended"
parent: none
covers: [CAP-1, CAP-2, CAP-3, CAP-4, CAP-5, CAP-6, CAP-7, CAP-8, CAP-9, CAP-10, CAP-11]
after: []
assignee: ""
risk: high
---

# Family receipts land in PostgreSQL unattended

## Description

A family member sends a receipt photo or PDF to a private Telegram bot; the service extracts it with Gemini Flash, prices every line, checks consistency, and stores it once, atomically, in PostgreSQL on the LAN, telling the sender and the admin the outcome. It replaces the legacy n8n pipeline greenfield. The spec owns the capabilities, constraints, and non-goals.

## Outcome

The family stops typing receipts: the spec's success signal (success reaction and a stored receipt within 10 minutes while extraction is available; nothing lost or doubled across outages and restarts) holds in daily use.

## Done when

1. A receipt from each supported chain, sent by an allowlisted user, is stored with items and settlement and the sender sees the success reaction within 10 minutes.
2. Every row of the outcome matrix is demonstrated on the deployed service, including duplicate, unsupported chain, inconsistency, and no-valid-result.
3. With extraction unavailable and the service restarted, a waiting receipt is stored after extraction returns, without being resent, and stored once.
4. The Resolver contract is in `docs/contracts/`, recorded in `docs/api-versions.md`, and a stored receipt is observable through it.
5. The service runs on the home server from `git clone + compose build`, with an induced internal error reaching the admin in Telegram.

## Boundaries

One Python service in one repo with one owner; see the spec's non-goals. Tracer path: one allowlisted photo of one chain → Gemini → atomic write → success reaction.

- Touch point: Telegram Bot API — intake, reactions, messages; owner: epic-receipts-pipeline
- Touch point: Gemini API — extraction; owner: epic-receipts-pipeline
- Touch point: PostgreSQL on the LAN — database and roles the admin provisions; owner: epic-receipts-pipeline

## References

- spec — _bmad-output/initiative-receipts-import-mvp/spec-receipts-import/spec-receipts-import.md, sections Capabilities and Constraints
- spec companion — _bmad-output/initiative-receipts-import-mvp/spec-receipts-import/receipt-outcomes.md
- addendum — _bmad-output/initiative-receipts-import-mvp/brief-receipts-import/addendum.md (chain traps, pricing logic, dedup lesson, Telegram rules)

## Notes

- Open question: identifier scheme, deduplication key, no-valid-result attempt limit, Resolver handoff mechanism, data model, and the durable-waiting mechanism are deferred to architecture by the spec; entries that depend on them wait.
- Decision: one epic for the whole initiative; one service, one repo, one owner, and durable waiting shapes the whole pipeline, so no split; platform baseline is its opening stories (owner, 2026-10-21).
- Decision: run bmad-architecture before epic inception to settle the deferred decisions (owner, 2026-10-21).
- Source conflict: AGENTS.md (Ruff 0.16, Python 3.14) vs pyproject.toml (`ruff==0.9.9`, ruff `target-version = "py313"`); fix in the platform baseline.
