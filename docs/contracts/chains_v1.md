# Consumer contract `chains_v1`

| | |
| --- | --- |
| Version | 1.2.0 |
| Kind | Consumer contract: this project states what it needs; `common` provides it |
| Provider | `grocery-tracker/common`, which owns the `chains` table, its DDL, migrations and seed data |
| Consumer | `retail-receipts-import`, read-only |
| Reference DDL and rows | [`chains_v1.sql`](chains_v1.sql), a reference copy for provisioning and tests |

The service learns the known retail chains from a shared reference in PostgreSQL. It never
creates or writes the reference, and no receipt table has a foreign key to it. The table is
shared with other projects, so its schema is owned and migrated by `common`; this project only
states the shape it reads.

## Object

The service reads the view **`public.chains_v1`** by name, and nothing else: not the table
behind it, not a PostgreSQL enum. `common` may change the table freely as long as the view
keeps this shape.

| Column | Type | Rule |
| --- | --- | --- |
| `chain_id` | `text` | Lowercase ASCII slug matching `^[a-z][a-z0-9_]{0,31}$`. Unique. Stable: never renamed, never reused for another chain. |
| `display_name` | `text` | Non-blank. Shown to people. |
| `aliases` | `text[]` | One-dimensional, no NULL or empty elements; may be an empty array. Names as printed on receipts. |
| `country_code` | `text` | Two uppercase ASCII letters (`^[A-Z]{2}$`), the country the chain row belongs to. Not a foreign key: the service does not check it against any list. |
| `tax_numbers` | `text[]` | The tax identifiers printed on the chain's receipts. May be NULL or an empty array; the two mean the same (a chain without printed identifiers). Otherwise one-dimensional, no NULL, blank or comma-containing elements. When `country_code` is `HR`, every element is exactly 11 decimal digits (OIB); for other countries the format is not constrained further. |
| `active` | `boolean` | `false` withdraws the chain. Rows are deactivated, never deleted. |

No column other than `tax_numbers` may be NULL.

The ids `other` and `unreadable` are reserved for the service's own use and must not appear.

## Privileges

`SELECT` on `public.chains_v1` for the environment's writer role (`rri_dev_writer` on srv22),
plus `USAGE` on schema `public`. The grant is not part of `chains_v1.sql`, because the grantee
differs per deployment.

## What the service does with it

- It returns the `active` rows as known chains, ordered by `chain_id`.
- A row that breaks a rule above (bad slug, reserved id, NULL field other than `tax_numbers`,
  bad aliases, bad country code, bad tax numbers, or a `chain_id` that appears more than once,
  active or not) is skipped and reported as rejected; the valid chains keep working.
- A missing view or column, a missing schema, or a missing `SELECT` is a structural fault.
- While PostgreSQL is unreachable, work that needs the reference waits.
- A chain with NULL or empty `tax_numbers` is not checked against the seller identifier on the
  receipt (the receipt is attributed by the chain's own parser and aliases only); a chain with
  tax numbers is.

## Versioning

Semantic versioning from 1.0.0.

- Adding a column to the view: minor version, same view name.
- Any other change (removing, renaming or retyping a column, changing a rule): normally a new
  view `chains_v2`, published next to `chains_v1` until the service has moved over.
- Version 1.2.0 is the one exception, decided by the owner on 2026-11-03: it changes `chains_v1`
  in place without a new view. It adds `country_code`, replaces `seller_oibs` with the optional
  `tax_numbers`, and moves table ownership to `common`. `common` applies the migration; the
  service must be upgraded together with it, because the old `seller_oibs` column is gone.

## Rows at 1.2.0

| `chain_id` | `display_name` | `aliases` | `country_code` | `tax_numbers` |
| --- | --- | --- | --- | --- |
| `dm` | dm | DM, dm | HR | 94124811986 |
| `kaufland` | Kaufland | KAUFLAND, Kaufland | HR | 47432874968 |
| `lidl` | Lidl | LIDL, Lidl | HR | 66089976432 |
| `mueller` | Müller | MÜLLER, Müller, Muller | HR | 84698789700 |
| `spar` | Spar | SPAR, Spar, INTERSPAR | HR | 46108893754 |

The tax numbers listed are the company OIBs printed on fiscal receipts issued by each chain in
Croatia.
