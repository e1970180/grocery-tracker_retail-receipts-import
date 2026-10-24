---
title: 'First production deployment and acceptance demo'
type: 'chore'
ticket: '16'
created: '2026-10-24'
status: 'built'
baseline_revision: 'b295de207540daa3db89e644f97bc77c7e85bf8a'
route: 'full'
route_source: 'auto'
risk: 'high'
review: 'thorough'
review_source: 'user'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
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
- [x] `scratch/narrow_dev_roles.py` -- one transaction as the temporary admin: the grants above, then a privilege matrix of the three roles over every database, schema and service table.
- [x] `docs/deployment.md` -- provisioning SQL (roles, database, schemas, minimal grants, closing PUBLIC on other databases), sparse clone, `.env`, build, migrate, start, update; `README.md` links to it.
- [x] `scratch/import_samples.py` -- takes a list of sample files, runs each through `process_file` with the real Gemini client and the writer; a per-file report to `scratch/import-report.md`.
- [x] Live, with the owner: push `main`; on `srv22` sparse clone, `.env` with `RRI_ENV=dev`, build, `migrate` twice, start; one receipt sent through the bot; the 50-file import.
- [x] Format and comment `.env` files; create/update `.env.example` with documented environment variables and defaults.
- [x] Code documentation audit: verify docstrings and comments across `src/` following repository rules (plain English explaining why).
- [x] Write a detailed README in Russian covering architecture, configuration, deployment runbook, DB roles, and operations.

**Acceptance Criteria:**
- Given the narrowed roles, when the service stores a receipt and `migrate` reruns, then both succeed, and each overreach in the matrix is refused.
- Given the home server, when the runbook is followed, then the service starts in dev and stores a receipt sent through the bot.
- Given 50 samples, when the import finishes, then every file has a reported outcome and stored receipts are readable as the Resolver reader.
- Given `.env` and `.env.example`, all settings are formatted and clearly commented, with safe defaults in `.env.example` and no secrets committed.
- Given `src/`, all modules and functions have accurate English docstrings explaining intent and rationale without restating specs.
- Given the project documentation, a comprehensive README in Russian is written and accessible.

## Implementation Notes

- Written in this session (Opus 5.5). Runbook `docs/deployment.md` with `docs/deploy/provision.sql` and `docs/deploy/after-migrate.sql`; README links to it.
- Role narrowing, 2026-10-24: table rights by `scratch/narrow_dev_roles.py --apply` as `rri_dev_owner`. The agent's database-level change through pg18 and a temporary admin role were both refused by the harness as changes to shared resources. The owner ran `scratch/admin_narrow_dev.sql` as `postgres` through `postgres:16` psql on srv22: PUBLIC lost CONNECT/TEMP on `postgres`, `data` and `template1`; `lab_loader`, `lab_reader` and `retail_prices_ingest` got the same rights explicitly; `rri_dev_owner` lost CREATE/TEMP on the dev database; `public` is usable only by `rri_dev_writer` and `retail_prices_ingest`.
- `scratch/check_overreach.py` after both steps: the writer is refused UPDATE, DELETE, TRUNCATE, reads of lines/feed/`schema_migrations`/`resolver_v1`/`public.chains`, CREATE TABLE and TEMP; the reader is refused internal tables, `chains_v1`, `public` functions and TEMP; all three roles are refused on `postgres`, `data` and `template1`.
- Deployment, srv22 (192.168.100.22): the existing empty clone got the positive sparse set from the runbook, `main` at `7f9638f`; `compose build` ok; `.env` written over ssh stdin without the owner's and Resolver's credentials, mode 600; `migrate` from the container applied 0 three times (before and after narrowing); pending updates 0 and no local poller; `compose up -d` logged `ready: env=dev`.
- Surprise: on Windows, `subprocess` text input sends CRLF and the remote `read` kept the CR, so the first `migrate` failed authentication; the helper now sends bytes.
- Import of 50 samples (10 per chain, DM 9 plus one Kaufland), live Gemini, 2026-10-24: 44 stored, 5 duplicate, 1 failed. Duplicates are real: two Spar samples stored by earlier dev runs, `muller 6.jpeg` = `Attachment-3.png` and `muller 7.jpeg` = `Attachment-2.png` (same receipts), Kaufland `20250630_084443` = `20250625_185418` (same receipt, both checked by eye). All 44 are readable as `resolver_dev_reader` through `resolver_v1`.
- Defect found: Kaufland `20260427_231253.pdf` (valid receipt) fails `no_valid_result` because the returned bottle line `Boca za pivo * 4 * 0,16 -0,64` becomes a sale line with a negative amount, which the model refuses; reproduced on a second run, pass-2 response kept in `scratch/diagnose-pass2.json`. Filed as bug 22 and deferred there; not fixed here and not a condition of this ticket (Decision 2026-10-24, owner).
- Live bot run, 2026-10-24 16:29: the owner sent one Kaufland receipt to the bot; the srv22 service log shows job 1 go `chain_pending` → `extract_pending (kaufland)` → `write_pending` → `stored` in 10 s, two Gemini calls, no warnings. The Resolver reader then sees the feed at 52 rows (51 after the import).

- Development split from the service, 2026-10-24 (owner decision): `scratch/dev_role_split.py` generated two passwords without printing them, put a new writer password only into the srv22 `.env` (mode 600) and a new `rri_dev_developer` into the local `.env`; the owner ran `scratch/admin_dev_role.sql` (SCRAM verifiers only) as `postgres`. The developer is a member of `rri_dev_owner`, with CONNECT, CREATE, TEMPORARY on the dev database and SELECT on `public.chains_v1`. `scratch/check_developer.py`: reads, updates, deletes, DDL, new schemas and TEMP work; the other project's schema, `public` DDL and the other databases are refused. The srv22 container was recreated; logging in from it as the writer with the new password succeeds and stops at `permission denied for schema retail_receipts_import`, as the narrowed role should.

## Plan Change Log

- 2026-10-24, owner: added tasks to ticket 16 scope: format and comment .env files, create/update .env.example, audit codebase docstrings, and write a detailed README in Russian.

- 2026-10-24, owner: the workstation gets its own broad developer role in the dev database; the writer's password lives only on srv22.

- 2026-10-24, owner: scope moved from a production deployment to trial operation on the dev database with role narrowing and a 50-receipt live import; the production steps wait for a later run of this ticket.

## Review Triage Log

Thorough review, 2026-10-24, four lenses on the docs and the scratch scripts since the baseline (scratch is ignored but did the live work).

| Finding | Verdict | Evidence | Route |
| --- | --- | --- | --- |
| Sparse set lacks `/docs/`, so step 4's `after-migrate.sql` (and step 2's `provision.sql`) cannot run on the server (3 lenses) | medium | `ls` of the srv22 checkout: no `docs/` | patch: sparse set gains `/docs/deploy/ /docs/contracts/`; step 2 may run there |
| Default privileges give the writer SELECT, INSERT on new tables incl. the ledger until the trim; the trim is conditional (3 lenses) | medium | `provision.sql` default privileges; `migrate.py` creates `schema_migrations`; live dev is trimmed (matrix shows no ledger right) | patch: trim after every migrate, said in the runbook and the script header |
| Update one-liner starts the new code before migrate and the trim | medium | `docs/deployment.md` Update section chained `up -d` | patch: build, then step 4, then `up -d` |
| Step 4 gives no safe way to enter the owner's password | low | runbook only said "export" | patch: `read -rs` and `unset` |
| `after-migrate.sql` names today's tables; a new table loses its default grant | low | `REVOKE ALL` then explicit grants | patch: header line asks for a grant per new table |
| No test runs the writer's SQL under the trimmed grants | medium | `tests/conftest.py` uses the owner connection | defer |
| Three other roles lost TEMP on `template1` | low | `datacl` `=c` where PUBLIC had `Tc`; intent says others keep their access | defer, admin-only one-line fix |
| PUBLIC keeps CONNECT/TEMP on `grocery-tracker-dev` | false | `datacl` of the dev database has no PUBLIC entry; owner has `c` only |  reject |
| Unlisted login roles lose access to `postgres`, `data`, `template1` | false | `pg_roles`: the only other login roles are the three re-granted; `exp_dev` is NOLOGIN | reject |
| `check_overreach.py` may count "undefined object" as refused | false | rerun: every statement refused with 42501 | reject |
| Server `.env` may stay world-readable if it existed | false | `stat`: mode 600 | reject |
| `provision.sql` on a shared database would cut off a co-tenant's `public` | false | it starts with `CREATE DATABASE` under `ON_ERROR_STOP`, so it stops on an existing database | reject |
| The 50 receipts ran from the workstation, not through the deployed container | false | intent asks for the real pipeline and Gemini; the deployed service is proven by the srv22 bot receipt | reject |
| Runbook is dev-only; no prod names | false | intent: production provisioning waits | reject |
| No verification step in the runbook; partial-failure cleanup; single-poller check in Update | low | real but rare, fix adds steps | reject |
| `import_samples.py`: unfiltered spare files, crc32 collisions, report written after the loop, newline in details; `deploy_srv22.py` unquoted values; `resolver_counts.py` lacks a dev guard; `assert` checks | low | scratch scripts, run once; the batch completed and its report exists | reject |
| Plan says "one transaction as the temporary admin" and "process_file" | false | fix would edit this plan | reject |
| Writer grants not covered by a positive check | false | the 50-file import and the bot receipt wrote as the writer | reject |

## Verification

**Commands:**
- `wsl -- bash -l scratch/wsl-run.sh run python scratch/narrow_dev_roles.py` -- expected: matrix equals Always.
- Standard check suite in WSL -- expected: green (docs and scratch only change).
- `gh run list -L 1` after the push -- expected: success.
