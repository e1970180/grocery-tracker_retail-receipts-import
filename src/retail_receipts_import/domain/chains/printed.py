"""Shared regexes and parsing helpers for values printed on retail receipts."""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.receipt import zagreb_to_utc

# Strict on purpose: a value in any other shape is a misread, and guessing would store it.
MONEY = re.compile(r"-?\d+,\d{2}")
QUANTITY = re.compile(r"\d+(?:,\d{1,3})?")
DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\.?")
SHORT_YEAR_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{2}|\d{4})\.?")


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


def parse_pass2[T: BaseModel](model: type[T], response: str) -> T:
    try:
        return model.model_validate_json(response)
    except ValidationError as exc:
        # The error count only: the errors themselves would echo receipt content into logs.
        raise UnreadableReceipt(f"response fails the schema ({exc.error_count()} errors)") from None


def purchase_time(
    date_re: re.Pattern[str],
    time_re: re.Pattern[str],
    date_text: str,
    time_text: str,
) -> datetime:
    date = date_re.fullmatch(date_text.strip())
    time = time_re.fullmatch(time_text.strip())
    if date is None or time is None:
        raise UnreadableReceipt(f"purchase time {date_text!r} {time_text!r} cannot be read")
    day_str, month_str, year_str = date.group(1), date.group(2), date.group(3)
    year = 2000 + int(year_str) if len(year_str) == 2 else int(year_str)
    hour, minute = int(time.group(1)), int(time.group(2))
    try:
        return datetime(year, int(month_str), int(day_str), hour, minute)
    except ValueError:
        raise UnreadableReceipt(f"purchase time {date_text!r} {time_text!r} is no date") from None


def pass1_time(
    date_re: re.Pattern[str],
    time_re: re.Pattern[str],
    date: str | None,
    time: str | None,
) -> datetime | None:
    # Pass 1 only steers the early duplicate check, so an unreadable time skips it, never fails.
    if not date or not time:
        return None
    try:
        return zagreb_to_utc(purchase_time(date_re, time_re, date, time))
    except Exception:
        return None
