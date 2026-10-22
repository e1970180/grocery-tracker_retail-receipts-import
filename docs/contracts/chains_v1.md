# Consumer contract `chains_v1`

| | |
| --- | --- |
| Version | 1.0.0 |
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
| `active` | `boolean` | `false` withdraws the chain. Rows are deactivated, never deleted. |

No column may be NULL.

The ids `other` and `unreadable` are reserved for the service's own use and must not appear.

## Privileges

`SELECT` on `public.chains_v1` for the environment's writer role (`rri_dev_writer` in dev),
plus `USAGE` on schema `public`. The grant is not part of `chains_v1.sql`, because the grantee
differs per environment.

## What the service does with it

- It returns the `active` rows as known chains, ordered by `chain_id`.
- A row that breaks a rule above (bad slug, reserved id, NULL field, bad aliases, or a
  `chain_id` that appears more than once, active or not) is skipped and reported as rejected;
  the valid chains keep working.
- A missing view or column, a missing schema, or a missing `SELECT` is a structural fault.
- While PostgreSQL is unreachable, work that needs the reference waits.

## Versioning

Semantic versioning from 1.0.0.

- Adding a column to the view: minor version, same view name.
- Any other change (removing, renaming or retyping a column, changing a rule): a new view
  `chains_v2`, published next to `chains_v1` until the service has moved over.

## Rows at 1.0.0

| `chain_id` | `display_name` | `aliases` |
| --- | --- | --- |
| `dm` | dm | DM, dm |
| `kaufland` | Kaufland | KAUFLAND, Kaufland |
| `lidl` | Lidl | LIDL, Lidl |
| `mueller` | Müller | MÜLLER, Müller, Muller |
| `spar` | Spar | SPAR, Spar, INTERSPAR |
