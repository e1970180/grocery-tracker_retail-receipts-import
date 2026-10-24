"""Writer tests against a throwaway PostgreSQL: each outcome, check failure and rollback."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import errors

from retail_receipts_import.adapters.postgres import receipts as writer
from retail_receipts_import.adapters.postgres.receipts import WriteKind, write_receipt
from retail_receipts_import.domain.receipt import (
    ItemsSettlementMismatch,
    LineKind,
    NormalizedReceipt,
    ReceiptLine,
    ReceiptSource,
    Settlement,
    SettlementKind,
    TotalSettlementMismatch,
    telegram_source,
)

pytestmark = pytest.mark.integration

PURCHASED = datetime(2026, 10, 24, 10, 34, tzinfo=UTC)
TABLES = ("receipts", "receipt_lines", "receipt_settlements", "receipt_feed")


def _line(
    text: str,
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


def _card(amount: str) -> Settlement:
    return Settlement(kind=SettlementKind.CARD, printed_text="KARTICA", amount=Decimal(amount))


def _receipt(
    lines: list[ReceiptLine],
    settlements: list[Settlement] | None = None,
    total: str | None = None,
    chain_id: str = "spar",
    purchased_at: datetime = PURCHASED,
) -> NormalizedReceipt:
    paid = sum((line.effective_amount for line in lines), Decimal(0))
    return NormalizedReceipt(
        payload_version=1,
        chain_id=chain_id,
        store_name="SPAR",
        purchased_at=purchased_at,
        total=Decimal(total) if total is not None else paid,
        lines=lines,
        settlements=settlements if settlements is not None else [_card(str(paid))],
    )


def _counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLES:
        row = conn.execute(f"SELECT count(*) FROM retail_receipts_import.{table}").fetchone()
        assert row is not None
        counts[table] = row[0]
    return counts


def _empty() -> dict[str, int]:
    return dict.fromkeys(TABLES, 0)


def _miss_first_call(real: Callable[..., Any]) -> Callable[..., Any]:
    """A lookup that misses on its first call and answers truthfully afterwards."""
    calls = {"count": 0}

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        return None if calls["count"] == 1 else real(*args, **kwargs)

    return wrapper


def test_mismatch_writes_nothing(receipts_conn: psycopg.Connection[Any]) -> None:
    receipt = _receipt([_line("Kruh", printed="2.00")], [_card("2.02")])
    with pytest.raises(ItemsSettlementMismatch):
        write_receipt(receipts_conn, uuid.uuid7(), receipt, telegram_source(1, 1, "Ana"))
    assert _counts(receipts_conn) == _empty()


def test_total_mismatch_writes_nothing(receipts_conn: psycopg.Connection[Any]) -> None:
    receipt = _receipt([_line("Kruh", printed="2.00")], total="2.02")
    with pytest.raises(TotalSettlementMismatch):
        write_receipt(receipts_conn, uuid.uuid7(), receipt, telegram_source(1, 1, "Ana"))
    assert _counts(receipts_conn) == _empty()


def test_one_cent_difference_is_written(receipts_conn: psycopg.Connection[Any]) -> None:
    receipt = _receipt([_line("Kruh", printed="2.00")], [_card("2.01")], total="2.01")
    receipt_id = uuid.uuid7()
    result = write_receipt(receipts_conn, receipt_id, receipt, telegram_source(1, 1, "Ana"))
    assert result.kind is WriteKind.STORED
    assert result.receipt_id == receipt_id
    assert _counts(receipts_conn)["receipts"] == 1


def test_dedup_hit_from_another_source_is_a_duplicate(
    receipts_conn: psycopg.Connection[Any],
) -> None:
    receipt = _receipt([_line("Kruh", printed="2.00")])
    first = write_receipt(receipts_conn, uuid.uuid7(), receipt, telegram_source(1, 1, "Ana"))
    second = write_receipt(receipts_conn, uuid.uuid7(), receipt, telegram_source(1, 2, "Ana"))
    assert second.kind is WriteKind.DUPLICATE
    assert second.receipt_id == first.receipt_id
    counts = _counts(receipts_conn)
    assert counts["receipts"] == 1
    assert counts["receipt_feed"] == 1


def test_own_write_is_reported_with_the_existing_receipt(
    receipts_conn: psycopg.Connection[Any],
) -> None:
    receipt = _receipt([_line("Kruh", printed="2.00")])
    source = telegram_source(1, 1, "Ana")
    first = write_receipt(receipts_conn, uuid.uuid7(), receipt, source)
    again = write_receipt(receipts_conn, uuid.uuid7(), receipt, source)
    assert again.kind is WriteKind.OWN_WRITE
    assert again.receipt_id == first.receipt_id
    counts = _counts(receipts_conn)
    assert counts["receipts"] == 1
    assert counts["receipt_feed"] == 1


def test_partial_storno_stores_one_netted_line(receipts_conn: psycopg.Connection[Any]) -> None:
    lines = [
        _line("Jogurt", quantity="3", printed="3.00"),
        _line("Storno", quantity="-1", printed="-1.00", kind=LineKind.STORNO, cancels_line=1),
    ]
    write_receipt(receipts_conn, uuid.uuid7(), _receipt(lines), telegram_source(1, 1, "Ana"))
    rows = receipts_conn.execute(
        "SELECT quantity, printed_amount FROM retail_receipts_import.receipt_lines"
    ).fetchall()
    assert rows == [(Decimal("2.000"), Decimal("2.00"))]


def test_over_storno_and_return_only_never_reach_the_writer() -> None:
    with pytest.raises(ValueError, match="beyond what was bought"):
        _receipt(
            [
                _line("Kruh", printed="1.00"),
                _line(
                    "Storno", quantity="-2", printed="-2.00", kind=LineKind.STORNO, cancels_line=1
                ),
            ]
        )
    with pytest.raises(ValueError, match="no purchased lines"):
        _receipt(
            [_line("Povrat", quantity="-1", printed="-1.00", kind=LineKind.RETURN)],
            [_card("-1.00")],
        )


def test_failure_after_lines_rolls_back_everything(
    receipts_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(writer, "_insert_settlements", boom)
    receipt = _receipt([_line("Kruh", printed="2.00")])
    with pytest.raises(RuntimeError, match="injected failure"):
        write_receipt(receipts_conn, uuid.uuid7(), receipt, telegram_source(1, 1, "Ana"))
    assert _counts(receipts_conn) == _empty()


def test_violation_with_a_missed_lookup_is_resolved_by_the_rerun(
    receipts_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _receipt([_line("Kruh", printed="2.00")])
    source = telegram_source(1, 1, "Ana")
    first = write_receipt(receipts_conn, uuid.uuid7(), receipt, source)
    monkeypatch.setattr(writer, "find_by_source", _miss_first_call(writer.find_by_source))
    monkeypatch.setattr(writer, "find_by_dedup_key", _miss_first_call(writer.find_by_dedup_key))
    again = write_receipt(receipts_conn, uuid.uuid7(), receipt, source)
    assert again.kind is WriteKind.OWN_WRITE
    assert again.receipt_id == first.receipt_id
    assert _counts(receipts_conn)["receipts"] == 1


def test_violation_with_both_lookups_missing_twice_is_raised(
    receipts_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt = _receipt([_line("Kruh", printed="2.00")])
    source = telegram_source(1, 1, "Ana")
    write_receipt(receipts_conn, uuid.uuid7(), receipt, source)
    monkeypatch.setattr(writer, "find_by_source", lambda conn, src: None)
    monkeypatch.setattr(writer, "find_by_dedup_key", lambda conn, chain, at: None)
    with pytest.raises(errors.UniqueViolation):
        write_receipt(receipts_conn, uuid.uuid7(), receipt, source)


def test_non_autocommit_connection_is_refused(pg_conn: psycopg.Connection[Any]) -> None:
    receipt = _receipt([_line("Kruh", printed="2.00")])
    with pytest.raises(ValueError, match="autocommit"):
        write_receipt(pg_conn, uuid.uuid7(), receipt, telegram_source(1, 1, "Ana"))


def test_schema_enforces_both_unique_keys(receipts_conn: psycopg.Connection[Any]) -> None:
    write_receipt(
        receipts_conn,
        uuid.uuid7(),
        _receipt([_line("Kruh", printed="2.00")]),
        telegram_source(1, 1, "Ana"),
    )
    insert = (
        "INSERT INTO retail_receipts_import.receipts (receipt_id, chain_id, store_name,"
        " currency, purchased_at, buyer_name, source_kind, source_ref)"
        " VALUES (%s, %s, 'SPAR', 'EUR', %s, 'Ana', %s, %s)"
    )
    with pytest.raises(errors.UniqueViolation, match="receipts_chain_purchased_key"):
        receipts_conn.execute(insert, (uuid.uuid7(), "spar", PURCHASED, "telegram", "9:9"))
    with pytest.raises(errors.UniqueViolation, match="receipts_source_key"):
        receipts_conn.execute(insert, (uuid.uuid7(), "konzum", PURCHASED, "telegram", "1:1"))


@pytest.mark.parametrize("chain_id", ["Spar", "other", "unreadable"])
def test_schema_refuses_bad_chain_ids(
    receipts_conn: psycopg.Connection[Any], chain_id: str
) -> None:
    with pytest.raises(errors.CheckViolation):
        receipts_conn.execute(
            "INSERT INTO retail_receipts_import.receipts (receipt_id, chain_id, store_name,"
            " currency, purchased_at, buyer_name, source_kind, source_ref)"
            " VALUES (%s, %s, 'SPAR', 'EUR', %s, 'Ana', 'telegram', %s)",
            (uuid.uuid7(), chain_id, PURCHASED, uuid.uuid4().hex),
        )


def test_round_trip_keeps_every_field_and_reference(
    receipts_conn: psycopg.Connection[Any],
) -> None:
    lines = [
        _line("Kruh", printed="2.00", unit="kom", unit_price=Decimal("2.00")),
        _line(
            "Jogurt",
            quantity="3",
            printed="3.00",
            separate="0.30",
            unit="kom",
            unit_price=Decimal("1.00"),
            discount_text="Kartica -10%",
        ),
        _line(
            "Storno",
            quantity="-1",
            printed="-1.00",
            separate="-0.10",
            kind=LineKind.STORNO,
            cancels_line=2,
        ),
        _line(
            "Sir",
            quantity="0.5",
            printed="5.00",
            included="1.00",
            separate="0.50",
            unit="kg",
            unit_price=Decimal("10.00"),
            discount_text="Štedite; Kartica",
        ),
        _line("Povrat", quantity="-1", printed="-2.00", kind=LineKind.RETURN),
    ]
    settlements = [
        Settlement(kind=SettlementKind.BONUS_POINTS, printed_text="BONUS", amount=Decimal("1.00")),
        Settlement(kind=SettlementKind.COUPON, printed_text="KUPON", amount=Decimal("0.50")),
        Settlement(
            kind=SettlementKind.DEPOSIT_REFUND, printed_text="POVRAT", amount=Decimal("8.00")
        ),
        _card("-3.20"),
    ]
    receipt = NormalizedReceipt(
        payload_version=1,
        chain_id="kaufland",
        store_name="Kaufland",
        branch_number="007",
        receipt_number="R-0001234",
        store_address="Ilica 1, Zagreb",
        loyalty_card_number="**** 1234",
        purchased_at=PURCHASED,
        total=Decimal("-3.20"),
        lines=lines,
        settlements=settlements,
    )
    source: ReceiptSource = telegram_source(-100123, 42, "Ana")
    receipt_id = uuid.uuid7()
    result = write_receipt(receipts_conn, receipt_id, receipt, source)
    assert result.kind is WriteKind.STORED
    assert result.receipt_id == receipt_id

    header = receipts_conn.execute(
        "SELECT receipt_id, chain_id, store_name, branch_number, receipt_number, store_address,"
        " loyalty_card_number, currency, purchased_at, buyer_name, source_kind, source_ref"
        " FROM retail_receipts_import.receipts"
    ).fetchone()
    assert header == (
        receipt_id,
        "kaufland",
        "Kaufland",
        "007",
        "R-0001234",
        "Ilica 1, Zagreb",
        "**** 1234",
        "EUR",
        PURCHASED,
        "Ana",
        "telegram",
        "-100123:42",
    )

    stored = receipts_conn.execute(
        "SELECT line_no, printed_text, quantity, unit, unit_price, printed_amount,"
        " included_discount, separate_discount, discount_text, regular_amount, effective_amount"
        " FROM retail_receipts_import.receipt_lines ORDER BY line_no"
    ).fetchall()
    assert stored == [
        (
            1,
            "Kruh",
            Decimal("1.000"),
            "kom",
            Decimal("2.00"),
            Decimal("2.00"),
            Decimal("0.00"),
            Decimal("0.00"),
            None,
            Decimal("2.00"),
            Decimal("2.00"),
        ),
        (
            2,
            "Jogurt",
            Decimal("2.000"),
            "kom",
            Decimal("1.00"),
            Decimal("2.00"),
            Decimal("0.00"),
            Decimal("0.20"),
            "Kartica -10%",
            Decimal("2.00"),
            Decimal("1.80"),
        ),
        (
            3,
            "Sir",
            Decimal("0.500"),
            "kg",
            Decimal("10.00"),
            Decimal("5.00"),
            Decimal("1.00"),
            Decimal("0.50"),
            "Štedite; Kartica",
            Decimal("6.00"),
            Decimal("4.50"),
        ),
    ]

    line_ids = receipts_conn.execute(
        "SELECT receipt_id, line_id FROM retail_receipts_import.receipt_lines"
    ).fetchall()
    assert len(line_ids) == 3
    assert all(row[0] == receipt_id and row[1].version == 7 for row in line_ids)

    settled = receipts_conn.execute(
        "SELECT receipt_id, settlement_no, kind, printed_text, amount"
        " FROM retail_receipts_import.receipt_settlements ORDER BY settlement_no"
    ).fetchall()
    assert settled == [
        (receipt_id, 1, "bonus_points", "BONUS", Decimal("1.00")),
        (receipt_id, 2, "coupon", "KUPON", Decimal("0.50")),
        (receipt_id, 3, "deposit_refund", "POVRAT", Decimal("8.00")),
        (receipt_id, 4, "card", "KARTICA", Decimal("-3.20")),
    ]

    feed = receipts_conn.execute(
        "SELECT receipt_id, event FROM retail_receipts_import.receipt_feed"
    ).fetchall()
    assert feed == [(receipt_id, "stored")]


def test_round_trip_with_null_store_name(
    receipts_conn: psycopg.Connection[Any],
) -> None:
    receipt = NormalizedReceipt(
        payload_version=1,
        chain_id="lidl",
        store_name=None,
        purchased_at=PURCHASED,
        total=Decimal("2.00"),
        lines=[_line("Kruh", printed="2.00")],
        settlements=[_card("2.00")],
    )
    receipt_id = uuid.uuid7()
    result = write_receipt(receipts_conn, receipt_id, receipt, telegram_source(1, 1, "Ana"))
    assert result.kind is WriteKind.STORED
    assert result.receipt_id == receipt_id

    row = receipts_conn.execute(
        "SELECT store_name FROM retail_receipts_import.receipts WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()
    assert row is not None
    assert row[0] is None
