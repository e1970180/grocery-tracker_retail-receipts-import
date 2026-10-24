---
title: 'First production deployment and acceptance demo'
type: 'chore'
ticket: '16'
created: '2026-10-24'
status: 'in-progress'
baseline_revision: 'b295de207540daa3db89e644f97bc77c7e85bf8a'
route: 'full'
route_source: 'auto'
risk: 'high'
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The service has never run from `git clone + compose build` on the home server, its database roles can do more than the service needs, and it has never processed a large batch of real receipts.

**Approach:** Start trial operation against the dev database instead of production. Narrow the three dev roles to exactly what the service needs, and write the provisioning and sparse-checkout deployment down in the repo. Then deploy on the home server with `RRI_ENV=dev`, and load 50 sample receipts through the real pipeline and Gemini, reporting the outcome of each.

**Decisions (owner, 2026-10-24):**
- Trial operation runs on the dev database `grocery-tracker-dev`; production provisioning and the production acceptance demo wait. The deployment path is the production one: home server, sparse `git clone`, `compose build`, `RRI_ENV=dev`. Pushing `main` to GitHub is approved for it.
- Load 50 receipts from `doc-inbox/fixtures` through Gemini (live calls).
- Each role reaches only `grocery-tracker-dev`, only the schemas it needs, with only the rights it needs; nothing else. Other roles on the cluster keep the access they have today.
- Code is written in this session (Opus 5.5).

## Boundaries & Constraints

**Always:**
- Writer: CONNECT on `grocery-tracker-dev`; USAGE on `public` (for `chains_v1`) and `retail_receipts_import`; SELECT on `public.chains_v1`; SELECT, INSERT on `receipts`; INSERT on `receipt_lines`, `receipt_settlements`, `receipt_feed`; USAGE on the feed sequence. Schema owner: CONNECT, owns both service schemas, nothing in `public`, no CREATE on the database. Resolver reader: CONNECT, USAGE on `resolver_v1`, SELECT on its views.
- No role of ours can CONNECT or TEMP to any other database. Removing PUBLIC's default grants first grants the same rights explicitly to every other existing login role, so nothing changes for them.
- Default privileges in `retail_receipts_import` give the writer SELECT, INSERT on new tables and USAGE on new sequences.
- One bot: before the home-server service starts, stop every other poller and confirm no pending updates.
- The batch import uses the pipeline and the writer role from `.env`, never prints secrets, reports per file: chain, outcome, receipt id or reason.

**Never:** No production database or roles; no change to `src/`, migrations or contracts (a defect found becomes a bug ticket); no `uv` or tests on the home server; no tests against the dev database.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Writer stores | valid receipt | stored with the narrowed grants | — |
| Writer overreach | UPDATE/DELETE on a receipt table, any `schema_migrations` access, connect to `postgres` | permission denied | — |
| Migrate rerun | narrowed owner, all applied | applies 0 | — |
| Batch, valid | sample of a supported chain | `stored` or `duplicate` | — |
| Batch, bad | unreadable or inconsistent sample | `failed` with its reason, nothing written | the batch continues |
| Batch, Gemini down | unavailable | file reported as waiting/failed, batch continues | no retry storm |

</frozen-after-approval>

## Code Map

- `scratch/audit_writer.py` -- read-only privilege audit as the writer; baseline found UPDATE/DELETE on all service tables, full access to `schema_migrations`, sequence SELECT, CONNECT/TEMP on `postgres` and `data` via PUBLIC.
- `src/retail_receipts_import/adapters/postgres/receipts.py:29-53` -- every statement the writer runs: two SELECTs on `receipts`, four INSERTs, no RETURNING, no UPDATE/DELETE.
- `adapters/postgres/chains.py:15` -- SELECT on `public.chains_v1`.
- `scratch/ingest_local.py` -- the pattern for driving `process_file` with real ports; replace the replay with the real Gemini client.
- `scratch/provision_dev.sql` -- current dev provisioning to correct.
- pg18 MCP runs over `ssh srv22` as superuser on database `postgres`; changes inside `grocery-tracker-dev` go through a temporary admin login role (`rri_tmp_admin`, member of `postgres`, dropped afterwards), as in story 3.
- Other login roles on the cluster: `lab_loader`, `lab_reader`, `retail_prices_ingest` (the last also uses `grocery-tracker-dev` and `public`).
- `README.md:57-78`, `.dockerignore`, `compose.yaml` -- deployment as in the earlier plan revision.

## Tasks & Acceptance

**Execution:**
- [ ] `scratch/narrow_dev_roles.py` -- one transaction as the temporary admin: the grants above, then a privilege matrix of the three roles over every database, schema and service table.
- [ ] `docs/deployment.md` -- provisioning SQL (roles, database, schemas, minimal grants, closing PUBLIC on other databases), sparse clone, `.env`, build, migrate, start, update; `README.md` links to it.
- [ ] `scratch/import_samples.py` -- takes a list of sample files, runs each through `process_file` with the real Gemini client and the writer; a per-file report to `scratch/import-report.md`.
- [ ] Live, with the owner: push `main`; on `srv22` sparse clone, `.env` with `RRI_ENV=dev`, build, `migrate` twice, start; one receipt sent through the bot; the 50-file import.

**Acceptance Criteria:**
- Given the narrowed roles, when the service stores a receipt and `migrate` reruns, then both succeed, and each overreach in the matrix is refused.
- Given the home server, when the runbook is followed, then the service starts in dev and stores a receipt sent through the bot.
- Given 50 samples, when the import finishes, then every file has a reported outcome and stored receipts are readable as the Resolver reader.

## Implementation Notes

## Plan Change Log

- 2026-10-24, owner: scope moved from a production deployment to trial operation on the dev database with role narrowing and a 50-receipt live import; the production steps wait for a later run of this ticket.

## Review Triage Log

## Verification

**Commands:**
- `wsl -- bash -l scratch/wsl-run.sh run python scratch/narrow_dev_roles.py` -- expected: matrix equals Always.
- Standard check suite in WSL -- expected: green (docs and scratch only change).
- `gh run list -L 1` after the push -- expected: success.
