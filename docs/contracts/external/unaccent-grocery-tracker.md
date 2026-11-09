# Contract: `public.unaccent_grocery_tracker(text)`

- **Contract Version:** `v1.0.0`
- **Status:** `Active`
- **Release Date:** 2026-11-03
- **Owner:** `common`
- **Target Database Schema:** `public`
- **Reference DDL:** `migrations/0011_unaccent_grocery_tracker.sql`
- **Test Suite:** `tests/test_unaccent_grocery_tracker.py`

---

## 1. Scope & Purpose

This contract defines the normative specification, immutability guarantees, behavioral rules, provisioning guidelines, and change management procedures for the shared database routine `public.unaccent_grocery_tracker(text)`.

The routine provides deterministic, accent-insensitive transliteration across all Unicode code points. It is designed specifically for use in immutable normalization functions (such as `retail.norm(text)`), generated stored columns, and trigram/B-tree indexes across the grocery-tracker ecosystem.

---

## 2. Specification (v1.0.0)

### 2.1 Identity & Signature

- **Function Signature:** `public.unaccent_grocery_tracker(t text) RETURNS text`
- **Language:** `sql`
- **Volatility:** `IMMUTABLE` (`provolatile = 'i'` in `pg_proc`)
- **Parallel Safety:** `PARALLEL SAFE` (`proparallel = 's'` in `pg_proc`)
- **Strictness:** `STRICT` (`proisstrict = true` in `pg_proc`)
- **Null & Empty Behavior:**
  - `public.unaccent_grocery_tracker(NULL)` returns `NULL`
  - `public.unaccent_grocery_tracker('')` returns `''`
- **Zero External Dependencies:**
  - The function body is composed exclusively of `replace()` and `translate()` invocations over character literals.
  - The function has **zero dependency** on the PostgreSQL `unaccent` extension, catalog tables, or external configuration settings.
  - The function executes deterministically under any `search_path`, including an empty `search_path = ''`.
  - The function remains fully operational even if the `unaccent` extension is dropped from the database.

### 2.2 Transliteration & Character Folding Rules

- **Coverage:** Evaluated across all 1,112,063 non-surrogate Unicode code points (U+0001 through U+10FFFF excluding U+D800..U+DFFF).
- **Baseline Equivalence:** For every non-surrogate code point, `public.unaccent_grocery_tracker(chr(i))` yields the exact transliteration produced by PostgreSQL 18.6 unaccent dictionary (`public.unaccent('public.unaccent', chr(i))`).
- **Frozen Character Table:** Exactly 2,661 characters undergo transliteration or removal:
  - 2,218 characters map one-to-one to unaccented base characters (including ASCII characters and unaccented Greek/Cyrillic scripts).
  - 337 characters expand to multi-character sequences (e.g. `Æ` -> `AE`, `ß` -> `ss`).
  - 106 characters are removed (e.g. combining diacritical marks).
- **Single-Pass Invariance:** Character folding is applied in a single logical pass. Output replacement characters are never recursively or repeatedly folded.
- **Freeze Guarantee:** The transliteration table is permanently frozen to the PostgreSQL 18.6 baseline rules. It will not track upstream PostgreSQL or extension changes within major version 1.

---

## 3. Semantic Versioning & Compatibility

This contract adheres to Semantic Versioning (`MAJOR.MINOR.PATCH`):

- **PATCH:** Clarifications in documentation, test additions, generator tooling optimizations, or comment changes. Zero change to SQL logic, function signature, or character mappings.
- **MINOR:** Backward-compatible additions that do not modify output for any input previously handled or stored by consumers. (Note: given the frozen nature of the 18.6 transliteration table, minor versions are not anticipated).
- **MAJOR:** Any change to the transliteration output of any character or string.
  - A major version increment **never modifies the existing function in place**.
  - A new major version is released as a distinct function with a version suffix (e.g., `public.unaccent_grocery_tracker_v2(text)`).
  - The existing function (`public.unaccent_grocery_tracker`) remains deployed, immutable, and unmodified in perpetuity as long as any registered consumer still depends on it.
  - Consumers migrate to new major versions on their own independent deployment schedules and rebuild their stored indexes/columns at their discretion.

### Lifecycle Invariants

While any registered consumer exists:
1. `public.unaccent_grocery_tracker(text)` will **never** be edited in place.
2. The function will **never** be dropped, renamed, or relocated to another schema.
3. Volatility (`IMMUTABLE`), parallel safety (`PARALLEL SAFE`), and strictness (`STRICT`) attributes will **never** be altered.

---

## 4. Provisioning Guidelines

### 4.1 Deployment Model & Privilege Requirements

- **Target Object:** The function is provisioned strictly within schema `public`.
- **Privileges:**
  - Role applying DDL requires `CREATE` privilege on schema `public`.
  - Default PostgreSQL `EXECUTE` privileges granted to `PUBLIC` (or all database roles) must not be revoked.
- **Idempotency:** DDL deployments must be idempotent using `CREATE OR REPLACE FUNCTION`. Re-applying the DDL definition of the identical version is completely safe and non-disruptive to running workloads.

### 4.2 Environment Distribution Strategy

To support multi-environment provisioning (development, CI, staging, and production):

1. **Shared Ecosystem Databases (Dev / Staging / Production):**
   - The authoritative `public.unaccent_grocery_tracker` DDL is applied once to schema `public` via migration runner or administrative script.
   - Downstream consumers rely on `public.unaccent_grocery_tracker` already being present in `public` before applying their own migrations.

2. **Isolated Consumer Test & CI Environments:**
   - Consumers provisioning ephemeral test databases may vendor the standalone `public.unaccent_grocery_tracker` DDL snippet (or execute `migrations/0011_unaccent_grocery_tracker.sql` DDL for `public.unaccent_grocery_tracker`) during their test database bootstrap phase prior to consumer schema creation.
   - Since `CREATE OR REPLACE` is idempotent, executing the function creation in consumer CI does not collide with shared environments.

3. **Schema Isolation Notice:**
   - The adopted handover asset `migrations/0011_unaccent_grocery_tracker.sql` historically combined `public.unaccent_grocery_tracker` and `retail.norm`. Target environment provisioning must execute only the `public.unaccent_grocery_tracker` statement when provisioning shared or foreign environments, avoiding cross-schema mutation of `retail.*`.

---

## 5. Consumer Registry

Consumers of `public.unaccent_grocery_tracker(text)` are formally registered with `common`.

| Consumer Repository | Usage Context | Stored / Indexed Data | Registered Since | Status |
|---|---|---|---|---|
| `retail-prices-ingest` | Used in immutable function `retail.norm(text)` | Stored in `retail.product_version.name_norm` and indexed via pg_trgm GIN | 2026-11-03 | Active |
| `canonical-products` | Used in immutable function `canonical_product.norm(text)` | Stored in `canonical_product` generated search columns and pg_trgm GIN index | 2026-11-04 | Active |
| `retail-receipts-import` | Planned use in text normalization of receipt data | Not yet stored | 2026-11-09 | Active |
| `taxonomy` | Planned use in text normalization of category and label text | Not yet stored | 2026-11-09 | Active |

### Registration Process

New consumer applications or services within the ecosystem must register before using `public.unaccent_grocery_tracker(text)` in persistent storage or indexes:
1. Submit a registration pull request or intake note to `common/docs/handovers/` specifying the consuming service name, repository path, intended usage, and affected database objects.
2. The `common` custodian registers the service in the table above and publishes an updated contract release.

---

## 6. Change Request Procedure

Consumers must never modify the function definition, generator script, or character replacement mapping independently.

To propose a modification (e.g. requesting additional character transliterations or an upgraded baseline):
1. **Submit Request:** Author a request document in the consumer repository under `docs/handovers/request-unaccent-grocery-tracker-<topic>.md` stating:
   - Specific proposed behavior change.
   - Technical and business rationale.
   - Impact assessment on stored data and indexes.
   - Required timeline or deadline.
2. **Deliver to Owner:** Forward the request document to the `common` maintainers via `common/docs/handovers/`.
3. **Owner Evaluation:** `common` evaluates the request and responds with either:
   - An accepted proposal scheduling a new contract version (under SemVer rules in Section 3), or
   - A written refusal detailing technical constraints.
4. **Implementation:** Downstream consumers make zero code or schema adjustments until a new contract version is officially published by `common` and vendored by the consumer.

---

## 7. Conformance Verification

To guarantee continuous adherence to this contract, `common` maintains an automated 8-check conformance test suite (`tests/test_unaccent_grocery_tracker.py`):

1. **Complete Code Point Parity:** Evaluates all 1,112,063 non-surrogate code points against PostgreSQL 18.6 `unaccent` dictionary output in a single-pass query, verifying exactly 2,661 changed characters and 0 mismatches.
2. **Stress & Edge-Case Parity:** Evaluates 3,000 multi-character combinations, Croatian/German special characters, and combining marks against `unaccent` output with 0 mismatches.
3. **Strictness & Null Handling:** Verifies `NULL` -> `NULL` and `''` -> `''`.
4. **Catalog Attributes:** Asserts `provolatile = 'i'`, `proparallel = 's'`, and `proisstrict = true` in `pg_proc`.
5. **Zero Dependency & Search Path Independence:** Verifies absence of `unaccent` tokens in function source, 0 `pg_depend` extension dependencies, and successful execution under `SET LOCAL search_path = ''`.
6. **Stored Generated Column Compatibility:** Verifies table creation and data insertion with stored generated columns using the function in isolated temporary tables under `SET LOCAL search_path = ''` without accessing the `unaccent` extension.
7. **DDL Idempotency:** Verifies that applying the extracted `public.unaccent_grocery_tracker` DDL repeatedly on existing or blank database states produces identical function definitions in `pg_proc` without permission errors.
8. **Normalization Parity:** Verifies deterministic output matching against reference normalization pipelines on real-world grocery product names using temporary helpers in `pg_temp`.
