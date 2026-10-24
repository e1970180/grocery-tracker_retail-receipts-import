"""Shared regexes and parsing helpers for values printed on retail receipts."""

import re
import unicodedata
from decimal import Decimal

from retail_receipts_import.domain.chains.errors import UnreadableReceipt

# Strict on purpose: a value in any other shape is a misread, and guessing would store it.
MONEY = re.compile(r"-?\d+,\d{2}")
QUANTITY = re.compile(r"\d+(?:,\d{1,3})?")
DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\.?")


def stripped(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def fold(text: str) -> str:
    # The model may keep or drop diacritics (PLAĆANJE, PLACANJE); compare without them.
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def money(text: str, field: str) -> Decimal:
    value = text.strip()
    if MONEY.fullmatch(value) is None:
        raise UnreadableReceipt(f"{field} {text!r} is not a printed amount")
    return Decimal(value.replace(",", "."))


def quantity(text: str) -> Decimal:
    value = text.strip()
    if QUANTITY.fullmatch(value) is None:
        raise UnreadableReceipt(f"quantity {text!r} is not a printed quantity")
    return Decimal(value.replace(",", "."))
