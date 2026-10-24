# Analyzer digests Q4: printed fields on sample receipts (working-tree files in doc-inbox/fixtures, not in the commit)

Two analyzers: Q4a (Lidl, Muller: images read visually) and Q4b (Kaufland, DM, Spar: PDF text layer via pdftotext). Card numbers masked to last 4; no private names reported. Samples only: Lidl 5 of 34, Muller 5 of 10, Kaufland 4 of 208, DM 5 of 9 (header grep of all 9), Spar 4 of 21.

## Lidl (files `Lidl/` L1-L5: 20260621_183809362_iOS.png, ..._183944767_iOS.png, WhatsApp Image 2026-10-24 at 11.10.09.jpeg, ..._184151689_iOS !.png, ..._184411334_iOS.png)

All are app screenshots or WhatsApp-forwarded images of a "Digitalni racun", with app chrome around a monospace receipt; not paper photos.

- Store name: only the legal entity "Lidl Hrvatska d.o.o. k.d." with "Velika Gorica, Ulica kneza Ljudevita Posavskog 53", same on all 5 files (header). Followed by "OIB: ... , PJ: 0269" where PJ (shop number) differs per shop (0205, 0269, 0198). No shop name label such as "Lidl <city>" is printed.
- Store address: last header line under the OIB/PJ line, e.g. "Omladinska 1A, Mali Losinj" (L1), "Julija Knifera 10, Zagreb" (L2, L3), "Ulica Ive Robica 4, Zagreb" (L4, L5). Printed a second time in the app footer "Kupnja izvrsena u" with postcode (wording differs between files: district names, "1 / A" split).
- Receipt number: label "Br.raC.:", shape `<number>/POSL<PJ>/<digits>`, e.g. "1259/POSL0205/10121", "31095/POSL0269/10102"; footer block under two lidl.hr URLs. A second identifier "IBR:" with shape `<PJ>/<number>/<2 digits>` (e.g. "0269/194757/01") below it; JIR (UUID) and ZKI (hex) above the URLs. All 5 files.
- Loyalty card number: NOT printed on any of the 5. "LIDL PLUS" appears only as a thank-you line, a "Lidl Plus popust" discount line and a "Lidl Plus usteda" box (L2).
- Cashier/terminal: "Poslužio(la) Blagajnik <n>" (a number, not a name) on all 5. Card terminal block on card receipts only: L2/L3 "TERMINAL", "TID", "MID"; L4 "MID", "TID", "Br.Trn". Cash receipts L1, L5 have none.
- Date/time: "Datum: DD.MM.YYYY HH:MM:SS" in the footer block; the card block repeats date/time about a minute later ("DATUM/VRIJEME").
- Payment: body line "za platiti <total>", then "Kartica <amount>" for card; "Novcanice <tendered>" and "Ostatak novcanice -<change>" for cash. Card block shows a masked PAN (L2/L3 "557474**AAAA4997 CL", L4 "*************1071").
- Notable: L5 (26.08.2023) is a HRK-to-EUR transition receipt ("(31,57kn)", "1 EUR = 7,53450 HRK"). File names carry dates that do not match the receipt dates. Not sampled: 29 other Lidl files.

## Muller (files `Muller receipts/` M1-M5: muller 25.36 (full) .png, muller 4.jpeg, muller 8.jpeg, muller 8.41 (full).png, muller1.jpeg; M1 and M5 are the same receipt)

- Store name: header "Müller trgovina Zagreb d.o.o" (company), then the company address "Oresko­viceva 6H/1, 10 020 Zagreb"; shop identity is the next line, a mall name ("Zagreb EKZ Arena", "Zagreb Avenue Mall").
- Store address: "Ulica Vice Vukova 6, 10000 Zagreb, +385 1 / 4615261" (EKZ Arena); "Avenija Dubrovnik 16, 10000 Zagreb, +385 1 / 6556342" (Avenue Mall). Printed once, in the header.
- Receipt number: "RB :18101/4981/3", "RB :37833/4981/3", "RB :148305/4981/3", "RB :143667/4972/4"; shape `RB :<number>/<4 digits>/<1 digit>`; middle number tracks the shop. Footer block under "Oznaka Operatera:" and "OIB:"; ZKI/JIR also printed. Barcode caption like "F76H4981#31739023432122".
- Loyalty card number: NOT printed on any of the 5. "Müller bodovi EUR 0,87" appears as a points amount (M2, M4) and a fixed app note on all; M4 has a line excluding items from the loyalty programme.
- Cashier/terminal: "Oznaka Operatera:<number>" (numeric); "TID:" and "MID:" in the card block; no till number.
- Date/time: "DATUM: dd.mm.yyyy VRIJEME: hh:mm:ss" in the card block; barcode caption "dd.mm.yyyy hh:mm" on all card receipts and the only date/time on the cash receipt M3.
- Payment: "PLACANJE KARTICOM EUR <amt>" plus card block with masked PAN; cash "GOTOVINA EUR 50,00" and "POVRAT NOVCA EUR -34,40" (M3, no card block).
- Notable: M4 is marked as a reprint ("Ponovni ispis racuna"). Not sampled: 5 other Muller files.

## Kaufland (files `Kaufland receipts/` K1-K4: 20250625_185418.pdf, 20260426_203845.pdf, kaufland 42126.pdf, 20260621_203008.pdf)

Each PDF repeats the receipt twice (wide and narrow copy).
- Store name: "Kaufland Hrvatska k.d." (legal entity), header, K1-K4.
- Store address: header; "Donje Svetice 14, Zagreb" is the company; "PJ5230,Zagreb Blato" is the shop (PJ ID and name); "Jaruscica 6" is the shop street without postcode or city.
- Receipt number: "Racun 279763/5230/4", shape `<running no>/<shop 5230>/<POS no>`, header and repeated in the narrow copy.
- Loyalty card: "Kaufland Card:   xxxxx8265" masked, last 4 visible; a Kaufland card number, in the body above the payment block, K1-K4. Points: "You earned 12 points for this purchase." at the top (English), "Vase trenutno stanje bodova: 677" at the bottom; K3 also "You saved 0,15 EUR with Kaufland Card" and a "Kaufland Card %" item line.
- Cashier/POS/terminal: footer "Poslovnic 5230 POS: 4 Blagajnik: 115"; "TERMINAL: 80260439" in the payment block.
- Date/time: card block "DATUM: 26/04/27 VRIJEME: 10:44:03" (yy/mm/dd) and fiscal line "Datum:27.04.26 Vrijeme10:44:08 Pot.98120" (dd.mm.yy).
- Payment: "Za platiti", "Kartica <amt>", "Za vratiti 0,00"; card block with masked PAN, AID, APN, IZNOS, BR.PROMETA, BR.ODOBRENJA, RRN, ODOBRENO. ZKI/JIR in footer; 28-digit barcode number on the last line.
- Notable: purchase dates inside files differ from file-name dates (K1 prints 30.11.24, K2 19.09.23). K2 is a "Receipt Copy" with HRK/EUR mixed amounts. All 4 sampled show the same shop (PJ5230). Not sampled: 204 files.

## DM (files `DM receipts/` D1-D5, dm-eBon_*.pdf; all are duplicate e-receipts)

- Store name: "dm-drogerie markt d.o.o." printed only in D2 and D4; D1, D3, D5 print no store-name line (header grep of all 9 files found none either).
- Shop address: "Ulica Vice Vukova 6, 10000 ZAGREB" (D2) or "Slavonska av. 11d, 10000 ZAGREB" (D4) with a shop phone; none in D1, D3, D5. The company address "10090 ZAGREB, Kovinska 5a", "Centrala: 01/3670-100" and OIB are on all five, so on D1, D3, D5 nothing says which shop sold the goods.
- Receipt number: "Br. racuna: 5999/K05F/2", "Br. racuna: 38588/K08H/1" ("Broj racuna:" in D1); shape `<number>/<register code K05F, K08H, K044, K01M>/<last part>`. Header line "05.03.2026 16:18 1810/2 175797 2134" repeats parts of it.
- Loyalty card: no card number in any form; no points balance. "Za ovu kupovinu mogli ste dobiti 4 dm active beauty bod(a/ova)" (D5).
- Cashier/terminal: "Blagajnik: 175797"; "MID: 1970218 TID: 76530344", "Br.Trn: 606401613458".
- Date/time: header `dd.mm.yyyy hh:mm`, payment block "Datum: ... Vrijeme: hh:mm"; times can differ by minutes (D1 18:42 vs 18:43, D3 14:28 vs 14:31). Date/time appears four times per receipt.
- Payment: "Ukupno", "MASTERCARD EUR -4,70" (negative on the item list, positive in the card block "4,70 EUR"); "Duplikat racuna" marker. D3 has "STORNO RETKA" lines. Receipt-number label varies between files.

## Spar (files `Spar + Interspar receipts/` S1-S4, named by a 30-digit number)

- Company: "SPAR HRVATSKA d.o.o." / "Slavonska avenija 50, 10000 Zagreb" / "MB:1527100 OIB:46108893754", header, S1-S4.
- Store name: a line under the company: "SPAR SUPERMARKET ZG-BAKIEVA", "SPAR SUPERMARKET ZG-SREDISE", "INTERSPAR ARENA ZAGREB".
- Shop address: next line, e.g. "Vojina Bakica 1, 10000 Zagreb" (S2), "Ivana Sibla 11, 10000 Zagreb" (S3), "V.Vukova 6, 10000 Zagreb" (S1, S4).
- Receipt number: footer "Broj racuna:3169/8714/103", shape `<n>/<shop code>/<register>`; shop code 8714 for Interspar, 87085 or 87005 for supermarkets.
- Loyalty card: no card number or points block in any of the 4.
- Cashier/till: "Blag. 90010834 Kasa 103 Trans 2600 Poz.18"; "TID: SP000270 MID: 1913266" in the card block (not S2, which is cash only).
- Date/time: header "Vasa kupnja dana 16.05.2026. u 14:31 sati" (no seconds); card block "DATUM: 26/05/16 VRIJEME: 14:32:02".
- Payment: "UKUPNO 54,25", "PLACANJE MASTERCARD 54,25", "PLACANJE GOTOVINOM 50,00"; S4 split tender cash + card; masked PAN "557474******4997 CL". 30-digit footer number equals the PDF file name.
- Not sampled: 17 other Spar files.

## Looked for and not found (all of Q4)
- Loyalty card number on Lidl, Muller, DM and Spar: none printed in any sample. Only Kaufland prints a masked Kaufland Card number.
- Separate shop-name label on Lidl and DM (most files): not printed.
- Cashier names on any chain: only numbers.
- Per-line article codes (EAN/SKU) on Kaufland, DM, Spar: not seen in the lines read.
