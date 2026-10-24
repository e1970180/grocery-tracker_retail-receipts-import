"""Synthetic Lidl responses: made-up stores, times and numbers, shaped like the real ones."""

import json
from typing import Any

CARD = "Kartica"
CASH = "Novčanice"
CHANGE = "Ostatak novčanice"
LIDL_OIB = "66089976432"


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


def payment(text: str, amount: str) -> Any:
    return {"text": text, "amount": amount}


def response(**overrides: Any) -> str:
    body: dict[str, Any] = {
        "seller_oib": LIDL_OIB,
        "pj": "0269",
        "ibr": "0269/024832/05",
        "store_address": "Julija Knifera 10, Zagreb",
        "receipt_number": "2003/POSL0269/10502",
        "purchase_date": "23.05.2026",
        "purchase_time": "15:54:37",
        "total": "1,99",
        "lines": [item("SYNTHETIC ITEM", "1", None, "1,99")],
        "payments": [payment(CARD, "1,99")],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)
