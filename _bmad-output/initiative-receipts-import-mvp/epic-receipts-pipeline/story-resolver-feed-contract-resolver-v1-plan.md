---
title: 'Resolver feed contract resolver_v1'
type: 'feature'
ticket: '14'
created: '2026-10-24'
status: 'ready-for-dev'
baseline_revision: ''
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

**Problem:** Stored receipts are invisible to the Resolver: no `resolver_v1` views, grants or contract exist, and `docs/api-versions.md` lists it as pending.

**Approach:** One migration adds the `resolver_v1` views over the feed, receipts, lines and settlements, with timestamps as ISO-8601 UTC `Z` text and money and quantity as decimal strings, readable by the Resolver role only through those views. Publish contract 1.0.0 in `docs/contracts/resolver_v1.md` and its `docs/api-versions.md` row.

**Decisions (owner, 2026-10-24, from the field audit):**
- `store_name` is optional (done in `0003`).
- `loyalty_card_number` is not in 1.0.0; it may come in a minor version with a plug-in that fills it.
- `store_address` and `receipt_number` are free text as printed, format not guaranteed.

**Decisions (owner, 2026-10-24, planning):**
- Grants come from provisioning, not the migration: the admin creates schema `resolver_v1` owned by the schema owner and grants the environment's Resolver role USAGE on it, SELECT on its existing views and default privileges for SELECT on tables the schema owner creates there. The migration only creates views and names no role, as for `retail_receipts_import` and `chains_v1`. This supersedes the ticket's "by migration".
- The plan is kept whole at about 1,650 tokens.

## Boundaries & Constraints

**Always:**
- Views keep the default `security_invoker = false` and list columns explicitly, never `SELECT *`.
- Text output does not depend on the session `TimeZone`.
- The feed view defines both `stored` and `deleted` events in 1.0.0.

**Never:**
- No change to the internal tables or the writer.
- No production database; the production Resolver login role belongs to entry 16.
- The delete command (deferred work) is not built here.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| CURSOR | feed rows seq 1..3, cursor 1 | rows 2 and 3 in seq order | No error expected |
| STORED | receipt bought 2026-07-15 14:05 Zagreb | `purchased_at` `2026-07-15T12:05:00Z`, `purchased_at_local` `2026-07-15T14:05:00+02:00`, money `"1.50"` | No error expected |
| WINTER | bought 2026-01-15 14:05 Zagreb | `…13:05:00Z`, local offset `+01:00` | No error expected |
| SESSION_TZ | session `TimeZone` `America/New_York` | same text as under UTC | No error expected |
| INTERNAL | Resolver role selects `retail_receipts_import.receipts` or `schema_migrations` | refused | SQLSTATE 42501 |

</frozen-after-approval>

## Code Map

- `migrations/0003_store_name_optional.sql` -- last migration; the new one is `0004_resolver_v1.sql`.
- `migrations/0002_receipts.sql` -- source columns; `receipt_feed` has no FK and events `stored`/`deleted`.
- `src/retail_receipts_import/migrate.py` -- applies each file in one transaction as the schema owner; unchanged.
- `tests/conftest.py` -- `migrate_conn` drops and creates only `retail_receipts_import`; without `resolver_v1` there, `0004` fails for every integration test. `receipts_conn` applies all migrations.
- `src/retail_receipts_import/adapters/postgres/receipts.py` -- `write_receipt` to seed tests; `tests/test_receipts_writer.py` has receipt builders to reuse.
- `docs/contracts/chains_v1.md`, `docs/api-versions.md` -- contract layout and versioning text to mirror.
- `README.md:51-52`, `scratch/provision_dev.sql` -- provisioning notes; dev roles `rri_dev_owner` (has CREATE on the database), `resolver_dev_reader` (CONNECT only).
- Roles are cluster-global and `CREATE ROLE` has no `IF NOT EXISTS`: tests use a unique role name with a random password (local throwaway uses a password, CI uses trust) and drop it after; connect with `psycopg.conninfo.make_conninfo(dsn, user=…, password=…)`.

## Tasks & Acceptance

**Execution:**
- [ ] `migrations/0004_resolver_v1.sql` -- the four views per Design Notes in the provisioned `resolver_v1` schema, plus a `COMMENT ON SCHEMA resolver_v1` naming it the Resolver contract; no `CREATE SCHEMA`, no role names, no GRANT.
- [ ] `tests/conftest.py` -- `migrate_conn` drops and recreates `resolver_v1` alongside the service schema, as provisioning would.
- [ ] `tests/test_resolver_v1.py` (integration) -- a fixture creates a unique login role with a random password, provisions it as the admin would (USAGE on `resolver_v1` and `ALTER DEFAULT PRIVILEGES … IN SCHEMA resolver_v1 GRANT SELECT ON TABLES`) before applying the migrations, so the default-privilege path is what grants the views; cleanup runs `DROP OWNED BY` and `DROP ROLE` after the schemas are dropped. One test per matrix row, connected as that role; a stored receipt with a line, a discount and two settlements read back field by field; a `deleted` feed row visible with no receipt row.
- [ ] `docs/contracts/resolver_v1.md` -- contract 1.0.0: objects, columns, types and rules, privileges with the provisioning SQL for a placeholder role (USAGE, `GRANT SELECT ON ALL TABLES IN SCHEMA`, default privileges), reading rules, versioning.
- [ ] `docs/api-versions.md`, `README.md` -- `resolver_v1` 1.0.0 Published; README: provisioning also creates `resolver_v1` before the first migrate.
- [ ] Dev live check (owner approval, done by the planning session, not the coder) -- provision `resolver_v1` in `grocery-tracker-dev` for `rri_dev_owner` and `resolver_dev_reader`, `migrate` as `rri_dev_owner`, then a scratch script as `resolver_dev_reader` reads the feed and stored receipts and is refused on `retail_receipts_import.receipts`.

**Acceptance Criteria:**
- Given the dev database after migrate and provisioning, when `resolver_dev_reader` reads `resolver_v1.feed` with cursor 0, then it sees every stored dev receipt with `Z` timestamps and decimal-string money, and an internal table read is refused.
- Given a push, when CI runs, then the standard suite and integration tests pass.

## Design Notes

Views in schema `resolver_v1`; `T` = text.

| View | Columns |
| --- | --- |
| `feed` | `seq` bigint, `receipt_id` uuid, `event` T (`stored`, `deleted`) |
| `receipts` | `receipt_id`, `chain_id`, `store_name`?, `branch_number`?, `receipt_number`?, `store_address`?, `currency`, `purchased_at` T `Z`, `purchased_at_local` T `+HH:MM`, `buyer_name` |
| `receipt_lines` | `line_id`, `receipt_id`, `line_no`, `printed_text`, `quantity` T, `unit`?, `unit_price` T?, `printed_amount` T, `included_discount` T, `separate_discount` T, `discount_text`?, `regular_amount` T, `effective_amount` T |
| `receipt_settlements` | `receipt_id`, `settlement_no`, `kind`, `printed_text`, `amount` T (signed) |

`?` = nullable. Left out of 1.0.0 (adding later is minor, removing is major): `loyalty_card_number` (owner), `source_kind`, `source_ref`, `created_at`, an amount-paid column.

- UTC text: `to_char(purchased_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')`. Local: the Zagreb wall time plus an offset computed from the difference of the two `AT TIME ZONE` values, not `TZH:TZM`, which follows the session.
- Contract text states: `seq` grows in commit order of the single writer and may have gaps, so read `seq > cursor`; a `stored` event whose receipt is gone is followed by a `deleted` event; stored lines hold only purchases (storno netted, returns dropped), so their sum can exceed the settlements when the receipt had a return; money is a decimal string with two places, quantity with three.

## Verification

**Commands:**
- WSL `uv run ruff check`, `ruff format --check`, `mypy`, `pytest` -- expected: pass.
- `bash scratch/integration-throwaway.sh` (throwaway `postgres:18.6`) -- expected: integration tests pass.
