"""The pass-2 instructions for a Spar receipt. The model copies; the plug-in computes."""

PASS2_PROMPT = """\
Transcribe this SPAR or INTERSPAR receipt from Croatia into the JSON schema.
Copy every value exactly as printed. Do not compute, round, convert or correct anything.
Amounts and quantities keep the printed decimal comma, for example "1,99", "-0,30", "0,326".

- seller_oib: the 11-digit company OIB printed in the header next to "OIB:" or "OIB".
- store_name: the store line printed under the company's MB and OIB line, for example
  "INTERSPAR ARENA ZAGREB". Never the company name "SPAR HRVATSKA D.O.O.".
- store_address: the line printed under the store line.
- purchase_date and purchase_time: only from the line
  "Vaša kupnja dana DD.MM.YYYY. u HH:MM sati". Never from the card slip's DATUM or VRIJEME.
- receipt_number: the value after "Broj računa:", as printed.
- lines: every row between the "EUR" header and "UKUPNO", in printed order.
  - An item is its name line plus the line under it, such as "2 x 0,99   1,98 A" or
    "0,326 kg(N) x 4,99 EUR/kg   1,63 A". text is the name, quantity is "2" or "0,326",
    unit is "kg(N)" on a weighed item and null otherwise, unit_price is "0,99" or "4,99",
    amount is the amount on the right without the tax letter.
  - A discount row such as "Joker 15%   -0,30" is its own entry: text "Joker 15%",
    amount "-0,30", and quantity, unit and unit_price null.
- total: the UKUPNO amount.
- payments: every "PLAĆANJE ..." row and the "OSTATAK NOVCA" row, with text and amount
  as printed.
- Leave out "Vaša ušteda", the tax table, "Povratna naknada", "KZP Markice", "SMEG",
  the whole card slip, ZKI, JIR and the footer.
"""
