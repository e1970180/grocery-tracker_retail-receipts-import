"""The pass-2 instructions for a Kaufland receipt. The model copies; the plug-in computes."""

PASS2_PROMPT = """\
Transcribe this KAUFLAND receipt from Croatia into the JSON schema.
Copy every value exactly as printed. Do not compute, round, convert or correct anything.
Amounts and quantities keep the printed decimal comma, for example "2,90", "-0,88", "0,774".

The PDF prints the same receipt twice. Transcribe it once, never both copies. If a row of one
copy is covered (for example by the QR code), read that row from the other copy.

- seller_oib: the 11-digit company OIB printed in the header next to "OIB:".
- pj_line: the line with "PJ" and the store name as printed, for example "PJ5230,Zagreb Blato".
- store_address: the street line printed directly under the PJ line, for example "Jaruščica 6".
  Do not copy the company address printed above the OIB.
- receipt_number: the value after "Račun" as printed, for example "21833/5230/6".
- purchase_date and purchase_time: only from the fiscal line "Datum:DD.MM.YY VrijemeHH:MM:SS",
  for example "25.02.26" and "12:33:51". Never from the card slip's DATUM or VRIJEME.
- total: the "Za platiti" amount.
- loyalty_card: the value after "Kaufland Card:" masked as printed, e.g. "xxxxx8265", else null.
- lines: every row between "Račun ... Cijena EUR" and "Za platiti", in printed order.
  - Item on one row such as "K.kamilica2x70 1,84 c": text "K.kamilica2x70", quantity "1",
    unit null, unit_price null, amount "1,84" without the tax letter.
  - Item whose next row is "qty * price amount", such as "K.Voda 7L" then "2 * 1,45 2,90 c",
    or both on one row: one entry, text "K.Voda 7L", quantity "2", unit null,
    unit_price "1,45", amount "2,90".
  - Weighed item such as "Pileće zadnja četvrt" then "0,774 kg * 1,40 1,08 E": one entry,
    text "Pileće zadnja četvrt", quantity "0,774", unit "kg", unit_price "1,40", amount "1,08".
  - Discount row such as "Kaufland Card% -0,88" or "Popust na kupnju -0,37": text is the
    discount text, amount the negative amount; quantity, unit, unit_price null.
  - Row starting "Štedite", such as "Štedite 30% ili 0,46 EUR!": text as printed, amount is the
    EUR figure ("0,46"); quantity, unit, unit_price null.
  - Deposit return such as "ambalaža - PET *" then "14 * 0,10 -1,40 F", or
    "amb.- staklo * 7 * 0,10 -0,70 F": one entry, text "ambalaža - PET *", amount "-1,40";
    quantity, unit, unit_price null.
- payments: every row under "Za platiti" before the PDV table, such as "Kartica 21,32",
  "Euro EUR 50,00", "Za vratiti 6,33".
- Leave out: "Međusuma", "Suma", "Povratna naknada", an amount in HRK, the PDV tax table,
  "* bez prava na popust", cashier line, JIR, ZKIR, the entire card slip, QR code, barcode,
  and the points text.
"""
