---
id: 16
type: story
title: "First production deployment and acceptance demo"
parent: epic-receipts-pipeline
covers: [CAP-1, CAP-2, CAP-6, CAP-8, CAP-9, CAP-10, CAP-11]
after: [15]
hitl: true
risk: high
---

# First production deployment and acceptance demo

## Description

Makes the first production deployment: the owner creates the production database and roles, the admin creates the chains_v1 reference table, view and five rows and the Resolver login role in production, the service is deployed to the home server by sparse-checkout git clone + compose build, and migrate runs against production; then demonstrates on the shared bot against production every outcome-matrix row, a receipt of each chain, a restart during an extraction outage, a PostgreSQL outage alert, and a stored receipt read through resolver_v1.

Additional deliverables:
- Format and comment `.env` files; create/update `.env.example` with comprehensive variable documentation and safe defaults.
- Audit codebase documentation: verify docstrings and comments across `src/` to ensure they explain rationale in plain English without restating specs.
- Write a comprehensive, detailed README in Russian covering system purpose, architecture, configuration, deployment runbook, database roles, and operations.

## Acceptance Criteria

1. **Production Deployment & Acceptance Demo**
   - On the home server, git clone + compose build succeeds and migrate applies every migration to production; the owner observes each listed case on production and signs off against the epic's Done when.

2. **Environment Configuration & .env.example**
   - `.env` files are formatted and documented with clear comments explaining each configuration variable, constraints, and defaults.
   - `.env.example` is complete, up to date with all supported `RRI_*` variables, and contains no real credentials or secrets.

3. **Codebase Documentation Audit**
   - Code documentation across `src/` is audited: all public modules, classes, and functions have clear English docstrings explaining why; standard check suite (mypy, ruff) passes.

4. **Detailed Russian README**
   - A comprehensive README in Russian is written, detailing project architecture, configuration parameters, database security and role models, deployment and migration instructions, and troubleshooting.

## References

- parent — _bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/epic-receipts-pipeline.md
- deployment runbook — docs/deployment.md
- configuration guide — README.md
