# Contract: `public.dimensions`, `public.units`, `public.dimension_text`, `public.unit_text`

- **Contract Version:** `v1.0.1`
- **Status:** `Active`
- **Release Date:** 2026-11-06
- **Owner:** `common`
- **Managing Project:** `common`
- **Target Database Schema:** `public`
- **Target Tables:** `public.dimensions`, `public.units`, `public.dimension_text`, `public.unit_text`
- **Reference DDL:** `migrations/0023_units_dimensions.sql` (tables), `migrations/0024_units_catalog_seed.sql` (catalog), `migrations/0025_grant_units_dimensions.sql` (grants for `taxonomy`), `migrations/0026_grant_canonical_units_dimensions.sql` (grants for `canonical-products`)
- **Fixture:** `tests/fixtures/contracts/units_dimensions.sql`
- **Test Suite:** `tests/contracts/test_units_dimensions_contract.py` (fixture equals the catalog built by migrations 0023 + 0024), `tests/test_migration_0024_units_catalog_seed.py` (catalog invariants), `tests/test_migration_0025_grant_units_dimensions.py` (grants for `taxonomy`), `tests/test_migration_0026_grant_canonical_units_dimensions.py` (grants for `canonical-products`)

- **Last Reconciled:** 2026-11-06 -- migrations 0023, 0024, 0025, and 0026 applied to the shared development database and read back: four tables in `public`, owner `common_developer`, row counts 9, 12, 27, 36, and the grants of Section 4.2. `canonical_developer` and `canonical_test` hold `SELECT` only on the four tables and `USAGE` on `public` (0026, read back 2026-11-06 from the live ACLs). The `taxonomy` role grants (0025) were read back in the earlier reconciliation and not re-read for v1.0.1. No consumer role holds a write privilege. Columns and constraints were not re-read from the live catalog; they are covered by the migration tests.
- **Changes in v1.0.1 (PATCH):** `canonical-products` is registered as Active and its roles receive the read grants of Section 4.2. Tables, rows, fixture, and catalog are unchanged.

---

## 1. Scope & Purpose

This contract defines the normative specification, versioning rules, provisioning guidelines, consumer registry, and change management procedures for the shared catalog of dimensions and units of measure: groups of units that convert into each other, units with an exact conversion factor to the base unit of their dimension, and their names and symbols per language.

The catalog is 9 dimensions and 12 units, with `en`, `ru`, and `hr` names for every row and `en`, `ru`, and `hr` symbols for every unit except `one`. It was created in `taxonomy` and is handed over to `common`, which is the managing project from contract version 1.0.0 onward.

### Architectural Invariants

1. **Foreign-Key Target:** `public.dimensions(dimension_code)` is a permanent foreign-key target. Consumers **may** reference it by foreign key from any schema of the same database. The primary key is never changed, renamed, or reassigned.
2. **No Foreign Key on Language:** `language_code` in the two text tables has no foreign key. Language codes are validated by format only: `language_code ~ '^[a-z]{2,3}$'`. `public` provides language codes by convention, not by a language table.
3. **Read-Only After Seeding:** Migration 0024 seeds the empty tables. No consumer inserts, updates, deletes, or alters rows. Rows change only through a published contract release by `common` (Section 3).
4. **Exact Arithmetic:** `factor_to_base` is `numeric`, never a float.

---

## 2. Specification (v1.0.0)

### 2.1 Identity & Ownership

- **Schema:** `public`
- **Tables:** `public.dimensions`, `public.units`, `public.dimension_text`, `public.unit_text`
- **Managing Project:** `common`. It owns every change to the four tables, their fixture, and this contract.
- **Table Owner Role:** the role that applies migrations 0023, 0024, 0025, and 0026. On the shared development database it is `common_developer` (observed 2026-11-06), not `postgres`, which owns the other `public` reference tables. The owner role does not change once set.
- All foreign keys use the default `ON DELETE NO ACTION`. No function, view, or trigger touches these tables.

### 2.2 Column Specifications & Constraints

#### `public.dimensions`

| Column Name | PostgreSQL Type | Nullable | Key | Constraints & Rules |
|---|---|---|---|---|
| `dimension_code` | `text` | `NO` | Primary key (`dimensions_pkey`) | For example `mass`. Permanent. |

#### `public.units`

| Column Name | PostgreSQL Type | Nullable | Key | Constraints & Rules |
|---|---|---|---|---|
| `unit_code` | `text` | `NO` | Primary key (`units_pkey`) | `unit_code ~ '^[A-Za-z0-9]+$'` (`units_unit_code_check`). Case-sensitive, stored verbatim (`kWh`, `l`, `m3`). Unique ignoring case (index `units_unit_code_ci` on `lower(unit_code)`), so `kWh` and `kwh` cannot coexist. |
| `dimension_code` | `text` | `NO` | Foreign key (`units_dimension_code_fkey`) | References `public.dimensions(dimension_code)`. |
| `factor_to_base` | `numeric` | `NO` | | Multiplier to the base unit: `value_in_base = value * factor_to_base`. `factor_to_base > 0 AND factor_to_base < 'Infinity'::numeric` (`units_factor_to_base_check`; also rejects `NaN`). |
| `is_base_unit` | `boolean` | `NO` | | True for the one base unit of the dimension. `NOT is_base_unit OR factor_to_base = 1` (`units_base_factor_to_base_check`). Exactly one per dimension (unique partial index `units_one_base_per_dimension`). |
| `base_unit_code` | `text` | `NO` | Composite foreign key (`units_base_unit_fkey`) | The base unit of this unit's dimension; a base unit names itself: `is_base_unit = (base_unit_code = unit_code)` (`units_base_flag_check`). |
| `base_is_base` | `boolean` | `YES` | | Generated always as `true`, stored. Exists only so the composite foreign key `(base_unit_code, dimension_code, base_is_base)` can point at base units: a unit's base must exist, be a base, and be in the same dimension. |

Also `units_unit_code_dimension_code_is_base_unit_key`: `UNIQUE (unit_code, dimension_code, is_base_unit)`, the target of the composite foreign key.

#### `public.dimension_text`

| Column Name | PostgreSQL Type | Nullable | Key | Constraints & Rules |
|---|---|---|---|---|
| `dimension_code` | `text` | `NO` | Primary key part 1; foreign key (`dimension_text_dimension_code_fkey`) | References `public.dimensions(dimension_code)`. |
| `language_code` | `text` | `NO` | Primary key part 2 | `language_code ~ '^[a-z]{2,3}$'` (`dimension_text_language_code_check`). No foreign key. |
| `dimension_name` | `text` | `NO` | | Non-blank: `dimension_name ~ '[^[:space:]]'` (`dimension_text_dimension_name_check`). |

Primary key `dimension_text_pkey (dimension_code, language_code)`.

#### `public.unit_text`

| Column Name | PostgreSQL Type | Nullable | Key | Constraints & Rules |
|---|---|---|---|---|
| `unit_code` | `text` | `NO` | Primary key part 1; foreign key (`unit_text_unit_code_fkey`) | References `public.units(unit_code)`. |
| `language_code` | `text` | `NO` | Primary key part 2 | `language_code ~ '^[a-z]{2,3}$'` (`unit_text_language_code_check`). No foreign key. |
| `unit_name` | `text` | `NO` | | Non-blank: `unit_name ~ '[^[:space:]]'` (`unit_text_unit_name_check`). |
| `unit_symbol` | `text` | `YES` | | Short written form (`kg`, `m³`). `NULL` when a unit has none (unit `one`); otherwise non-blank (`unit_text_unit_symbol_check`). |

Primary key `unit_text_pkey (unit_code, language_code)`.

No fallback between languages: a missing translation is a missing row, never another language's text.

### 2.3 Seed Scope

Exactly 9 dimensions, 12 units, 27 `dimension_text` rows, and 36 `unit_text` rows, loaded by `migrations/0024_units_catalog_seed.sql` and exported to `tests/fixtures/contracts/units_dimensions.sql`. The `en` name of a dimension is its code.

#### Units

| `unit_code` | `dimension_code` | `factor_to_base` | `is_base_unit` | `base_unit_code` |
|---|---|---|---|---|
| `kg` | `mass` | 1 | yes | `kg` |
| `g` | `mass` | 0.001 | no | `kg` |
| `l` | `volume` | 1 | yes | `l` |
| `ml` | `volume` | 0.001 | no | `l` |
| `m3` | `volume` | 1000 | no | `l` |
| `m` | `length` | 1 | yes | `m` |
| `m2` | `area` | 1 | yes | `m2` |
| `day` | `time` | 1 | yes | `day` |
| `kWh` | `energy` | 1 | yes | `kWh` |
| `pc` | `count` | 1 | yes | `pc` |
| `set` | `set` | 1 | yes | `set` |
| `one` | `none` | 1 | yes | `one` |

#### Unit names and symbols

| `unit_code` | `en` name | `en` symbol | `ru` name | `ru` symbol | `hr` name | `hr` symbol |
|---|---|---|---|---|---|---|
| `kg` | kilogram | `kg` | килограмм | `кг` | kilogram | `kg` |
| `g` | gram | `g` | грамм | `г` | gram | `g` |
| `l` | litre | `l` | литр | `л` | litra | `l` |
| `ml` | millilitre | `ml` | миллилитр | `мл` | mililitar | `ml` |
| `m3` | cubic metre | `m³` | кубический метр | `м³` | kubni metar | `m³` |
| `m` | metre | `m` | метр | `м` | metar | `m` |
| `m2` | square metre | `m²` | квадратный метр | `м²` | četvorni metar | `m²` |
| `day` | day | `day` | сутки | `сут.` | dan | `dan` |
| `kWh` | kilowatt-hour | `kWh` | киловатт-час | `кВт·ч` | kilovatsat | `kWh` |
| `pc` | single countable item | `pc` | штука | `шт.` | komad | `kom` |
| `set` | group of several items sold or counted as one | `set` | набор | `наб.` | komplet | `kompl.` |
| `one` | dimensionless quantity | none | безразмерная величина | none | bezdimenzijska veličina | none |

#### Dimension names

| `dimension_code` | `en` name | `ru` name | `hr` name |
|---|---|---|---|
| `mass` | mass | масса | masa |
| `volume` | volume | объём | volumen |
| `length` | length | длина | duljina |
| `area` | area | площадь | površina |
| `time` | time | время | vrijeme |
| `energy` | energy | энергия | energija |
| `count` | count | количество | količina |
| `set` | set | набор | komplet |
| `none` | none | безразмерная величина | bezdimenzijska veličina |

### 2.4 Data Rules

Conversion:

- Convert only inside one dimension: `value_to = value_from * factor_from / factor_to`, where each factor is the `factor_to_base` of its unit. Across dimensions conversion is an error, not zero or null.
- `pc` (`count`), `set`, and `one` (`none`) each sit alone in their dimension and never convert to anything.
- `set` is not convertible to `pc`: the content of a set differs per product. Pack composition belongs to product quantity data.
- `one` is for quantities with no physical measure and no countable item (a fee, a ratio, a service per visit); countable items use `pc`. It is not a fallback for a missing unit.
- A non-base unit may have `factor_to_base = 1` (an alias). Only `is_base_unit` marks the base.
- `month` and `year` are absent on purpose: their length in days is not constant. If needed, they are added in a separate dimension, never in `time`.

Invariants:

- Every dimension has exactly one unit with `is_base_unit = true`; its `factor_to_base` is 1.
- Every unit's `base_unit_code` is the base unit of its own dimension.
- `factor_to_base` is finite and greater than zero.
- Every dimension and unit has a non-blank `en`, `ru`, and `hr` name.
- A dimension's base unit and the `factor_to_base` of an existing unit are never changed once data refers to them; that would rescale stored quantities silently.

Extension:

- A new unit in an existing dimension needs a `public.units` row (factor, base) and its names and symbols in `public.unit_text`.
- A new dimension needs a `public.dimensions` row, a self-referencing base unit with `factor_to_base = 1`, and its names in `public.dimension_text`, all in one change.
- Adding a unit, a dimension, or a language is a decision of `common` and a contract release (Section 3).

---

## 3. Semantic Versioning & Compatibility

This contract adheres to Semantic Versioning (`MAJOR.MINOR.PATCH`):

- **PATCH:** Documentation clarifications, test suite expansions, or non-functional DDL comments. Zero change to table shape or rows.
- **MINOR:** Backward-compatible changes that existing foreign keys survive unchanged: adding a unit, a dimension, or a language's names and symbols; correcting a name or a symbol of an existing row. Codes, factors, and base units of existing rows are never changed. Fixture, conformance test (including row counts), and this contract are updated in the same commit.
- **MAJOR:** Any breaking change:
  - Dropping, renaming, or retyping a column.
  - Tightening nullability or a constraint so that existing rows or referencing rows are rejected.
  - Changing a primary key, a base unit, or a conversion factor.
  - Removing or renumbering a row, which is allowed only for a row no registered consumer references.
  - A major version never mutates the deployed tables in place; it is released as distinct versioned relations deployed side-by-side while any registered consumer depends on the old ones.

### Lifecycle Invariants

While any registered consumer depends on this contract:
1. **Primary Key Immutability:** A `dimension_code` and a `unit_code` are permanent and never reused for another meaning.
2. **Non-Deletion:** A row referenced by a registered consumer is never deleted or renumbered.
3. **Table Identity:** The four tables are never dropped, renamed, or relocated to another schema.

---

## 4. Provisioning Guidelines

### 4.1 Deployment Model

- **Migrations:** `migrations/0023_units_dimensions.sql` creates the four empty tables; `migrations/0024_units_catalog_seed.sql` seeds the catalog and requires 0023. Neither contains `GRANT` statements; `migrations/0025_grant_units_dimensions.sql` grants the privileges of Section 4.2 to the `taxonomy` roles and `migrations/0026_grant_canonical_units_dimensions.sql` to the `canonical-products` roles; both require 0023. 0025 and 0026 are idempotent and skip a role absent from the database.
- **Caller:** The caller manages the transaction context (`psql -1`, or a test transaction).
- **Isolated Consumer Test & CI Environments:** Consumers vendor `migrations/0023_units_dimensions.sql` during test bootstrap to obtain the empty tables, then load `tests/fixtures/contracts/units_dimensions.sql`. The fixture is data only (`INSERT INTO public.` statements in foreign-key order), equals the catalog of migration 0024 row for row, and must be loaded into empty tables.
- **Migration Order for Taxonomy:** The tables must exist and be filled in `public` (migrations 0023, then 0024, then 0025 for the grants) before taxonomy drops its own copies. Dimension codes are carried over unchanged, so existing `ecoicop_node_dimension` rows stay valid.

### 4.2 Privileges

Required grants, by consumer:

| Consumer | Roles | Object | Privilege |
|---|---|---|---|
| `taxonomy` | `rri_dev_developer`, `taxonomy_test` | schema `public` | `USAGE` |
| `taxonomy` | `rri_dev_developer`, `taxonomy_test` | `public.dimensions`, `public.units`, `public.dimension_text`, `public.unit_text` | `REFERENCES`, `SELECT` |
| `canonical-products` | `canonical_developer`, `canonical_test` | schema `public` | `USAGE` |
| `canonical-products` | `canonical_developer`, `canonical_test` | `public.dimensions`, `public.units`, `public.dimension_text`, `public.unit_text` | `SELECT` |

Source: the `taxonomy` grants are issued by `migrations/0025_grant_units_dimensions.sql` and tested in a rolled-back transaction by `tests/test_migration_0025_grant_units_dimensions.py`; the `canonical-products` grants by `migrations/0026_grant_canonical_units_dimensions.sql` and `tests/test_migration_0026_grant_canonical_units_dimensions.py`. All were applied to the shared development database and read back from the live catalog on 2026-11-06 (see `Last Reconciled`); each role holds `USAGE` on `public`. `canonical-products` receives no `REFERENCES`: it declares no foreign key, and a later foreign key needs its own request (Section 5). Consumer roles receive no `INSERT`, `UPDATE`, or `DELETE`. A fresh database built from migrations 0023 and 0024 alone carries no grants; consumers must not assume them on a database they provision themselves.

---

## 5. Consumer Registry

Consumers of these tables are formally registered with `common`.

| Consumer Repository | Usage Context | Referencing Objects | Registered Since | Status |
|---|---|---|---|---|
| `taxonomy` | Foreign-key target of leaf-category dimensions; reads names and symbols; converts quantities with `factor_to_base` | `ecoicop_node_dimension.dimension_code` -> `public.dimensions(dimension_code)`; tooling: `tools/export_catalog.py` (catalog export to the operator workbook), `tools/interactive_search.py` (search and annotation tool), `tools/load_seeds.py` (leaf dimension seed loader) | 2026-11-06 | Active |
| `canonical-products` | Reads unit codes, dimensions, `factor_to_base`, and symbols for its pack-size and base-unit rules and pack labels, with roles `canonical_developer` and `canonical_test` (schema `canonical_product`) | None; no foreign key declared | 2026-11-06 | Active |
| `retail-prices-ingest` | Candidate reader of units and symbols; no usage defined yet | None yet; no foreign key declared | 2026-11-06 | Registered, no grants |
| `retail-receipts-import` | Planned reader of unit codes, dimensions, `factor_to_base` and symbols; no usage defined yet | None yet; no foreign key declared | 2026-11-09 | Active |

Taxonomy keeps `ecoicop_node_dimension` and its leaf-only trigger; only the four tables move to `common`. After the move, taxonomy's vendored copy of this contract replaces its own definitions and drift test, and taxonomy tests use the fixture instead of holding unit data of their own.

`canonical-products` is Active from v1.0.1 with the read grants of Section 4.2 and no referencing objects. `retail-prices-ingest` is a registry entry only: no privilege has been issued to any of its roles; they are added to `migrations/` and Section 4.2 in a later release once it declares its referencing objects and required privileges (Registration Process, step 1). Neither consumer may declare a foreign key to `public.dimensions` before its own request is accepted.

### Registration Process

New consumers must register before declaring a foreign key to `public.dimensions` or reading the tables:
1. Submit an intake note to `common/docs/handovers/` naming the consuming service, repository path, referencing objects, and required privileges (`USAGE` on `public`, `SELECT`, `REFERENCES`).
2. The `common` custodian registers the consumer in the table above, applies the grants for the environment, and publishes an updated contract release.

---

## 6. Change Request Procedure

The managing project `common` owns every change after handover. Consumers must never alter the tables, their constraints, or their rows directly.

1. **Submit Request:** Author a request in the consumer repository under `docs/handovers/request-units-dimensions-<topic>.md` stating the proposed change, rationale, impact on referencing objects, and timeline, and forward it to `common/docs/handovers/`.
2. **Announce Breaking Changes:** Every MAJOR change under Section 3 is announced to the `taxonomy` owner before deployment.
3. **One Commit:** The contract, the fixture, and the regression test are updated in one commit, before the change goes live.
4. **Version Bump:** Every change bumps `Contract Version` under the rules in Section 3.
5. **Reconciliation:** Every reconciliation against the live catalog (columns, constraints, row counts, owner, grants, and foreign-key dependents) sets `Last Reconciled`.
6. **Implementation:** Consumers make no code or schema adjustments until the new version is published by `common`.

---

## 7. Conformance Verification

`common` maintains automated checks against PostgreSQL 18.6:

1. **Fixture Conformance (`tests/contracts/test_units_dimensions_contract.py`):** Applies migrations 0023 and 0024 in `pg_temp`, empties the tables, loads the fixture, and verifies that all four tables equal the migration catalog row for row (9, 12, 27, 36 rows). Verifies that the fixture is data only, and that this document names the four tables, every column, and every fixture code and symbol.
2. **Catalog Invariants (`tests/test_migration_0024_units_catalog_seed.py`):** Verifies the exact catalog, one base per dimension, factor domain, names and symbols, and that the seed is plain DML.
3. **Grants (`tests/test_migration_0025_grant_units_dimensions.py`, `tests/test_migration_0026_grant_canonical_units_dimensions.py`):** Apply the grant migrations twice and verify the privileges of Section 4.2, the absence of `REFERENCES` (0026) and of `INSERT`, `UPDATE`, `DELETE`, and `TRUNCATE`, and the skip of an absent role.

The tests write only to `pg_temp` inside a rolled-back transaction and never touch `public`. The live read-back of 2026-11-06 was a one-time manual reconciliation; there is no automated live conformance test against the deployed tables yet.
