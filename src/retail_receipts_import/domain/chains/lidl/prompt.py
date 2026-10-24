"""The pass-2 instructions for a Lidl receipt. The model copies; the plug-in computes."""

PASS2_PROMPT = """\
Transcribe this LIDL receipt from Croatia into the JSON schema.
Copy every value exactly as printed. Do not compute, round, convert or correct anything.
Amounts and quantities keep the printed decimal comma, for example "3,29", "-0,83", "0,946".

- seller_oib: the 11-digit company OIB printed in the header next to "OIB:".
- pj: the value next to "PJ:", e.g. "0269", keeping leading zeros.
- ibr: the value after "IBR:", e.g. "0269/024832/05".
- store_address: the street address line printed directly under the "OIB: ..., PJ: ..." line,
  for example "Julija Knifera 10, Zagreb". Do not copy the company address printed earlier.
- receipt_number: the value after "Br.rač.:" as printed, for example "2003/POSL0269/10502".
- purchase_date and purchase_time: only from the line with "Datum:", for example "23.05.2026"
  and "15:54:37" or "15:54". Never from the card slip's DATUM or VRIJEME.
- total: the "za platiti" amount.
- lines: every row between the "€" header and "za platiti", in printed order.
  - Single item such as "1 Kremšnita 3,29 C": text is "Kremšnita" (omit the leading count "1 "),
    quantity is "1", unit is null, unit_price is null, amount is "3,29" without the tax letter.
  - Multi-quantity item such as "Hugo 2,99x 2 5,98 C": text is "Hugo", quantity is "2",
    unit is null, unit_price is "2,99", amount is "5,98" without the tax letter.
  - Weighed item such as "Šljiva okrugla 3,77 A" with "0,946 kg x 3,99 EUR/kg" under it:
    merge both rows into one entry: text "Šljiva okrugla", quantity "0,946", unit "kg",
    unit_price "3,99", amount "3,77" without the tax letter.
  - Discount row such as "POPUST 25% -0,83", "Lidl akcija -1,09", "Lidl Plus popust -0,19":
    text is the discount description, amount is the negative amount, and quantity, unit,
    unit_price are null.
  - Deposit return such as "Otkup ambalaže -3,60 D": text is "Otkup ambalaže", amount "-3,60",
    and quantity, unit, unit_price are null.
  - Price change such as "Promjena cijene 0,00": text "Promjena cijene", amount "0,00",
    and quantity, unit, unit_price are null.
- payments: every payment row under "za platiti", such as "Kartica 19,75", "Novčanice 100,00",
  "Ostatak novčanice -57,03".
- Leave out: the footer "POPUST ...", "Lidl Plus ušteda" box, the PDV tax table,
  "Pov. naknada", cashier line, JIR, ZKI, the entire card slip, QR code, barcode, and footer text.
"""
