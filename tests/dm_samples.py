"""Synthetic DM responses built per test; the default header copies recorded case 212915."""

import json
from typing import Any

DM_OIB = "94124811986"
CARD = "MASTERCARD EUR"
CASH = "GOTOVINA EUR"
CHANGE = "Povrat novaca EUR"


def item(
    text: str,
    quantity: str,
    unit_price: str | None,
    amount: str,
) -> dict[str, Any]:
    return {
        "text": text,
        "quantity": quantity,
        "unit_price": unit_price,
        "amount": amount,
    }


def storno_marker(text: str = "STORNO RETKA", amount: str = "0,00") -> dict[str, Any]:
    return {
        "text": text,
        "quantity": None,
        "unit_price": None,
        "amount": amount,
    }


def storno_line(
    text: str,
    quantity: str,
    unit_price: str | None,
    amount: str,
) -> dict[str, Any]:
    return {
        "text": text,
        "quantity": quantity,
        "unit_price": unit_price,
        "amount": amount,
    }


def payment(text: str, amount: str) -> dict[str, Any]:
    return {"text": text, "amount": amount}


def response(**overrides: Any) -> str:
    body: dict[str, Any] = {
        "seller_oib": DM_OIB,
        "store_address": None,
        "receipt_number": "212915/K05F/2",
        "purchase_date": "21.09.2024",
        "purchase_time": "18:42",
        "total": "15,80",
        "lines": [
            item("Maybelline korekt /podočnjak", "1", "7,90", "7,90"),
            item("Maybelline kor. za podočnjak", "1", "7,90", "7,90"),
        ],
        "payments": [payment(CARD, "-15,80")],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)
