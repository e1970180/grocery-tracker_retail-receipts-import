from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from retail_receipts_import.domain.receipt import (
    LineKind,
    NormalizedReceipt,
    ReceiptLine,
    Settlement,
    SettlementKind,
    SourceKind,
    check_consistency,
    check_total,
    telegram_source,
    zagreb_to_utc,
)

PURCHASED = datetime(2026, 10, 24, 10, 34, tzinfo=UTC)


def _line(
    text: str = "Mlijeko",
    quantity: str = "1",
    printed: str = "1.00",
    included: str = "0",
    separate: str = "0",
    **extra: Any,
) -> ReceiptLine:
    return ReceiptLine(
        printed_text=text,
        quantity=Decimal(quantity),
        printed_amount=Decimal(printed),
        included_discount=Decimal(included),
        separate_discount=Decimal(separate),
        **extra,
    )


def _storno(cancels: int, quantity: str, printed: str, separate: str = "0") -> ReceiptLine:
    return _line(
        "Storno",
        quantity=quantity,
        printed=printed,
        separate=separate,
        kind=LineKind.STORNO,
        cancels_line=cancels,
    )


def _card(amount: str) -> Settlement:
    return Settlement(kind=SettlementKind.CARD, printed_text="KARTICA", amount=Decimal(amount))


def _receipt(
    lines: list[ReceiptLine],
    settlements: list[Settlement] | None = None,
    total: str | None = None,
    chain_id: str = "spar",
) -> NormalizedReceipt:
    paid = sum((line.effective_amount for line in lines), Decimal(0))
    if settlements is None:
        settlements = [_card(str(paid))]
    return NormalizedReceipt(
        payload_version=1,
        chain_id=chain_id,
        store_name="SPAR",
        purchased_at=PURCHASED,
        total=Decimal(total) if total is not None else Decimal(str(paid)),
        lines=lines,
        settlements=settlements,
    )


def test_included_discount_raises_regular_amount_only() -> None:
    line = _line(printed="8.00", included="1.00")
    assert line.regular_amount == Decimal("9.00")
    assert line.effective_amount == Decimal("8.00")


def test_separate_discount_lowers_effective_amount_only() -> None:
    line = _line(printed="8.00", separate="0.50")
    assert line.regular_amount == Decimal("8.00")
    assert line.effective_amount == Decimal("7.50")


def test_regular_and_effective_amounts_with_both_discounts() -> None:
    line = _line(printed="8.00", included="1.00", separate="0.50")
    assert line.regular_amount == Decimal("9.00")
    assert line.effective_amount == Decimal("7.50")


def test_sale_line_signs_are_enforced() -> None:
    with pytest.raises(ValidationError, match="positive quantity"):
        _line(quantity="0")
    with pytest.raises(ValidationError, match="cannot be negative"):
        _line(printed="-1.00")


def test_storno_and_return_lines_need_negative_values() -> None:
    with pytest.raises(ValidationError, match="negative quantity"):
        _line(quantity="1", kind=LineKind.RETURN)
    with pytest.raises(ValidationError, match="cannot be positive"):
        _line(quantity="-1", printed="1.00", kind=LineKind.RETURN)
    with pytest.raises(ValidationError, match="must name the line"):
        _line(quantity="-1", printed="-1.00", kind=LineKind.STORNO)
    with pytest.raises(ValidationError, match="cancels no line"):
        _line(quantity="-1", printed="-1.00", kind=LineKind.RETURN, cancels_line=1)


def test_settlement_signs_follow_kind() -> None:
    with pytest.raises(ValidationError, match="must be positive"):
        Settlement(kind=SettlementKind.BONUS_POINTS, printed_text="BONUS", amount=Decimal("-1"))
    with pytest.raises(ValidationError, match="must be positive"):
        Settlement(kind=SettlementKind.COUPON, printed_text="KUPON", amount=Decimal("0"))
    Settlement(kind=SettlementKind.DEPOSIT_REFUND, printed_text="POVRAT", amount=Decimal("0.25"))
    refund_card = Settlement(kind=SettlementKind.CARD, printed_text="KARTICA", amount=Decimal("-3"))
    assert refund_card.amount == Decimal("-3")


@pytest.mark.parametrize("chain_id", ["Spar", "other", "unreadable", "", "spar-1"])
def test_chain_id_must_be_a_reference_slug(chain_id: str) -> None:
    with pytest.raises(ValidationError, match="reference slug"):
        _receipt([_line()], chain_id=chain_id)


def test_currency_is_eur_only() -> None:
    with pytest.raises(ValidationError):
        NormalizedReceipt(
            payload_version=1,
            chain_id="spar",
            store_name="SPAR",
            currency="USD",  # type: ignore[arg-type]
            purchased_at=PURCHASED,
            total=Decimal("1"),
            lines=[_line()],
            settlements=[_card("1")],
        )


def test_store_name_is_optional_and_rejects_empty_string() -> None:
    receipt = NormalizedReceipt(
        payload_version=1,
        chain_id="spar",
        purchased_at=PURCHASED,
        total=Decimal("1"),
        lines=[_line()],
        settlements=[_card("1")],
    )
    assert receipt.store_name is None

    with pytest.raises(ValidationError):
        NormalizedReceipt(
            payload_version=1,
            chain_id="spar",
            store_name="",
            purchased_at=PURCHASED,
            total=Decimal("1"),
            lines=[_line()],
            settlements=[_card("1")],
        )


def test_purchased_at_must_be_utc_to_the_minute() -> None:
    base: dict[str, Any] = {
        "payload_version": 1,
        "chain_id": "spar",
        "store_name": "SPAR",
        "total": Decimal("1"),
        "lines": [_line()],
        "settlements": [_card("1")],
    }
    with pytest.raises(ValidationError, match="must be UTC"):
        NormalizedReceipt(
            purchased_at=datetime(2026, 10, 24, 12, 34, tzinfo=timezone(timedelta(hours=2))),
            **base,
        )
    with pytest.raises(ValidationError, match="zero seconds"):
        NormalizedReceipt(purchased_at=datetime(2026, 10, 24, 10, 34, 5, tzinfo=UTC), **base)


def test_consistency_passes_at_one_cent_and_fails_at_two() -> None:
    assert check_consistency(_receipt([_line(printed="2.00")], [_card("2.01")])) is None
    difference = check_consistency(_receipt([_line(printed="2.00")], [_card("2.02")]))
    assert difference == Decimal("-0.02")


def test_total_passes_at_one_cent_and_fails_at_two() -> None:
    assert check_total(_receipt([_line(printed="2.00")], total="2.01")) is None
    assert check_total(_receipt([_line(printed="2.00")], total="2.02")) == Decimal("0.02")


def test_total_checks_card_plus_cash_with_a_negative_card() -> None:
    settlements = [
        Settlement(kind=SettlementKind.CARD, printed_text="KARTICA", amount=Decimal("-3.00")),
        Settlement(kind=SettlementKind.CASH, printed_text="GOTOVINA", amount=Decimal("5.00")),
        Settlement(kind=SettlementKind.COUPON, printed_text="KUPON", amount=Decimal("1.00")),
    ]
    ok = _receipt([_line(printed="2.00")], settlements, total="2.00")
    assert check_total(ok) is None
    bad = _receipt([_line(printed="2.00")], settlements, total="3.00")
    assert check_total(bad) == Decimal("1.00")


def test_full_storno_nets_to_nothing_and_is_dropped() -> None:
    receipt = _receipt(
        [_line("Kruh", printed="2.00"), _line("Jaja"), _storno(2, "-1", "-1.00")],
    )
    stored = receipt.stored_lines()
    assert [line.printed_text for line in stored] == ["Kruh"]


def test_partial_storno_nets_into_its_sale_line_with_discount() -> None:
    sale = _line(
        "Jogurt", quantity="3", printed="3.00", separate="0.30", unit_price=Decimal("1.00")
    )
    receipt = _receipt([sale, _storno(1, "-1", "-1.00", separate="-0.10")])
    (stored,) = receipt.stored_lines()
    assert stored.quantity == Decimal("2")
    assert stored.printed_amount == Decimal("2.00")
    assert stored.separate_discount == Decimal("0.20")
    assert stored.effective_amount == Decimal("1.80")
    assert stored.unit_price == Decimal("1.00")
    assert stored.printed_text == "Jogurt"


def test_over_storno_is_refused_by_the_model() -> None:
    with pytest.raises(ValidationError, match="beyond what was bought"):
        _receipt([_line("Kruh"), _storno(1, "-2", "-2.00")])


def test_storno_pointing_out_of_range_or_forward_is_refused() -> None:
    with pytest.raises(ValidationError, match="out of range"):
        _receipt([_line("Kruh"), _storno(5, "-1", "-1.00")])
    with pytest.raises(ValidationError, match="not earlier"):
        _receipt([_storno(2, "-1", "-1.00"), _line("Kruh")])


def test_storno_pointing_at_a_return_is_refused() -> None:
    return_line = _line("Povrat", quantity="-1", printed="-1.00", kind=LineKind.RETURN)
    with pytest.raises(ValidationError, match="not a sale"):
        _receipt([_line("Kruh"), return_line, _storno(2, "-1", "-1.00")])


def test_separate_discount_above_printed_amount_is_refused() -> None:
    with pytest.raises(ValidationError, match="separate discount above its price"):
        _receipt([_line("Kruh", printed="1.00", separate="1.50")])


def test_quantity_with_four_decimals_is_refused() -> None:
    with pytest.raises(ValidationError):
        _line(quantity="1.2345")


def test_return_is_consistency_checked_but_not_stored() -> None:
    return_line = _line("Povrat", quantity="-1", printed="-2.00", kind=LineKind.RETURN)
    receipt = _receipt([_line("Kruh", printed="5.00"), return_line], total="3.00")
    assert check_consistency(receipt) is None
    assert [line.printed_text for line in receipt.stored_lines()] == ["Kruh"]


def test_return_only_receipt_is_refused() -> None:
    return_line = _line("Povrat", quantity="-1", printed="-2.00", kind=LineKind.RETURN)
    with pytest.raises(ValidationError, match="no purchased lines"):
        _receipt([return_line], [_card("-2.00")])


def test_telegram_source_reference_and_kind() -> None:
    source = telegram_source(-100123, 42, "Ana")
    assert source.kind is SourceKind.TELEGRAM
    assert source.ref == "-100123:42"
    assert source.buyer_name == "Ana"


def test_receipt_survives_a_json_round_trip() -> None:
    sale = _line("Jogurt", quantity="3", printed="3.00", separate="0.30", discount_text="-10%")
    receipt = _receipt([sale, _storno(1, "-1", "-1.00", separate="-0.10")], total="1.80")
    restored = NormalizedReceipt.model_validate_json(receipt.model_dump_json())
    assert restored == receipt


def test_zagreb_to_utc_drops_seconds_and_converts() -> None:
    assert zagreb_to_utc(datetime(2026, 10, 24, 12, 34, 56, 789)) == datetime(
        2026, 10, 24, 10, 34, tzinfo=UTC
    )


def test_zagreb_to_utc_autumn_overlap_takes_summer_offset() -> None:
    assert zagreb_to_utc(datetime(2026, 10, 25, 2, 30)) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_zagreb_to_utc_spring_gap_takes_winter_offset() -> None:
    assert zagreb_to_utc(datetime(2026, 3, 29, 2, 30)) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)


def test_zagreb_to_utc_refuses_aware_input() -> None:
    with pytest.raises(ValueError, match="naive"):
        zagreb_to_utc(datetime(2026, 10, 24, 12, 0, tzinfo=UTC))
