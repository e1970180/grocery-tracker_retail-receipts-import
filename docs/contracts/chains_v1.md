# Consumer contract `chains_v1`

| | |
| --- | --- |
| Version | 1.1.0 |
| Kind | Consumer contract: this project states what it needs; the admin provides it |
| Provider | The PostgreSQL admin (a person), who owns and writes the reference |
| Consumer | `retail-receipts-import`, read-only |
| Reference DDL and rows | [`chains_v1.sql`](chains_v1.sql) |

The service learns the known retail chains from an admin-owned reference in PostgreSQL. It
never creates or writes the reference, and no receipt table has a foreign key to it.

## Object

The service reads the view **`public.chains_v1`** by name, and nothing else: not the table
behind it, not a PostgreSQL enum. The admin may change the table freely as long as the view
keeps this shape.

| Column | Type | Rule |
| --- | --- | --- |
| `chain_id` | `text` | Lowercase ASCII slug matching `^[a-z][a-z0-9_]{0,31}$`. Unique. Stable: never renamed, never reused for another chain. |
| `display_name` | `text` | Non-blank. Shown to people. |
| `aliases` | `text[]` | One-dimensional, no NULL or empty elements; may be an empty array. Names as printed on receipts. |
| `seller_oibs` | `text[]` | One-dimensional, no NULL elements, non-empty, every element exactly 11 decimal digits. The OIBs printed on the chain's fiscal receipts. |
| `active` | `boolean` | `false` withdraws the chain. Rows are deactivated, never deleted. |

No column may be NULL.

The ids `other` and `unreadable` are reserved for the service's own use and must not appear.

## Privileges

`SELECT` on `public.chains_v1` for the environment's writer role (`rri_dev_writer` in dev),
plus `USAGE` on schema `public`. The grant is not part of `chains_v1.sql`, because the grantee
differs per environment.

## What the service does with it

- It returns the `active` rows as known chains, ordered by `chain_id`.
- A row that breaks a rule above (bad slug, reserved id, NULL field, bad aliases, bad OIBs, or a
  `chain_id` that appears more than once, active or not) is skipped and reported as rejected;
  the valid chains keep working.
- A missing view or column, a missing schema, or a missing `SELECT` is a structural fault.
- While PostgreSQL is unreachable, work that needs the reference waits.

## Versioning

Semantic versioning from 1.0.0.

- Adding a column to the view: minor version, same view name. Version 1.1.0 added `seller_oibs`
  to the view and table. To bring an existing dev database to 1.1.0, the admin recreates the
  table and view from `chains_v1.sql` 1.1.0 (no separate upgrade script).
- Any other change (removing, renaming or retyping a column, changing a rule): a new view
  `chains_v2`, published next to `chains_v1` until the service has moved over.

## Rows at 1.1.0

| `chain_id` | `display_name` | `aliases` | `seller_oibs` |
| --- | --- | --- | --- |
| `dm` | dm | DM, dm | 94124811986 |
| `kaufland` | Kaufland | KAUFLAND, Kaufland | 47432874968 |
| `lidl` | Lidl | LIDL, Lidl | 66089976432 |
| `mueller` | Müller | MÜLLER, Müller, Muller | 84698789700 |
| `spar` | Spar | SPAR, Spar, INTERSPAR | 46108893754 |

The OIB values are the company OIBs printed on fiscal receipts issued by each chain in Croatia.
