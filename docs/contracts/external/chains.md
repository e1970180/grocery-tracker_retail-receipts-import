# Contract: `public.chains_v1`

- **Contract Version:** `v1.2.0`
- **Status:** `Active`
- **Release Date:** 2026-11-04
- **Owner:** `common`
- **Target Database Schema:** `public`
- **Target View:** `public.chains_v1`
- **Underlying Table:** `public.chains`
- **Reference DDL:** `migrations/0020_chains.sql` (greenfield baseline), `migrations/0021_migrate_chains_v1_2_0.sql` (in-place migration), `migrations/0022_grant_chains_v1_canonical_products.sql` (consumer privilege grants)
- **Test Suite:** `tests/test_chains.py`

---

## 1. Scope & Purpose

This contract defines the normative specification, schema constraints, lifecycle invariants, provisioning guidelines, consumer registry, and change management procedures for the shared database view `public.chains_v1` and its underlying table `public.chains`.

The `chains` catalog provides an authoritative, shared reference of known retail grocery chains across the grocery-tracker ecosystem. It is owned, maintained, and migrated centrally by `common`.

### Architectural Invariants & Decoupling

1. **View Abstraction:** Downstream consumer services interact exclusively with the view `public.chains_v1` by name. Consumers must never query the underlying table `public.chains` directly or rely on PostgreSQL enumerated types. `common` reserves the right to modify the underlying table structure, storage, or indexing freely provided the `public.chains_v1` view shape and behavioral invariants are preserved.
2. **Zero Foreign Keys:** Downstream consumer schemas (such as receipt ingestion tables in `retail-receipts-import` or future services) **must never declare foreign keys** pointing to `public.chains`. Consumer records store `chain_id` as an independent text slug and validate against `public.chains_v1` at the application service boundary. This ensures strict decoupling: migrations, maintenance, or test provisioning in consumer databases remain independent of shared catalog physical storage.

---

## 2. Specification (v1.2.0)

### 2.1 Identity & Schema Objects

- **Underlying Table:** `public.chains`
- **Exposed View:** `public.chains_v1`
- **View Definition:**
  ```sql
  CREATE VIEW public.chains_v1 AS
  SELECT chain_id, display_name, aliases, country_code, tax_numbers, active
  FROM public.chains;
  ```
- **Unordered Projection Invariant:** The view projection `public.chains_v1` does not declare an internal `ORDER BY`. Downstream services requiring sorted results (e.g. for deterministic processing or UI display) must explicitly append `ORDER BY chain_id` in their queries.
- **Nullability Invariant:** Only the `tax_numbers` column is nullable. All other columns (`chain_id`, `display_name`, `aliases`, `country_code`, `active`) are strictly `NOT NULL`.

### 2.2 Column Specifications & Constraints

The underlying table `public.chains` enforces the following column definitions and integrity constraints:

| Column Name | PostgreSQL Type | Nullable | Default | Constraints & Rules |
|---|---|---|---|---|
| `chain_id` | `text` | `NO` | *None* | Primary key (`chains_pkey`). Lowercase ASCII slug matching `^[a-z][a-z0-9_]{0,31}$` (`chains_chain_id_slug`). Must not equal reserved identifiers `other` or `unreadable` (`chains_chain_id_not_reserved`). Primary keys are immutable: once created, an identifier is never renamed, mutated, or reassigned. |
| `display_name` | `text` | `NO` | *None* | Human-facing display name. Must not be empty or whitespace-only (`btrim(display_name) <> ''`, constraint `chains_display_name_not_empty`). |
| `aliases` | `text[]` | `NO` | `'{}'` | Trade names, store brands, and aliases printed on receipts. Must be a one-dimensional array (`coalesce(array_ndims(aliases), 1) = 1`), contain no `NULL` elements (`array_position(aliases, NULL) IS NULL`), and contain no empty strings (`'' <> ALL (aliases)`). May be an empty array (`{}`). Constraint `chains_aliases_valid`. |
| `country_code` | `text` | `NO` | *None* | Two-letter uppercase ASCII ISO 3166-1 alpha-2 country code (`country_code ~ '^[A-Z]{2}$'`, constraint `chains_country_code_valid`). Not a foreign key; validated by regex format convention only. |
| `tax_numbers` | `text[]` | `YES` | *None* | Tax identifiers printed on receipts. May be `NULL` or an empty array `{}`; both represent a chain without printed tax identifiers. When present, must satisfy general and country-specific rules (see below). Constraints `chains_tax_numbers_valid` and `chains_hr_tax_numbers_oib`. |
| `active` | `boolean` | `NO` | `true` | Operational status flag. Setting `active = false` withdraws the chain from active processing. Chains are deactivated, never deleted. |

#### Tax Numbers Validation Rules

1. **General Format Rule (`chains_tax_numbers_valid`):**
   - Must be a one-dimensional array (`coalesce(array_ndims(tax_numbers), 1) = 1`).
   - Must contain no `NULL` elements (`array_position(tax_numbers, NULL) IS NULL`).
   - Elements must not be blank or whitespace-only (`cardinality(tax_numbers) = 0 OR array_to_string(tax_numbers, ',') !~ '(^|,)[[:space:]]*(,|$)'`).
   - Elements must not contain commas (ensured by string substitution length parity: `length(replace(array_to_string(tax_numbers, ','), ',', '')) = length(array_to_string(tax_numbers, ',')) - greatest(cardinality(tax_numbers) - 1, 0)`).
2. **Croatian OIB Enforcement (`chains_hr_tax_numbers_oib`):**
   - When `country_code = 'HR'`, if `tax_numbers` is non-null and non-empty, every element must be exactly 11 decimal digits representing a valid Croatian OIB (`array_to_string(tax_numbers, ',') ~ '^[0-9]{11}(,[0-9]{11})*$'` and `length(array_to_string(tax_numbers, ',')) = 12 * cardinality(tax_numbers) - 1`).
   - For all other countries (`country_code <> 'HR'`), alphanumeric and formatted tax numbers (e.g. `DE123456789`, `ATU12345678`, `12-3456789`) are accepted provided they satisfy the general array rules.

### 2.3 Reference Seed Entities (v1.2.0)

The v1.2.0 catalog provides 5 baseline retail chains operating in Croatia:

| `chain_id` | `display_name` | `aliases` | `country_code` | `tax_numbers` | `active` |
|---|---|---|---|---|---|
| `dm` | `dm` | `{"DM", "dm"}` | `HR` | `{"94124811986"}` | `true` |
| `kaufland` | `Kaufland` | `{"KAUFLAND", "Kaufland"}` | `HR` | `{"47432874968"}` | `true` |
| `lidl` | `Lidl` | `{"LIDL", "Lidl"}` | `HR` | `{"66089976432"}` | `true` |
| `mueller` | `Müller` | `{"MÜLLER", "Müller", "Muller"}` | `HR` | `{"84698789700"}` | `true` |
| `spar` | `Spar` | `{"SPAR", "Spar", "INTERSPAR"}` | `HR` | `{"46108893754"}` | `true` |

*Note: The tax numbers listed are the official 11-digit company OIBs printed on fiscal receipts issued by each chain in Croatia.*

### 2.4 Ecosystem Roles & Privileges

Access to `public.chains_v1` is governed by database role privileges:

- **Required Grants:**
  - `USAGE` on schema `public`.
  - `SELECT` on view `public.chains_v1`.
- **Authorized Roles:**
  - `rri_dev_writer`: Ingestion writer role for `retail-receipts-import` (read-only consumer).
  - `rri_dev_developer`: Development and debugging role for `retail-receipts-import`.
  - `canonical_developer`: Development and debugging role for `canonical-products` (read-only consumer).
  - `canonical_test`: Test runner role for `canonical-products`.
  - `common_reader`: Ecosystem-wide read-only reader role.
  - `common_developer`: Ecosystem developer role.
  - `common_test`: Test runner role for automated conformance and integration suites.
- **Read-Only Security Boundary:**
  - Consumer and reader roles (`rri_dev_writer`, `canonical_developer`, `canonical_test`, `common_reader`) are strictly prohibited from receiving `INSERT`, `UPDATE`, or `DELETE` privileges on `public.chains_v1` or `public.chains`.
  - Catalog modifications and seed provisioning are executed exclusively by administrative migration roles (`postgres`, `common_admin`).

---

## 3. Semantic Versioning & Compatibility

This contract adheres strictly to Semantic Versioning (`MAJOR.MINOR.PATCH`):

- **PATCH:** Documentation clarifications, test suite expansions, non-functional DDL comments, or internal performance indexes that do not affect the view shape or constraint rules. Zero change to SQL view definition or column types.
- **MINOR:** Backward-compatible additions to `public.chains_v1` (e.g. adding a new nullable or defaulted column). Existing queries referencing `public.chains_v1` continue to operate without modification.
- **MAJOR:** Any breaking change to the contract:
  - Removing, renaming, or retyping an existing column.
  - Tightening constraint expressions such that previously valid chain records are rejected.
  - Altering slug format rules or adding new reserved identifiers.
  - Major version increments **never modify an existing view in place**.
  - A new major version is released as a distinct view (e.g. `public.chains_v2`) deployed side-by-side with `public.chains_v1`.
  - Existing views remain deployed and supported in perpetuity as long as any registered consumer still depends on them.

### Historic Exception (v1.2.0)

Version `1.2.0` represents a singular, owner-authorized in-place upgrade decided on 2026-11-03:
- Added `country_code` (`text NOT NULL`).
- Replaced legacy `seller_oibs` column with nullable `tax_numbers` (`text[]`).
- Transferred schema and migration ownership to `grocery-tracker/common`.
- Upgraded view `public.chains_v1` in place, requiring a synchronized release with consumer `retail-receipts-import`.
- All future updates after v1.2.0 strictly follow non-breaking SemVer evolution.

### Lifecycle Invariants

While any registered consumer depends on this contract:
1. **Primary Key Immutability:** A `chain_id` is permanent. It is never renamed, mutated, or reused for another retailer.
2. **Non-Deletion Invariant:** Records in `public.chains` are never deleted via `DELETE`. Discontinued or inactive chains have their status updated to `active = false`. Downstream consumers filter by `active = true` during active ingestion while retaining historical receipt attribution integrity.
3. **View-Only Interface:** Consumers access the catalog exclusively through `public.chains_v1`.

---

## 4. Provisioning Guidelines

### 4.1 Deployment Model & Dual-Path Provisioning

`common` provides two complementary DDL migration paths:

1. **Greenfield Bootstrap (`migrations/0020_chains.sql`):**
   - Applied in fresh database environments, local Docker instances, and ephemeral consumer test environments.
   - Creates `public.chains` table with all v1.2.0 check constraints, creates view `public.chains_v1`, and inserts the 5 baseline reference seeds.
2. **In-Place Upgrade (`migrations/0021_migrate_chains_v1_2_0.sql`):**
   - Applied in pre-existing shared databases holding the legacy schema (`seller_oibs`).
   - Drops `public.chains_v1`, adds `country_code`, backfills existing rows with `'HR'`, sets `country_code` to `NOT NULL`, renames and modifies `seller_oibs` to nullable `tax_numbers`, applies v1.2.0 constraints, recreates `public.chains_v1`, and idempotently restores role grants for all ecosystem roles.

### 4.2 Multi-Environment Distribution Strategy

1. **Shared Ecosystem Databases (Dev / Staging / Production):**
   - Migrations are executed centrally by `common` migration runners.
   - Downstream consumers assume `public.chains_v1` is pre-provisioned and grants are active prior to consumer deployment.
2. **Isolated Consumer Test & CI Environments:**
   - Consumers provisioning ephemeral test databases may vendor the standalone `migrations/0020_chains.sql` DDL script during test bootstrap.
   - Consumer tests can safely verify integration with `public.chains_v1` in local PostgreSQL containers without network dependency on shared databases.
3. **Consumer Decoupling Rule:**
   - Downstream migrations must never create foreign key constraints pointing to `public.chains`.
   - Downstream services must never attempt DDL operations or schema mutations on `public.chains` or `public.chains_v1`.

---

## 5. Consumer Registry

Consumers of `public.chains_v1` are formally registered with `common`.

| Consumer Repository | Usage Context | Stored / Referenced Data | Registered Since | Status |
|---|---|---|---|---|
| `retail-receipts-import` | Read-only lookup of known retail chains; matches receipts by aliases and tax numbers | Attributed receipt `chain_id` text field (no foreign key) | 2026-11-04 | Active |
| `canonical-products` | Read-only lookup and validation of retail chains | Attributed `chain_id` text slug (zero foreign keys) | 2026-11-04 | Active |
| `retail-prices-ingest` | Planned read-only lookup of retail chains | Not yet stored; no foreign key declared | 2026-11-09 | Active |
| `taxonomy` | Planned read-only lookup of retail chains | Not yet stored; no foreign key declared | 2026-11-09 | Active |

### Registration Process

New consumer applications or services within the grocery-tracker ecosystem must register before querying `public.chains_v1`:
1. Submit an intake note or registration request to `common/docs/handovers/` specifying the consuming service name, repository path, intended query patterns, and environment requirements.
2. The `common` custodian verifies role privileges, registers the consumer in the table above, and publishes an updated contract release.

---

## 6. Change Request Procedure

Consumers must never alter table definitions, constraints, or seed data in `public.chains` directly.

To propose additions or modifications (e.g. registering a new grocery chain, adding aliases, supporting a new country, or proposing schema adjustments):
1. **Submit Request:** Author a request document in the consumer repository under `docs/handovers/request-chains-<topic>.md` stating:
   - Specific proposed change (e.g. new chain slug, legal name, aliases, country code, tax identifiers).
   - Business and domain rationale (e.g. expansion to new retailer or geographic region).
   - Technical impact assessment on receipt matching and active consumers.
   - Target timeline or deadline.
2. **Deliver to Owner:** Forward the request to `common` maintainers via `common/docs/handovers/`.
3. **Owner Evaluation:** `common` evaluates the request and responds with:
   - An accepted proposal scheduling a new migration and contract release under SemVer rules (Section 3), or
   - A written response detailing technical or architectural constraints.
4. **Implementation:** Downstream consumers make zero code or assumption adjustments until the new version is officially provisioned and published by `common`.

---

## 7. Conformance Verification

To guarantee continuous adherence to this contract, `common` maintains an automated 8-check conformance test suite against PostgreSQL 18.6 (`tests/test_chains.py`):

1. **Table and View Schema Conformance (`test_check_1_table_and_view_schema`):**
   - Validates that `public.chains` contains all 6 required columns with exact data types and nullability (`tax_numbers` nullable, all others `NOT NULL`).
   - Confirms absence of legacy column `seller_oibs`.
   - Asserts single primary key constraint `chains_pkey` on `chain_id`.
   - Confirms presence of all 7 check constraints (`chains_chain_id_slug`, `chains_chain_id_not_reserved`, `chains_display_name_not_empty`, `chains_aliases_valid`, `chains_country_code_valid`, `chains_tax_numbers_valid`, `chains_hr_tax_numbers_oib`).
   - Asserts 100% column projection parity between `public.chains` and view `public.chains_v1`.
2. **Seed Records Conformance (`test_check_2_seed_records`):**
   - Queries `public.chains_v1` and validates exact presence of all 5 canonical Croatian seeds (`dm`, `kaufland`, `lidl`, `mueller`, `spar`).
   - Asserts valid non-empty display names, valid non-empty aliases arrays, `country_code = 'HR'`, 11-digit numeric OIB tax numbers, and `active = true`.
3. **Slug Regex and Reserved IDs (`test_check_3_slug_and_reserved_ids`):**
   - Asserts rejection of invalid slugs: uppercase letters, hyphens, leading digits, leading underscores, symbols, spaces, empty strings, and slugs exceeding 32 characters.
   - Asserts rejection of reserved IDs `other` and `unreadable`.
   - Asserts rejection of duplicate primary keys.
   - Verifies acceptance of valid slugs up to 32 characters on both live and isolated temporary tables.
4. **Display Name and Aliases Integrity (`test_check_4_display_name_and_aliases`):**
   - Asserts rejection of empty string, whitespace-only, and `NULL` display names.
   - Asserts rejection of aliases containing `NULL` elements, empty strings, 2D arrays, or `NULL` array column.
   - Verifies acceptance of valid multi-element alias arrays and empty arrays `{}`.
5. **Country Code Format (`test_check_5_country_code`):**
   - Asserts rejection of invalid country codes: lowercase letters, 3-letter codes, digits, symbols, empty strings, and `NULL`.
   - Verifies acceptance of valid 2-letter uppercase ASCII ISO codes (`HR`, `DE`, `AT`, `IT`, `SI`, `US`, `FR`).
6. **Tax Numbers General Format (`test_check_6_tax_numbers_general`):**
   - Asserts rejection of tax number elements containing commas, whitespace-only/empty elements, `NULL` elements, and 2D arrays.
   - Verifies acceptance of `NULL`, empty array `{}`, and valid foreign multi-element tax arrays.
7. **Croatian OIB vs Foreign Tax Numbers (`test_check_7_hr_tax_numbers_oib`):**
   - For `country_code = 'HR'`, strictly rejects tax numbers with fewer than 11 digits, greater than 11 digits, non-digit characters, or mixed arrays with invalid elements.
   - For foreign countries (`AT`, `DE`, `US`, `SI`), verifies acceptance of non-11-digit and alphanumeric tax identifier formats.
8. **Consumer Role Privileges and Non-Deletion Lifecycle (`test_check_8_privileges_and_non_deletion`):**
   - Verifies `SELECT` on `public.chains_v1` and `USAGE` on schema `public` for all ecosystem roles (`rri_dev_writer`, `rri_dev_developer`, `canonical_developer`, `canonical_test`, `common_reader`, `common_developer`, `common_test`).
   - Verifies that consumer and reader roles (`rri_dev_writer`, `canonical_developer`, `canonical_test`, `common_reader`) have zero write privileges (`INSERT`, `UPDATE`, `DELETE`).
   - Verifies non-deletion lifecycle: setting `active = false` preserves the row and primary key in `public.chains_v1`, properly excludes the chain when filtering by `active = true`, and allows seamless reactivation.
