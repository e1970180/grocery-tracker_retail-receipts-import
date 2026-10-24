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
