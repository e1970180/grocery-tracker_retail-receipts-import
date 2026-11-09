# Contract: `public.ref_country`

- **Contract Version:** `v2.0.0`
- **Status:** `Active`
- **Release Date:** 2026-11-05
- **Last Reconciled:** 2026-11-05
- **Owner:** `common`
- **Managing Project:** `common`
- **Target Database Schema:** `public`
- **Target Table:** `public.ref_country`
- **Reference DDL:** `migrations/0001_ref_country.sql`
- **Fixture:** `tests/fixtures/contracts/ref_country.sql`
- **Test Suite:** `tests/contracts/test_ref_country_contract.py` (live conformance), `tests/test_migration_0001_ref_country.py` (migration on a throwaway table)

---

## 1. Scope & Purpose

This contract defines the normative specification, versioning rules, provisioning guidelines, consumer registry, and change management procedures for the shared reference table `public.ref_country`.

The table is the ISO 3166-1 alpha-2 country list (249 rows) with an ISO 4217 currency per country. It was created and seeded by `canonical-products` and handed over to `common`, which is the managing project from contract version 2.0.0 onward.

### Architectural Invariants

1. **Foreign-Key Target:** Unlike `public.chains`, whose contract forbids foreign keys, `public.ref_country` is the opposite: consumers **may** reference `public.ref_country(country_code)` by foreign key. The table is a stable reference, and its primary key is permanent.
2. **No Activity Flag:** The table carries no activity flag and no other restricting column, and none is ever added. The table is a reference, not a switchboard: a need to restrict the list is a project error to record, not a column to add.
3. **Read-Only After Seeding:** Migration 0001 creates the table and seeds it only when empty. No consumer inserts, updates, deletes, or alters rows. Rows change only through a published contract release by `common` (Section 3).

---

## 2. Specification (v2.0.0)

### 2.1 Identity & Ownership

- **Table:** `public.ref_country`
- **Managing Project:** `common`. It owns every change to the table, its fixture, and this contract.
- **Table Owner Role:** `postgres`. The owner role does not change: there is no `ALTER TABLE ... OWNER TO` in any migration, and none is planned.

### 2.2 Column Specifications & Constraints

| Column Name | PostgreSQL Type | Nullable | Key | Constraints & Rules |
|---|---|---|---|---|
| `country_code` | `character varying(2)` | `NO` | Primary key | ISO 3166-1 alpha-2, upper case only (`country_code ~ '^[A-Z]{2}$'`, constraint `ref_country_country_code_check`), for example `HR`. Never renamed, mutated, or reassigned. |
| `name` | `text` | `NO` | | English short name, for example `Croatia`. |
| `currency` | `character varying(3)` | `NO` | | ISO 4217 alpha-3, for example `EUR`. Territories without an official currency carry `XXX`. |

The table has exactly these three columns, one primary key, and one CHECK constraint. It has no activity flag.

### 2.3 Seed Scope

The full ISO 3166-1 alpha-2 list: exactly 249 rows, loaded by `migrations/0001_ref_country.sql` and exported to `tests/fixtures/contracts/ref_country.sql`. The live table equals the fixture row for row.

---

## 3. Semantic Versioning & Compatibility

This contract adheres to Semantic Versioning (`MAJOR.MINOR.PATCH`):

- **PATCH:** Documentation clarifications, test suite expansions, or non-functional DDL comments. Zero change to table shape or rows.
- **MINOR:** Backward-compatible row changes that existing foreign keys survive unchanged: correcting the `name` or `currency` of an existing row, or adding a row for a newly assigned ISO 3166-1 code. The `country_code` of an existing row is never changed. Fixture and conformance test (including the row count) are updated in the same commit. Any column change needs a new contract version and test update, and a restricting or activity column is never added.
- **MAJOR:** Any breaking change:
  - Dropping, renaming, or retyping a column.
  - Tightening nullability or a constraint so that existing rows or referencing rows are rejected.
  - Changing the primary key.
  - Removing or renumbering a row, which is allowed only for a row no registered consumer references.
  - A major version never mutates the deployed table in place; it is released as a distinct versioned relation deployed side-by-side while any registered consumer depends on the old one.

### Lifecycle Invariants

While any registered consumer depends on this contract:
1. **Primary Key Immutability:** A `country_code` is permanent and is never reused for another country.
2. **Non-Deletion:** A row referenced by a registered consumer is never deleted or renumbered.
3. **Table Identity:** `public.ref_country` is never dropped, renamed, or relocated to another schema.

---

## 4. Provisioning Guidelines

### 4.1 Deployment Model

- **Migration:** `migrations/0001_ref_country.sql` creates the table if missing and seeds it only when empty. Re-applying it to a populated table changes nothing. It contains no `GRANT` statements by design.
- **Caller:** The caller manages the transaction context (`psql -1`, or a test transaction).
- **Isolated Consumer Test & CI Environments:** Consumers may vendor `migrations/0001_ref_country.sql` during test bootstrap to obtain the table before creating their own foreign keys.

### 4.2 Privileges

Privileges are provisioned per environment, outside migration 0001. On the shared database, observed at `last_reconciled`:

| Role | Privileges on `public.ref_country` |
|---|---|
| `postgres` | owner (all) |
| `canonical_developer` | `SELECT`, `REFERENCES` |
| `canonical_test` | `SELECT`, `REFERENCES` |
| `common_developer` | `SELECT` |
| `common_reader` | `SELECT` |
| `common_test` | all (test runner; its tests never write to the live table by convention, not by grant) |

A fresh database built from migration 0001 alone does not carry these grants; the environment administrator applies them. Consumers must not assume them on a database they provision themselves. Consumer roles (`canonical_developer`, `canonical_test`) and reader roles receive no `INSERT`, `UPDATE`, or `DELETE`.

---

## 5. Consumer Registry

Consumers of `public.ref_country` are formally registered with `common`. Dependents are observed from foreign keys in the live catalog as of `last_reconciled` (2026-11-05).

| Consumer Repository | Usage Context | Referencing Objects | Registered Since | Status |
|---|---|---|---|---|
| `canonical-products` | Foreign-key target of country attribution | `canonical_product.private_label_brands` (`country_code`), `canonical_product.retail_receipt_abbreviations` (`country_code`) | 2026-11-05 | Active |
| `retail-prices-ingest` | Planned country attribution | None yet; no foreign key declared | 2026-11-09 | Active |
| `retail-receipts-import` | Planned country attribution | None yet; no foreign key declared | 2026-11-09 | Active |
| `taxonomy` | Planned country attribution | None yet; no foreign key declared | 2026-11-09 | Active |

### Registration Process

New consumers must register before declaring a foreign key to `public.ref_country`:
1. Submit an intake note to `common/docs/handovers/` naming the consuming service, repository path, referencing objects, and required privileges (`SELECT`, `REFERENCES`).
2. The `common` custodian registers the consumer in the table above, applies the grants for the environment, and publishes an updated contract release.

---

## 6. Change Request Procedure

The managing project `common` owns every change after handover. Consumers must never alter the table, its constraints, or its rows directly.

1. **Submit Request:** Author a request in the consumer repository under `docs/handovers/request-ref-country-<topic>.md` stating the proposed change, rationale, impact on referencing objects, and timeline, and forward it to `common/docs/handovers/`.
2. **Announce Breaking Changes:** Every MAJOR change under Section 3 (including dropped or renamed column, type change, nullability or constraint tightening, key change, row removal) is announced to the `canonical-products` owner before deployment.
3. **One Commit:** The contract, the fixture, and the regression test are updated in one commit, before the change goes live.
4. **Version Bump:** Every change bumps `contract_version` under the rules in Section 3.
5. **Reconciliation:** Every reconciliation against the live catalog (columns, constraints, row count, owner, grants, and foreign-key dependents) updates `last_reconciled`.
6. **Implementation:** Consumers make no code or schema adjustments until the new version is published by `common`.

---

## 7. Conformance Verification

`common` maintains automated checks against PostgreSQL 18.6:

1. **Live Conformance (`tests/contracts/test_ref_country_contract.py`):** Read-only. Verifies the exact three columns with types, lengths, and nullability; the single primary key on `country_code`; the exact CHECK `^[A-Z]{2}$`; the absence of any activity or extra column; the row count 249; and row equality between the live table and the fixture.
2. **Migration Conformance (`tests/test_migration_0001_ref_country.py`):** Runs migration 0001 against a `pg_temp` table in place of `public.ref_country`; verifies creation, the 249-row seed equal to the fixture, idempotent re-application, seeding of an existing empty table, and that a populated table is left untouched.

3. **Source Read-Only (`test_source_is_read_only`):** Asserts the live test file issues only `SELECT` against `public.ref_country`.

Tests never write to the live table. They read it, or load the fixture into a throwaway table. `last_reconciled` is the date of the last passing live run, on which the owner, grants, and foreign-key dependents in Sections 2.1, 4.2 and 5 were also read from the live catalog.
