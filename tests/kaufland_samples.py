"""Synthetic Kaufland responses built per test; the default header copies recorded case 21833."""

import json
from typing import Any

CARD = "Kartica"
CASH = "Euro EUR"
CHANGE = "Za vratiti"
KAUFLAND_OIB = "47432874968"


def item(
    text: str,
    quantity: str,
    price: str | None,
    amount: str,
    unit: str | None = None,
) -> Any:
    return {
        "text": text,
        "quantity": quantity,
        "unit": unit,
        "unit_price": price,
        "amount": amount,
    }


def discount(text: str, amount: str) -> Any:
    return {"text": text, "quantity": None, "unit": None, "unit_price": None, "amount": amount}


def stedite(text: str, amount: str) -> Any:
    return {"text": text, "quantity": None, "unit": None, "unit_price": None, "amount": amount}


def payment(text: str, amount: str) -> Any:
    return {"text": text, "amount": amount}


def response(**overrides: Any) -> str:
    body: dict[str, Any] = {
        "seller_oib": KAUFLAND_OIB,
        "pj_line": "PJ5230,Zagreb Blato",
        "store_address": "Ulica kneza Branimira 119",
        "receipt_number": "21833/5230/6",
        "purchase_date": "25.02.26",
        "purchase_time": "12:33:51",
        "total": "2,90",
        "lines": [item("SYNTHETIC ITEM", "1", None, "2,90")],
        "payments": [payment(CARD, "2,90")],
        "loyalty_card": "xxxxx8265",
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


# Recorded pass-2 response of sample 20260427_231253.pdf.
SAMPLE_20260427_231253_PASS2 = json.dumps(
    {
        "seller_oib": "47432874968",
        "pj_line": "PJ4430,Zagreb Središće",
        "store_address": "Julija Knifera 1",
        "receipt_number": "137297/4430/6",
        "purchase_date": "03.07.25",
        "purchase_time": "10:19:55",
        "total": "61,23",
        "lines": [
            {
                "text": "K.Voda 7L",
                "quantity": "2",
                "unit": None,
                "unit_price": "1,45",
                "amount": "2,90",
            },
            {
                "text": "Jamnica gaz.1,5 l",
                "quantity": "12",
                "unit": None,
                "unit_price": "0,99",
                "amount": "11,88",
            },
            {
                "text": "Agragold šećer 1 kg",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "0,75",
            },
            {
                "text": "Violeta Toal.pap2x60",
                "quantity": "5",
                "unit": None,
                "unit_price": "2,21",
                "amount": "11,05",
            },
            {
                "text": "KLC riža d.z.1kg",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "1,99",
            },
            {
                "text": "Sprite 2 l",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "2,25",
            },
            {
                "text": "Svježi posni sir",
                "quantity": "0,954",
                "unit": "kg",
                "unit_price": "3,20",
                "amount": "3,05",
            },
            {
                "text": "Bonito Vin.Char.0,75",
                "quantity": "2",
                "unit": None,
                "unit_price": "3,99",
                "amount": "7,98",
            },
            {
                "text": "Milchland Sir Gouda",
                "quantity": "0,317",
                "unit": "kg",
                "unit_price": "5,80",
                "amount": "1,84",
            },
            {
                "text": "Krizant. mix 5 kom.",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "3,49",
            },
            {
                "text": "Menta svj.",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "1,49",
            },
            {
                "text": "WD 40 sprej",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "3,49",
            },
            {
                "text": "Pan Rad.bres.đum0,5L",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "1,25",
            },
            {
                "text": "Boca za pivo *",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "0,16",
            },
            {
                "text": "Kruh njemački",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "1,99",
            },
            {
                "text": "K.vreće za smeć.25 L",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "0,85",
            },
            {
                "text": "amb.- staklo *",
                "quantity": None,
                "unit": None,
                "unit_price": None,
                "amount": "-0,20",
            },
            {
                "text": "ambalaža - PET *",
                "quantity": None,
                "unit": None,
                "unit_price": None,
                "amount": "-0,40",
            },
            {
                "text": "Boca za pivo *",
                "quantity": "4",
                "unit": None,
                "unit_price": "0,16",
                "amount": "-0,64",
            },
            {
                "text": "Marelica",
                "quantity": "3,040",
                "unit": "kg",
                "unit_price": "1,99",
                "amount": "6,05",
            },
            {
                "text": "Vrećica Vip",
                "quantity": "1",
                "unit": None,
                "unit_price": None,
                "amount": "0,01",
            },
        ],
        "payments": [
            {"text": "Kartica", "amount": "61,23"},
            {"text": "Za vratiti", "amount": "0,00"},
        ],
        "loyalty_card": "xxxxx8265",
    },
    ensure_ascii=False,
)
