"""Synthetic Müller responses built per test, so each test states only the rows it is about."""

import json
from typing import Any

MUELLER_OIB = "84698789700"
CARD = "PLACANJE KARTICOM EUR"
CASH = "GOTOVINA EUR"
CHANGE = "POVRAT NOVCA EUR"
BONUS = "Müller bodovi EUR"


def item(
    text: str,
    quantity: str | None,
    unit_price: str | None,
    amount: str,
    discount: str | None = None,
    discount_note: str | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "quantity": quantity,
        "unit_price": unit_price,
        "discount": discount,
        "amount": amount,
        "discount_note": discount_note,
    }


def payment(text: str, amount: str) -> dict[str, Any]:
    return {"text": text, "amount": amount}


def response(**overrides: Any) -> str:
    body: dict[str, Any] = {
        "seller_oib": MUELLER_OIB,
        "store_name": "Zagreb EKZ Arena",
        "store_address": "Ulica Vice Vukova 6, 10000 Zagreb",
        "receipt_number": "18101/4981/3",
        "purchase_date": "15.03.2025",
        "purchase_time": "19:17",
        "amount_to_pay": "3,28",
        "lines": [
            item("BLINK SPUŽVA", "1", "3,28", "3,28a"),
        ],
        "payments": [payment(CARD, "3,28")],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)
