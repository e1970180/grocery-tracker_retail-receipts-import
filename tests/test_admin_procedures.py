"""Integration tests for stored administrative procedures."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import errors

from retail_receipts_import.adapters.postgres.receipts import SCHEMA, write_receipt
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptLine,
    Settlement,
    SettlementKind,
    telegram_source,
    zagreb_to_utc,
)


def _synthetic_receipt(purchased_at: datetime | None = None) -> NormalizedReceipt:
    return NormalizedReceipt(
        payload_version=1,
        chain_id="spar",
        store_name="SPAR Test",
        purchased_at=purchased_at or zagreb_to_utc(datetime(2026, 5, 10, 14, 30)),
        total=Decimal("12.50"),
        lines=[
            ReceiptLine(
                printed_text="ORIGINAL CROISSANT",
                quantity=Decimal("2.000"),
                unit_price=Decimal("1.25"),
                printed_amount=Decimal("2.50"),
            ),
            ReceiptLine(
                printed_text="ORIGINAL COFFEE",
                quantity=Decimal("1.000"),
                unit_price=Decimal("10.00"),
                printed_amount=Decimal("10.00"),
            ),
        ],
        settlements=[
            Settlement(kind=SettlementKind.CARD, printed_text="MASTERCARD", amount=Decimal("12.50"))
        ],
    )


@pytest.mark.integration
def test_delete_receipt_by_id(receipts_conn: psycopg.Connection[tuple[Any, ...]]) -> None:
    receipt_id = uuid.uuid7()
    receipt = _synthetic_receipt()
    source = telegram_source(chat_id=100, message_id=1, buyer_name="Test")
    write_receipt(receipts_conn, receipt_id, receipt, source)

    # Verify receipt and lines are present
    assert receipts_conn.execute(
        f"SELECT count(*) FROM {SCHEMA}.receipts WHERE receipt_id = %s", (receipt_id,)
    ).fetchone() == (1,)
    assert receipts_conn.execute(
        f"SELECT count(*) FROM {SCHEMA}.receipt_lines WHERE receipt_id = %s", (receipt_id,)
    ).fetchone() == (2,)

    # Call delete procedure by UUID
    receipts_conn.execute("CALL retail_receipts_import.delete_receipt(%s)", (receipt_id,))

    # Receipt, lines, settlements must be gone
    assert receipts_conn.execute(
        f"SELECT count(*) FROM {SCHEMA}.receipts WHERE receipt_id = %s", (receipt_id,)
    ).fetchone() == (0,)
    assert receipts_conn.execute(
        f"SELECT count(*) FROM {SCHEMA}.receipt_lines WHERE receipt_id = %s", (receipt_id,)
    ).fetchone() == (0,)
    assert receipts_conn.execute(
        f"SELECT count(*) FROM {SCHEMA}.receipt_settlements WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone() == (0,)

    # Feed must contain both 'stored' and 'deleted' events in seq order
    events = receipts_conn.execute(
        "SELECT event FROM resolver_v1.feed WHERE receipt_id = %s ORDER BY seq", (receipt_id,)
    ).fetchall()
    assert [e[0] for e in events] == ["stored", "deleted"]


@pytest.mark.integration
def test_delete_receipt_by_chain_and_purchased_at(
    receipts_conn: psycopg.Connection[tuple[Any, ...]],
) -> None:
    receipt_id = uuid.uuid7()
    purchased_at = zagreb_to_utc(datetime(2026, 6, 1, 10, 15))
    receipt = _synthetic_receipt(purchased_at=purchased_at)
    source = telegram_source(chat_id=100, message_id=2, buyer_name="Test")
    write_receipt(receipts_conn, receipt_id, receipt, source)

    # Call delete procedure by (chain_id, purchased_at)
    receipts_conn.execute(
        "CALL retail_receipts_import.delete_receipt(%s, %s)", ("spar", purchased_at)
    )

    # Verify deletion
    assert receipts_conn.execute(
        f"SELECT count(*) FROM {SCHEMA}.receipts WHERE receipt_id = %s", (receipt_id,)
    ).fetchone() == (0,)
    events = receipts_conn.execute(
        "SELECT event FROM resolver_v1.feed WHERE receipt_id = %s ORDER BY seq", (receipt_id,)
    ).fetchall()
    assert [e[0] for e in events] == ["stored", "deleted"]


@pytest.mark.integration
def test_delete_receipt_nonexistent_raises(
    receipts_conn: psycopg.Connection[tuple[Any, ...]],
) -> None:
    missing_id = uuid.uuid7()
    with pytest.raises(errors.RaiseException, match=f"Receipt {missing_id} not found"):
        receipts_conn.execute("CALL retail_receipts_import.delete_receipt(%s)", (missing_id,))

    missing_time = zagreb_to_utc(datetime(2020, 1, 1, 0, 0))
    with pytest.raises(errors.RaiseException, match="Receipt for chain spar at .* not found"):
        receipts_conn.execute(
            "CALL retail_receipts_import.delete_receipt(%s, %s)", ("spar", missing_time)
        )


@pytest.mark.integration
def test_update_line_printed_text_by_id(
    receipts_conn: psycopg.Connection[tuple[Any, ...]],
) -> None:
    receipt_id = uuid.uuid7()
    receipt = _synthetic_receipt()
    source = telegram_source(chat_id=100, message_id=3, buyer_name="Test")
    write_receipt(receipts_conn, receipt_id, receipt, source)

    row = receipts_conn.execute(
        f"SELECT line_id FROM {SCHEMA}.receipt_lines WHERE receipt_id = %s AND line_no = 1",
        (receipt_id,),
    ).fetchone()
    assert row is not None
    line_id = row[0]

    # Update printed_text
    new_text = "CORRECTED BUTTER CROISSANT"
    receipts_conn.execute(
        "CALL retail_receipts_import.update_line_printed_text(%s, %s)", (line_id, new_text)
    )

    # Verify updated in base table and resolver_v1 view
    updated_base = receipts_conn.execute(
        f"SELECT printed_text FROM {SCHEMA}.receipt_lines WHERE line_id = %s", (line_id,)
    ).fetchone()
    assert updated_base == (new_text,)

    updated_view = receipts_conn.execute(
        "SELECT printed_text FROM resolver_v1.receipt_lines WHERE line_id = %s", (line_id,)
    ).fetchone()
    assert updated_view == (new_text,)


@pytest.mark.integration
def test_update_line_printed_text_by_receipt_and_line_no(
    receipts_conn: psycopg.Connection[tuple[Any, ...]],
) -> None:
    receipt_id = uuid.uuid7()
    receipt = _synthetic_receipt()
    source = telegram_source(chat_id=100, message_id=4, buyer_name="Test")
    write_receipt(receipts_conn, receipt_id, receipt, source)

    new_text = "ESPRESSO SPECIAL BLEND"
    receipts_conn.execute(
        "CALL retail_receipts_import.update_line_printed_text(%s, %s, %s)",
        (receipt_id, 2, new_text),
    )

    updated_view = receipts_conn.execute(
        "SELECT printed_text FROM resolver_v1.receipt_lines WHERE receipt_id = %s AND line_no = 2",
        (receipt_id,),
    ).fetchone()
    assert updated_view == (new_text,)


@pytest.mark.integration
def test_update_line_printed_text_validation_errors(
    receipts_conn: psycopg.Connection[tuple[Any, ...]],
) -> None:
    line_id = uuid.uuid7()
    with pytest.raises(errors.RaiseException, match="printed_text cannot be null or empty"):
        receipts_conn.execute(
            "CALL retail_receipts_import.update_line_printed_text(%s, %s)", (line_id, "   ")
        )

    with pytest.raises(errors.RaiseException, match=f"Receipt line {line_id} not found"):
        receipts_conn.execute(
            "CALL retail_receipts_import.update_line_printed_text(%s, %s)", (line_id, "Valid Text")
        )

    receipt_id = uuid.uuid7()
    with pytest.raises(
        errors.RaiseException, match=f"Receipt line for receipt {receipt_id} line_no 99 not found"
    ):
        receipts_conn.execute(
            "CALL retail_receipts_import.update_line_printed_text(%s, %s, %s)",
            (receipt_id, 99, "Valid Text"),
        )
