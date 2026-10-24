"""Unit tests for shared printed helpers and parsing rules."""

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel

from retail_receipts_import.domain.chains.errors import UnreadableReceipt
from retail_receipts_import.domain.chains.printed import (
    DATE,
    SHORT_YEAR_DATE,
    fold,
    money,
    parse_pass2,
    pass1_time,
    purchase_time,
    quantity,
    stripped,
)

TIME_WITH_OPTIONAL_SECONDS = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
TIME_TWO_GROUPS = re.compile(r"(\d{1,2}):(\d{2})")
MUELLER_TIME = re.compile(r"(\d{2}):(\d{2})")


class _SamplePass2(BaseModel):
    store_name: str
    total: str


def test_parse_pass2_valid() -> None:
    result = parse_pass2(_SamplePass2, '{"store_name": "Spar", "total": "10,00"}')
    assert result.store_name == "Spar"
    assert result.total == "10,00"


def test_parse_pass2_invalid_schema_raises_unreadable_receipt_with_count() -> None:
    with pytest.raises(UnreadableReceipt, match=r"^response fails the schema \(1 errors\)$"):
        parse_pass2(_SamplePass2, '{"store_name": "Spar"}')

    with pytest.raises(UnreadableReceipt, match=r"^response fails the schema \(2 errors\)$"):
        parse_pass2(_SamplePass2, "{}")


def test_parse_pass2_does_not_echo_receipt_content_in_error() -> None:
    secret = "TopSecretReceiptRow"
    with pytest.raises(UnreadableReceipt) as exc_info:
        parse_pass2(_SamplePass2, f'{{"store_name": "{secret}"}}')
    assert secret not in str(exc_info.value)


def test_purchase_time_four_digit_year() -> None:
    assert purchase_time(DATE, TIME_WITH_OPTIONAL_SECONDS, "23.05.2026", "15:54:37") == datetime(
        2026, 5, 23, 15, 54
    )
    assert purchase_time(DATE, TIME_WITH_OPTIONAL_SECONDS, "23.05.2026.", "15:54") == datetime(
        2026, 5, 23, 15, 54
    )
    assert purchase_time(DATE, TIME_TWO_GROUPS, "23.05.2026", "15:54") == datetime(
        2026, 5, 23, 15, 54
    )


def test_purchase_time_two_digit_year() -> None:
    # DM and Kaufland 2-digit year (e.g. '26' -> 2026)
    assert purchase_time(
        SHORT_YEAR_DATE, TIME_WITH_OPTIONAL_SECONDS, "23.05.26", "15:54"
    ) == datetime(2026, 5, 23, 15, 54)
    assert purchase_time(
        SHORT_YEAR_DATE, TIME_WITH_OPTIONAL_SECONDS, "23.05.26.", "15:54:02"
    ) == datetime(2026, 5, 23, 15, 54)
    # SHORT_YEAR_DATE also accepts 4-digit years
    assert purchase_time(
        SHORT_YEAR_DATE, TIME_WITH_OPTIONAL_SECONDS, "23.05.2026", "15:54"
    ) == datetime(2026, 5, 23, 15, 54)


def test_purchase_time_bad_date_or_time_regex_mismatch() -> None:
    with pytest.raises(UnreadableReceipt, match=r"purchase time 'invalid' '15:54' cannot be read"):
        purchase_time(DATE, TIME_TWO_GROUPS, "invalid", "15:54")

    with pytest.raises(
        UnreadableReceipt, match=r"purchase time '23.05.2026' 'invalid' cannot be read"
    ):
        purchase_time(DATE, TIME_TWO_GROUPS, "23.05.2026", "invalid")


def test_purchase_time_mueller_regex_refuses_seconds() -> None:
    with pytest.raises(
        UnreadableReceipt, match=r"purchase time '23.05.2026' '15:54:37' cannot be read"
    ):
        purchase_time(DATE, MUELLER_TIME, "23.05.2026", "15:54:37")

    assert purchase_time(DATE, MUELLER_TIME, "23.05.2026", "15:54") == datetime(2026, 5, 23, 15, 54)


def test_purchase_time_invalid_calendar_date_or_clock_time() -> None:
    with pytest.raises(UnreadableReceipt, match=r"purchase time '32.13.2026' '15:54' is no date"):
        purchase_time(DATE, TIME_TWO_GROUPS, "32.13.2026", "15:54")

    invalid_time_re = re.compile(r"(\d{2}):(\d{2})")
    with pytest.raises(UnreadableReceipt, match=r"purchase time '23.05.2026' '25:99' is no date"):
        purchase_time(DATE, invalid_time_re, "23.05.2026", "25:99")


def test_pass1_time_valid() -> None:
    # Daylight saving time (UTC+2)
    assert pass1_time(DATE, TIME_WITH_OPTIONAL_SECONDS, "23.05.2026", "15:54:37") == datetime(
        2026, 5, 23, 13, 54, tzinfo=UTC
    )
    assert pass1_time(DATE, TIME_TWO_GROUPS, "23.05.2026.", "15:54") == datetime(
        2026, 5, 23, 13, 54, tzinfo=UTC
    )

    # 2-digit year
    assert pass1_time(SHORT_YEAR_DATE, TIME_WITH_OPTIONAL_SECONDS, "23.05.26", "15:54") == datetime(
        2026, 5, 23, 13, 54, tzinfo=UTC
    )


def test_pass1_time_failures_return_none() -> None:
    assert pass1_time(DATE, TIME_TWO_GROUPS, "invalid", "15:54") is None
    assert pass1_time(DATE, TIME_TWO_GROUPS, "23.05.2026", "invalid") is None
    assert pass1_time(DATE, TIME_TWO_GROUPS, "32.13.2026", "15:54") is None
    assert pass1_time(DATE, re.compile(r"(\d{2}):(\d{2})"), "23.05.2026", "25:99") is None
    assert pass1_time(DATE, MUELLER_TIME, "23.05.2026", "15:54:37") is None
    assert pass1_time(DATE, TIME_TWO_GROUPS, "", "") is None
    assert pass1_time(DATE, TIME_TWO_GROUPS, None, None) is None
    assert pass1_time(DATE, TIME_TWO_GROUPS, "23.05.2026", None) is None


def test_stripped() -> None:
    assert stripped("  abc  ") == "abc"
    assert stripped("") is None
    assert stripped("   ") is None
    assert stripped(None) is None


def test_fold() -> None:
    assert fold("PLAĆANJE") == "PLACANJE"
    assert fold("POVRATNA NAKNADA") == "POVRATNA NAKNADA"


def test_money() -> None:
    assert money("12,34", "field") == Decimal("12.34")
    assert money("-0,50", "field") == Decimal("-0.50")
    with pytest.raises(UnreadableReceipt, match=r"field 'abc' is not a printed amount"):
        money("abc", "field")


def test_quantity() -> None:
    assert quantity("2") == Decimal("2")
    assert quantity("0,946") == Decimal("0.946")
    with pytest.raises(UnreadableReceipt, match=r"quantity 'abc' is not a printed quantity"):
        quantity("abc")
