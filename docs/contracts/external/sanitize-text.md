# Contract: `public.sanitize_text(text)`

- **Contract Version:** `v1.0.0`
- **Status:** `Active`
- **Release Date:** 2026-11-06
- **Owner:** `common`
- **Target Database Schema:** `public`
- **Reference DDL:** `migrations/0012_sanitize_text.sql`
- **Test Suite:** `tests/test_sanitize_text.py`

---

## 1. Scope & Purpose

This contract defines the normative specification, immutability guarantees, behavioral rules, provisioning guidelines, and change management procedures for the shared database routine `public.sanitize_text(text)`.

The routine removes invisible characters, turns every whitespace and control character into an ASCII space, collapses runs of spaces, and trims both ends. It is designed for use in immutable normalization functions, generated stored columns, and indexes across the grocery-tracker ecosystem, so that consumers do not duplicate sanitization logic.

Out of scope: case conversion (belongs to consumer normalization such as `retail.norm`), transliteration or unaccenting (`public.unaccent_grocery_tracker`), Unicode normalization (NFC/NFKC), and cross-script look-alike replacement.

---

## 2. Specification (v1.0.0)

### 2.1 Identity & Signature

- **Function Signature:** `public.sanitize_text(t text) RETURNS text`
- **Language:** `sql`
- **Volatility:** `IMMUTABLE` (`provolatile = 'i'` in `pg_proc`)
- **Parallel Safety:** `PARALLEL SAFE` (`proparallel = 's'` in `pg_proc`)
- **Strictness:** `STRICT` (`proisstrict = true` in `pg_proc`)
- **Null & Empty Behavior:**
  - `public.sanitize_text(NULL)` returns `NULL`
  - `public.sanitize_text('')` returns `''`
- **Zero External Dependencies:**
  - The body uses only `pg_catalog` builtins (`translate`, `regexp_replace`, `btrim`), always schema-qualified, over literal code points.
  - It has no dependency on extensions, tables, locale-dependent character classes (`\s`, `[[:space:]]`), or configuration settings.
  - It executes deterministically under any `search_path`, including `search_path = ''`.

### 2.2 Processing Order

For input `t`, in this order:

1. **Remove** every code point of the invisible set (2.3.1). No space is inserted.
2. **Replace** every code point of the whitespace set (2.3.2) and the other control set (2.3.3) with one ASCII space (U+0020).
3. **Collapse** every run of two or more ASCII spaces into one (literal-space pattern only).
4. **Trim** ASCII spaces at both ends.

All other characters, including case and accents, are returned unchanged. Input made only of characters from the three sets yields `''`. The function is idempotent: `sanitize_text(sanitize_text(x)) = sanitize_text(x)`.

### 2.3 Frozen Code Point Sets

U+0000 cannot occur in PostgreSQL `text` and is not listed. Surrogates (U+D800..U+DFFF) are not valid characters and are not classified.

#### 2.3.1 Invisible set (21 code points, removed)

U+00AD, U+180E, U+200B-U+200F, U+202A-U+202E, U+2060, U+2062-U+2064, U+2066-U+2069, U+FEFF.

#### 2.3.2 Whitespace set (25 code points, replaced by a space)

U+0009-U+000D, U+0020, U+0085, U+00A0, U+1680, U+2000-U+200A, U+2028, U+2029, U+202F, U+205F, U+3000.

#### 2.3.3 Other control set (58 code points, replaced by a space)

U+0001-U+0008, U+000E-U+001F, U+007F, U+0080-U+009F except U+0085.

#### 2.3.4 Freeze Guarantee

The three sets and the processing order are permanently frozen for major version 1. The 104 listed code points are removed or replaced; every other code point passes through unchanged.

---

## 3. Semantic Versioning & Compatibility

This contract adheres to Semantic Versioning (`MAJOR.MINOR.PATCH`):

- **PATCH:** Documentation clarifications, test additions, tooling changes. Zero change to SQL logic, signature, or the code point sets.
- **MINOR:** Backward-compatible additions that change the output for no input. Given the frozen sets, minor versions are not anticipated.
- **MAJOR:** Any change to a code point set, the processing order, or the output for any input.
  - A major version **never modifies the existing function in place**.
  - It is released as a distinct function with a version suffix (e.g. `public.sanitize_text_v2(text)`).
  - `public.sanitize_text` stays deployed, immutable and unmodified as long as any registered consumer depends on it.
  - Consumers migrate on their own schedule and rebuild stored columns and indexes at their discretion.

### Lifecycle Invariants

While any registered consumer exists:
1. `public.sanitize_text(text)` will **never** be edited in place.
2. The function will **never** be dropped, renamed, or relocated to another schema.
3. `IMMUTABLE`, `PARALLEL SAFE` and `STRICT` will **never** be altered.

---

## 4. Provisioning Guidelines

### 4.1 Deployment Model & Privilege Requirements

- **Target Object:** The function lives strictly in schema `public`.
- **Privileges:** The role applying DDL needs `CREATE` on schema `public`. Default `EXECUTE` granted to `PUBLIC` must not be revoked; the migration contains no `GRANT`.
- **Idempotency:** DDL uses `CREATE OR REPLACE FUNCTION`; re-applying the identical version is safe.

### 4.2 Environment Distribution Strategy

1. **Shared Ecosystem Databases:** `migrations/0012_sanitize_text.sql` is applied once to schema `public`. Consumers rely on the function already being present before applying their own migrations. Deployed to the shared database on 2026-11-06.
2. **Isolated Consumer Test & CI Environments:** Consumers may vendor the DDL from `migrations/0012_sanitize_text.sql` into their ephemeral test database bootstrap, before creating consumer schemas. `CREATE OR REPLACE` makes this safe.
3. **Schema Isolation:** The migration touches only `public.sanitize_text`. Never mutate `retail.*` or any sibling schema from it.

---

## 5. Consumer Registry

| Consumer Repository | Usage Context | Stored / Indexed Data | Registered Since | Status |
|---|---|---|---|---|
| `canonical-products` | Planned use in its normalization function and search columns | Not yet stored | 2026-11-06 | Active |
| `retail-prices-ingest` | Planned use in `retail.norm(text)` input cleaning | Not yet stored | 2026-11-06 | Active |
| `retail-receipts-import` | Planned cleaning of receipt line text | Not yet stored | 2026-11-06 | Active |
| `taxonomy` | Planned cleaning of category and label text | Not yet stored | 2026-11-06 | Active |

### Registration Process

New consumers must register before using the function in persistent storage or indexes:
1. Submit an intake note to `common/docs/handovers/` naming the service, repository path, intended usage, and affected database objects.
2. The `common` custodian adds the service to the table above and publishes an updated contract release.

---

## 6. Change Request Procedure

Consumers must never modify the function definition or the code point sets independently.

To propose a change:
1. **Submit Request:** Write `docs/handovers/request-sanitize-text-<topic>.md` in the consumer repository stating the proposed behavior change, rationale, impact on stored data and indexes, and required timeline.
2. **Deliver to Owner:** Forward it to `common` via `common/docs/handovers/`.
3. **Owner Evaluation:** `common` either accepts it and schedules a new contract version under Section 3 (a new versioned function), or refuses it in writing.
4. **Implementation:** Consumers make no change until a new contract version is published by `common` and vendored.

---

## 7. Conformance Verification

`common` maintains a conformance suite (`tests/test_sanitize_text.py`), run against live PostgreSQL 18.6 inside rolled-back transactions:

1. **Catalog Attributes:** `provolatile = 'i'`, `proparallel = 's'`, `proisstrict = true`.
2. **Null & Empty Handling:** `NULL` -> `NULL`, `''` -> `''`.
3. **Mixed Sample:** tabs, NBSP, zero-width and control characters around words give single-spaced, trimmed output.
4. **Junk-Only Input:** input made only of set members yields `''`.
5. **Invisible Removal:** removal inserts no space (`'a' || U+200B || 'b'` -> `'ab'`).
6. **Case Preserved:** `'ČaJ'` -> `'ČaJ'`.
7. **DDL Idempotency:** applying the migration twice leaves one function with identical attributes and source.
8. **Search Path Independence:** the function works under `SET LOCAL search_path = ''`.
9. **Reference Table Shape:** the independently written reference sets have 21, 25 and 58 members.
10. **Full Code Point Sweep:** every non-surrogate code point (except U+0000) is classified against the reference table with 0 mismatches; lone set members give `''`.
11. **Generated Strings:** seeded random strings match the model and are idempotent.
12. **Generated Column & Index:** use in a stored generated column and an expression index under an empty `search_path`.
13. **Performance:** a 100 KB mixed sample is processed and its timing recorded.
