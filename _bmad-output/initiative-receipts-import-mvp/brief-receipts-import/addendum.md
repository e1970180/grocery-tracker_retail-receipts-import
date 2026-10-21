# Addendum: retail-receipts-import brief

This addendum holds detail that belongs in the PRD, architecture, or chain prompts rather than in the brief. Sources are the non-normative files in `doc-inbox/`. Everything here is reference material, not a decision.

## Chain-specific knowledge (legacy)

### Kaufland

- **Branch.** The branch ID comes from `PJ####` in the header and must match the middle segment of the receipt number (`NNNNN/BBBB/X`).
- **Date and time.** The date comes from the porezna.gov.hr fiscal URL (`datv=YYYYMMDD_HHMM`). The time, with seconds, comes from the fiscal line `Datum: DD.MM.YY Vrijeme HH:MM:SS`.
- **Bank-terminal date.** Never read it. It uses `YY/MM/DD`, so `26/02/05` means 5 Feb 2026.
- **Lines to ignore.** Ignore the subtotal lines `Međusuma` / `Suma`. Also ignore the `Povratna naknada` bookkeeping lines inside items.
- **Discounts.** A `Kaufland Card % -X,XX` line under an item means the line price is before the discount. A `Štedite XX%` line means the price is already reduced.
- **Deposit refunds.** `ambalaža - PET` and `amb.- staklo` are deposit refunds.

### Lidl

- **Item lines and `POPUST`.** Item lines always show the full price. The discount follows on its own line: `POPUST XX% -X,XX` or `Lidl Plus popust -X,XX`.
- **Footer trap.** The summary `POPUST X,XX` after `za platiti` repeats discounts already attached to items. Ignore it completely, or the discount is counted twice.
- **Branch.** The branch comes from `IBR: 0198/...` or `PJ: 0198`. Keep the leading zeros.
- **Loyalty card.** No loyalty-card number is printed.

### DM

- **Branch.** The branch is the alphanumeric middle segment of the receipt number (`9619/K05F/5` gives `K05F`).
- **Cancellations.** `STORNO RETKA` cancels a line. Drop both the original and the cancellation.
- **Units.** Everything is sold per piece.

### Müller

- **Bonus points.** A `Müller bodovi EUR 0,49` line between `Međuzbroj` and `ZA PLATITI` is a payment with bonus points. If it is missed, the receipt does not balance.
- **Deposits.** Deposits (`POVRATNA NAKNADA`) are printed as ordinary positive item lines and are included in the subtotal.

## Pricing logic (legacy)

- **Discount already applied (shelf promotion).** The effective line amount is the printed amount, and the regular amount is printed plus discount.
- **Discount on a separate line.** The regular amount is the printed amount, and the effective amount is printed minus discount.
- **Checking line amounts.** Compare line amounts against the printed fields. Do not compare against price times quantity: the unit price is itself rounded, so reconstructing the amount from price and weight produces false 1–2 cent mismatches.
- **Cash.** For cash payments, record the receipt total and ignore the change.

## Deduplication lesson (legacy)

- **The legacy key.** The key is the store chain plus the purchase timestamp to the second. The receipt number was dropped from the key for two reasons:
  - OCR misreads it, so a resend produced a new ID.
  - An `UNKNOWN` sentinel caused collisions.
- **Why the key holds.** In practice, the family never makes two purchases in the same chain within the same second.

## Telegram intake requirements (telegram_core reference spec)

- **Token safety.** Never put the bot token in logs or exceptions. httpx error messages embed the request URL, which contains the token.
- **Polling timeout.** The long-polling read timeout is the poll timeout plus 10 s.
- **Retries.**
  - HTTP 429: wait exactly `retry_after`.
  - 5xx, network errors, or HTTP 200 without a valid `result`: exponential backoff, at most 5 attempts.
  - 4xx: fail without retrying.
- **Gate.** Accept a message only when the sender is on the allowlist (`from.id`), the chat is private, and `message_id > 0`. Ignore service and system updates silently.
- **Reactions.** 👍 means accepted; 👎 means unsupported content; 🤔 means an unknown or unsupported forward type. A failure to set a reaction must never break processing.
- **Attachment precedence.** Check attachment types in this order: `live_photo`, `photo`, `animation`, `document`, then other media. For a photo, pick the largest `PhotoSize` by area.
- **Size limit.** The limit is 20 MB, checked both before and after `getFile`. Refuse to download a file whose size Telegram did not confirm.
- **Polling offset.** Persist the offset atomically: write a temp file, flush, fsync, then replace.

## Image preprocessing idea (Gemini note, untested)

- **EXIF.** Correct the rotation from EXIF before sending.
- **Long receipts.** If height divided by width is above 2.5, slice the image vertically into overlapping chunks (about 12% overlap). Send them as JPEG parts in one request, so the model is not forced to squash a long receipt.
- **Determinism.** Use constrained decoding with a response schema, temperature 0, and no thinking budget.
- **Money values.** Use `Decimal` for all money values, never float.
- **Decompression bombs.** Cap the pixel count of incoming images.

## PostgreSQL access lesson (legacy)

- **Role layout.** The legacy setup had one schema owner, permission-bundle roles without login (read-write and read-only), and separate login roles per service.
- **Trigger permissions.** `SECURITY INVOKER` triggers run as the caller. Therefore, a writer role needs `USAGE` on enum types, rights on sequences, and `DELETE` on child tables for cascades to work.
