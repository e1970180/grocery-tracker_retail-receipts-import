# Provider contract `receipt_feed_v1`

| | |
| --- | --- |
| Version | 1.2.0 |
| Kind | Provider contract: this project provides the feed; the Resolver reads it |
| Provider | `retail-receipts-import` (writes receipts and feed, publishes views) |
| Consumers | Resolver, read-only; `canonical-products`, read-only, uses `item_key` of `resolver_v1.receipt_lines` to link lines to canonical products |

The service exposes stored retail grocery receipts and an event feed to the Resolver via
schema-qualified PostgreSQL views. The Resolver connects with a dedicated read-only role that
has access only to these views, never to the internal tables.

## Objects

All objects live in schema **`resolver_v1`**; the schema keeps its original name, only the
contract is called `receipt_feed_v1`. The Resolver reads only these four views:

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
| `total` | `text` | No | Value of goods as a decimal string with 2 decimal places, equal to the sum of the receipt's settlement amounts of every kind; so it exceeds the amount paid when coupons, bonus points or deposit refunds settled part of it. Zero or negative when returns outweigh purchases. |

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
| `item_key` | `uuid` | No | Deterministic item key (UUIDv5) from the receipt's `chain_id` and the line's `printed_text`; see [Item key](#item-key). Kept as `uuid` like the other identifiers; only numbers are rendered as text. |

### Item key

`item_key` identifies an item as the receipt side sees it: lines with equal `item_key` carry the
same item, within one chain, whatever receipt they come from, so one link made by a consumer
applies to every line carrying that key. Different chains always give different keys. The
database computes the key on every insert and on every change of `printed_text`; historical
lines carry it too. It identifies the printed item text, not a product catalogue entry: the
same product printed differently gives different keys.

**Construction.** `item_key = UUIDv5(namespace, name)` (RFC 9562, SHA-1 based):

- `namespace` is the RFC 9562 `NAMESPACE_URL`, `6ba7b811-9dad-11d1-80b4-00c04fd430c8`.
- `name` is the UTF-8 encoding of `chain_id || ':' || sanitize_text(unaccent_grocery_tracker(printed_text))`:
  1. `public.unaccent_grocery_tracker(text)`, contract `v1.0.0` (owner `common`), transliterates
     accented and special characters (`Č` -> `C`, `ß` -> `ss`).
  2. `public.sanitize_text(text)`, contract `v1.0.0` (owner `common`), applied to the result of
     step 1, removes invisible characters, turns whitespace and control characters into spaces,
     collapses runs of spaces and trims both ends.
  3. The receipt's `chain_id`, one ASCII colon `:` (U+003A), then the result of step 2. A
     `chain_id` never contains `:`.
- Case is not changed: `Žličica` and `ŽLIČICA` give different keys.

The database function `retail_receipts_import.item_key(chain text, printed_text text)` computes
it. Consumers read the stored column and are not granted the function; the SQL below
reproduces it wherever the two shared routines and `uuid-ossp` are installed:

```sql
SELECT public.uuid_generate_v5(
    '6ba7b811-9dad-11d1-80b4-00c04fd430c8'::uuid,
    :chain_id || ':' || public.sanitize_text(public.unaccent_grocery_tracker(:printed_text))
);
```

Python reproduces the UUID from a final name. This project provides no Python port of the two
routines: a consumer computing names outside PostgreSQL needs behaviour equal to their
contracts, and checks it against the final names below.

```python
import uuid

def item_key(chain_id: str, normalized_text: str) -> uuid.UUID:
    """`normalized_text` is sanitize_text(unaccent_grocery_tracker(printed_text))."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{chain_id}:{normalized_text}")
```

**Test vectors.** Strings are Python string literals; non-ASCII letters are precomposed (NFC),
and the hex column gives the exact UTF-8 bytes of the name fed to UUIDv5.

`uuid_generate_v5` itself (RFC 9562 published values, and a UTF-8 check over a raw, not
normalized, name):

| Namespace | Name | Name UTF-8 hex | UUID |
| --- | --- | --- | --- |
| DNS | `"www.example.com"` | | `2ed6657d-e927-568b-95e1-2665a8aea6a2` |
| URL | `"http://python.org/"` | | `4c565f0d-3f5a-5890-b41b-20cf47701c5e` |
| URL | `"spar:Čaj zeleni 0,5l ß"` | `737061723ac48c616a207a656c656e6920302c356c20c39f` | `165b574d-f4c8-528e-b1a8-7b8651ade646` |

`item_key`:

| `chain_id` | `printed_text` | Final name | Name UTF-8 hex | `item_key` |
| --- | --- | --- | --- | --- |
| `"spar"` | `"Čaj  zeleni 0,5l ß"` | `"spar:Caj zeleni 0,5l ss"` | `737061723a43616a207a656c656e6920302c356c207373` | `f8b02898-1bae-5aba-82b3-b18527e6c93c` |
| `"kaufland"` | `"MLIJEKO 2,8% 1L"` | `"kaufland:MLIJEKO 2,8% 1L"` | `6b6175666c616e643a4d4c494a454b4f20322c382520314c` | `529c0b4c-0a9e-5c2c-afb4-25f11ea018e8` |
| `"lidl"` | `"  Jogurt​ voćni\t150g "` | `"lidl:Jogurt vocni 150g"` | `6c69646c3a4a6f6775727420766f636e692031353067` | `a9189539-4c4e-57f6-91af-20ae2f1753ee` |
| `"dm"` | `"Žličica"` | `"dm:Zlicica"` | `646d3a5a6c6963696361` | `26f8975f-52f9-5819-9103-a13e8ae3c591` |
| `"dm"` | `"ŽLIČICA"` | `"dm:ZLICICA"` | `646d3a5a4c4943494341` | `7881c082-cb8c-5b31-a584-28942ee26c99` |

**Stability.** The construction above is frozen for this contract. Consumers may store
`item_key` and key their own records by it. Any change that alters a key value for any input
(namespace, name construction, a new version of either shared routine) is a breaking change:
it ships as a new contract major version with a new database function (`item_key_v2`), is
announced in advance, and leaves `item_key` as published until consumers have migrated. No
old-to-new key mapping is provided; a consumer re-links from `printed_text` and `chain_id`,
both published in the same views.

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
(`rri_dev_owner` on srv22) and grants access to the Resolver reader role (`resolver_dev_reader` on srv22,
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

- **1.2.0**: Added `item_key` column to `resolver_v1.receipt_lines` (deterministic UUIDv5 item key) and the Item key section with its construction, test vectors and stability rule. `canonical-products` is registered as a reader of `item_key`.
- **1.1.0**: Added `total` column to `resolver_v1.receipts` (value of goods, equal to the sum of settlement amounts). Minor changes definition updated to adding columns to views.
- **1.0.0**: Initial release of the resolver feed contract.
