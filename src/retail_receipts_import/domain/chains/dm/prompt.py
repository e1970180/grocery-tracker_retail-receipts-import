"""The pass-2 instructions for a DM receipt. The model copies; the plug-in computes."""

PASS2_PROMPT = """\
Transcribe this DM (dm-drogerie markt) receipt from Croatia into the JSON schema.
Copy every value exactly as printed. Do not compute, round, convert or correct anything.
Amounts and quantities keep the printed decimal comma and sign, for example "7,90", "-1,10",
"-15,80".

- seller_oib: the 11-digit company OIB printed in the header next to "OIB:".
- store_address: the specific store address line printed above the Kovinska head office
  (e.g. "Ulica Vice Vukova 6, 10000 ZAGREB" or "Slavonska av. 11d, 10000 ZAGREB"), or null if
  no separate store address is printed. Never copy the head office address
  ("10090 ZAGREB, Kovinska 5a").
- receipt_number: the value after "Broj računa:" or "Br. računa:" as printed, for example
  "212915/K05F/2" or "9619/K05F/5".
- purchase_date and purchase_time: only from the header line above the receipt number (e.g. from
  "21.09.2024 18:42 3342/2 ...", purchase_date is "21.09.2024" and purchase_time is "18:42").
  Never copy Datum or Vrijeme from the card slip at the bottom.
- total: the "Ukupno" amount (e.g. "15,80").
- lines: every item row between the receipt number and "Ukupno", in printed order.
  - Item row: the item name on one row, followed by "Q kom x P A V" (where V is the tax class
    digit 1, 2, or 3): text is the item name, quantity "Q" (e.g. "1"), unit_price "P"
    (e.g. "7,90"), amount "A" (e.g. "7,90"). Do not copy the tax class digit into the amount.
  - If "STORNO RETKA" appears: transcribe "STORNO RETKA" as its own row (text "STORNO RETKA",
    quantity null, unit_price null, amount "0,00"), followed by the cancelled item row with its
    item name, negative quantity (e.g. "-1"), negative unit_price (e.g. "-1,10"), and negative
    amount (e.g. "-1,10").
- payments: every row between "Ukupno" and the "St. PDV-a" table, such as
  "MASTERCARD EUR -15,80", "GOTOVINA EUR -4,00", or "Povrat novaca EUR 0,75". Copy the text and
  the amount signed exactly as printed.
- Leave out: the top barcode/number, "Duplikat računa", cashier line ("Blagajnik: ..."), the
  "St. PDV-a" tax table, "dm active beauty bod" lines, marketing texts, opening hours, ZKI, JIR,
  and the entire card transaction slip ("MID:", "TID:", "MASTERCARD ****...", "Kupovina: ...",
  "Potvrđeno NFC-om").
"""
