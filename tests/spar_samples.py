"""Synthetic Spar pass-2 responses: made-up stores, times and numbers, shaped like the real ones."""

import json
from typing import Any

CARD = "PLAĆANJE MASTERCARD"
CASH = "PLAĆANJE GOTOVINOM"


def item(text: str, quantity: str, price: str, amount: str, unit: str | None = None) -> Any:
    return {"text": text, "quantity": quantity, "unit": unit, "unit_price": price, "amount": amount}


def discount(text: str, amount: str) -> Any:
    return {"text": text, "quantity": None, "unit": None, "unit_price": None, "amount": amount}


def payment(text: str, amount: str) -> Any:
    return {"text": text, "amount": amount}


def response(**overrides: Any) -> str:
    body: dict[str, Any] = {
        "store_name": "SYNTHETIC STORE",
        "store_address": "Test street 1, 10000 Zagreb",
        "receipt_number": "100/2000/300",
        "purchase_date": "01.02.2030.",
        "purchase_time": "09:05",
        "total": "1,99",
        "lines": [item("SYNTHETIC ITEM", "1", "1,99", "1,99")],
        "payments": [payment(CARD, "1,99")],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)
