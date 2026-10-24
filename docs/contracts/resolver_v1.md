# Provider contract `resolver_v1`

| | |
| --- | --- |
| Version | 1.1.0 |
| Kind | Provider contract: this project provides the feed; the Resolver reads it |
| Provider | `retail-receipts-import` (writes receipts and feed, publishes views) |
| Consumer | Resolver, read-only |

The service exposes stored retail grocery receipts and an event feed to the Resolver via
schema-qualified PostgreSQL views. The Resolver connects with a dedicated read-only role that
has access only to these views, never to the internal tables.

## Objects

All objects live in schema **`resolver_v1`**. The Resolver reads only these four views:

- `resolver_v1.feed`
- `resolver_v1.receipts`
- `resolver_v1.receipt_lines`
- `resolver_v1.receipt_settlements`

### `resolver_v1.feed`

The changelog of receipt mutations. Consumers track their progress with a sequence cursor.

| Column | Type | Nullable | Rule |
| --- | --- | --- | --- |
| `seq` | `bigint` | No | Monotonically increasing sequence number. May have gaps. |
| `receipt_id` | `uuid` | No | Unique identifier of the receipt (UUIDv7). |
| `event` | `text` | No | Mutation type: `stored` or `deleted`. |

### `resolver_v1.receipts`

Header information for stored receipts.

| Column | Type | Nullable | Rule |
| --- | --- | --- | --- |
| `receipt_id` | `uuid` | No | Unique identifier of the receipt (UUIDv7). |
| `chain_id` | `text` | No | Lowercase ASCII slug matching `^[a-z][a-z0-9_]{0,31}$`. |
| `store_name` | `text` | Yes | Store name as printed, if printed by the chain. |
| `branch_number` | `text` | Yes | Branch or store number as printed. |
| `receipt_number` | `text` | Yes | Free text invoice/receipt number as printed; format not guaranteed. |
| `store_address` | `text` | Yes | Free text address as printed; format not guaranteed. |
| `currency` | `text` | No | Fixed currency code `EUR`. |
| `purchased_at` | `text` | No | ISO-8601 UTC timestamp formatted with `Z`, e.g. `2026-07-15T12:05:00Z`. |
| `purchased_at_local` | `text` | No | ISO-8601 local wall-clock timestamp with timezone offset (`Europe/Zagreb`), e.g. `2026-07-15T14:05:00+02:00` or `2026-01-15T14:05:00+01:00`. |
| `buyer_name` | `text` | No | Name of the person who submitted the receipt. |
| `total` | `text` | No | Value of goods as a decimal string with 2 decimal places, equal to the sum of the receipt's settlement amounts, deposit refunds included; so it exceeds the amount paid when deposits were refunded. Zero or negative when returns outweigh purchases. |

*Not exposed:* `loyalty_card_number` (may be introduced in a future minor release),
`source_kind`, `source_ref`, `created_at`, and the amount paid.

### `resolver_v1.receipt_lines`

Purchased line items only; see reading rule 3.

| Column | Type | Nullable | Rule |
| --- | --- | --- | --- |
| `line_id` | `uuid` | No | Unique identifier of the line item (UUIDv7). |
| `receipt_id` | `uuid` | No | Reference to `resolver_v1.receipts(receipt_id)`. |
| `line_no` | `integer` | No | 1-based sequential line number within the receipt. |
| `printed_text` | `text` | No | Item name as printed on the receipt. |
| `quantity` | `text` | No | Decimal string with 3 decimal places, e.g. `"1.000"`, `"0.500"`. |
| `unit` | `text` | Yes | Unit of measure as printed (e.g. `kom`, `kg`), if present. |
| `unit_price` | `text` | Yes | Unit price as decimal string with 2 decimal places, if present. |
| `printed_amount` | `text` | No | Subtotal amount as decimal string with 2 decimal places. |
| `included_discount` | `text` | No | Discount included in printed amount, 2 decimal places (>= 0). |
| `separate_discount` | `text` | No | Separate line discount, 2 decimal places (>= 0). |
| `discount_text` | `text` | Yes | Description of discounts or promotions applied. |
| `regular_amount` | `text` | No | Pre-discount price (`printed_amount + included_discount`), 2 decimal places. |
| `effective_amount` | `text` | No | Final line cost (`printed_amount - separate_discount`), 2 decimal places. |

### `resolver_v1.receipt_settlements`

Payment tenders and settlement breakdowns recorded for the receipt.

| Column | Type | Nullable | Rule |
| --- | --- | --- | --- |
| `receipt_id` | `uuid` | No | Reference to `resolver_v1.receipts(receipt_id)`. |
| `settlement_no` | `integer` | No | 1-based sequential settlement index within the receipt. |
| `kind` | `text` | No | One of: `card`, `cash`, `bonus_points`, `coupon`, `deposit_refund`. |
| `printed_text` | `text` | No | Payment description as printed on the receipt. |
| `amount` | `text` | No | Signed amount as decimal string with 2 decimal places. Only `card` and `cash` may be negative (a payout). |

## Reading rules

1. **Feed consumption and cursor:**
   `seq` grows in commit order of the single writer and may have gaps. A new consumer starts
   from cursor `0`. Each receipt has at most one `stored` and one `deleted` event, so an event
   seen twice can be skipped by (`receipt_id`, `event`). Consumers poll for new events using:
   ```sql
   SELECT seq, receipt_id, event
   FROM resolver_v1.feed
   WHERE seq > :cursor
   ORDER BY seq;
   ```
2. **Lifecycle events:**
   - `stored`: the receipt was written to `resolver_v1.receipts` and its related lines and
     settlements tables.
   - `deleted`: a previously stored receipt was deleted. Its rows are no longer present in
     `resolver_v1.receipts`, `resolver_v1.receipt_lines` or `resolver_v1.receipt_settlements`.
3. **Net purchases:**
   `receipt_lines` contains only purchase lines. A storno is netted into the line it cancels,
   and return lines are dropped. The service checks the printed lines, returns included,
   against the settlements, so the sum of `effective_amount` across `receipt_lines` exceeds
   the sum of settlement amounts when the receipt had a return. The header `total` equals the
   sum of the receipt's settlement amounts.
4. **Ordering and deletion:**
   A `stored` event always precedes the `deleted` event of the same receipt. When a receipt is
   absent from `resolver_v1.receipts` for a `stored` event, a `deleted` event for it follows
   in the feed.
5. **Number formatting:**
   All money amounts are formatted as decimal strings with two decimal places (e.g. `"1.50"`,
   `"-3.20"`). Quantities are formatted as decimal strings with three decimal places (e.g. `"1.000"`).
6. **Timezone neutrality:**
   `purchased_at` (UTC `Z`) and `purchased_at_local` (`Europe/Zagreb` wall clock with offset)
   are rendered as static text. Their output is invariant under any client session `TimeZone`
   setting.

## Privileges

The database admin provisions schema `resolver_v1` owned by the schema owner role
(`rri_dev_owner` in dev) and grants access to the Resolver reader role (`resolver_dev_reader` in dev,
or placeholder `<resolver_role>`):

```sql
-- Provisioned by the database admin:
CREATE SCHEMA resolver_v1 AUTHORIZATION <schema_owner>;

GRANT USAGE ON SCHEMA resolver_v1 TO <resolver_role>;
GRANT SELECT ON ALL TABLES IN SCHEMA resolver_v1 TO <resolver_role>;

ALTER DEFAULT PRIVILEGES FOR ROLE <schema_owner> IN SCHEMA resolver_v1
    GRANT SELECT ON TABLES TO <resolver_role>;
```

The Resolver role requires no privileges on `retail_receipts_import` tables or sequences.
The views in `resolver_v1` execute with the default `security_invoker = false`, so queries
succeed without exposing internal tables.

## Versioning

Semantic versioning from 1.0.0.

- **Minor changes (backward-compatible):** Adding columns to views retains
  the schema name `resolver_v1`.
- **Major changes (breaking):** Renaming, removing, or changing the type/semantics of a column,
  or a new value of `event`, settlement `kind` or `currency`, introduces a new schema
  `resolver_v2`, published alongside `resolver_v1` until the consumer completes migration.
- Consumers name the columns they read, never `SELECT *`, so an added column breaks nothing.

### Changes

- **1.1.0**: Added `total` column to `resolver_v1.receipts` (value of goods, equal to the sum of settlement amounts). Minor changes definition updated to adding columns to views.
- **1.0.0**: Initial release of the resolver feed contract.
