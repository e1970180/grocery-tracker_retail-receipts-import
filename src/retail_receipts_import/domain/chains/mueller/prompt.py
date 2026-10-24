"""The pass-2 instructions for a Müller receipt. The model copies; the plug-in computes."""

PASS2_PROMPT = """\
Transcribe this Müller receipt from Croatia into the JSON schema.
Copy every value exactly as printed. Do not compute, round, convert or correct anything.
Amounts and quantities keep the printed decimal comma and sign, for example "11,99", "0,89",
"-0,10", "-34,40".

- seller_oib: the 11-digit company OIB printed in the footer next to "OIB:".
- store_name: the shop name line printed under the company address (e.g. "Zagreb EKZ Arena").
  Never copy the company name ("MÜLLER TRGOVINA ZAGREB d.o.o.").
- store_address: the specific store address line printed under the shop name, without the phone
  (e.g. "Ulica Vice Vukova 6, 10000 Zagreb"). Never copy the head office address
  ("Oreškovićeva 6H/1, 10 020 Zagreb") and never include the telephone number.
- receipt_number: the value after "RB :" as printed, for example "18101/4981/3" or
  "143667/4972/4".
- purchase_date and purchase_time: only from the footer line beside the code (e.g. from
  "15.03.2025 19:17", purchase_date is "15.03.2025" and purchase_time is "19:17").
  Never copy Datum or Vrijeme from the card transaction slip.
- amount_to_pay: the amount next to "ZA PLATITI" (e.g. "3,28").
- lines: every item row in printed order.
  - An item row has "Kom Artikl Cijena [Popust] Iznos" (with a VAT letter glued to Iznos,
    e.g. "11,99a" or "0,10b"). Copy quantity into quantity (null if missing on POVRATNA NAKNADA),
    item name into text, unit price into unit_price, discount if printed into discount
    (e.g. "-0,10"), and Iznos with its glued letter into amount.
  - If a discount description row is printed under a discounted item (such as "Coupon 0,89 Blink"),
    copy it into discount_note on that item row; never transcribe it as its own item line.
- payments: the "Müller bodovi EUR 3,01" row printed above "ZA PLATITI" when present, then
  every payment row under "ZA PLATITI", such as "PLACANJE KARTICOM EUR 3,28",
  "GOTOVINA EUR 50,00" or "POVRAT NOVCA EUR -34,40". Copy the text and the amount alone
  (without "EUR"), keeping any printed minus sign.
- Leave out: running subtotals ("Međuzbroj"), "** Ponovni ispis računa **", the PDV tax table
  (including "Zbroj" and "POVRATNA" tax rows), loyalty points notes ("Na ovu kupovinu...",
  points balances), marketing texts, opening hours, ZKI, JIR, the footer code ("F76H...#..."),
  the barcode, and the entire card transaction slip ("DATUM", "VRIJEME", "MID:", "TID:", "PAN",
  "RRN", "Potvrđeno PIN-om").
"""
