"""Integration tests for the deterministic receipt line item key."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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
)
from retail_receipts_import.migrate import apply_migrations
from tests.conftest import REPO

pytestmark = pytest.mark.integration

Conn = psycopg.Connection[tuple[object, ...]]

# The contract's vectors: (chain_id, printed_text, final name, item_key).
VECTORS = [
    (
        "spar",
        "Čaj  zeleni 0,5l ß",
        "spar:Caj zeleni 0,5l ss",
        "f8b02898-1bae-5aba-82b3-b18527e6c93c",
    ),
    (
        "kaufland",
        "MLIJEKO 2,8% 1L",
        "kaufland:MLIJEKO 2,8% 1L",
        "529c0b4c-0a9e-5c2c-afb4-25f11ea018e8",
    ),
    (
        "lidl",
        "  Jogurt​ voćni\t150g ",
        "lidl:Jogurt vocni 150g",
        "a9189539-4c4e-57f6-91af-20ae2f1753ee",
    ),
    ("dm", "Žličica", "dm:Zlicica", "26f8975f-52f9-5819-9103-a13e8ae3c591"),
    ("dm", "ŽLIČICA", "dm:ZLICICA", "7881c082-cb8c-5b31-a584-28942ee26c99"),
]


def _key(conn: Conn, chain: str, printed_text: str | None) -> object:
    row = conn.execute(
        "SELECT retail_receipts_import.item_key(%s, %s)", (chain, printed_text)
    ).fetchone()
    assert row is not None
    return row[0]


def _receipt(texts: list[str], chain_id: str = "spar") -> NormalizedReceipt:
    lines = [
        ReceiptLine(printed_text=text, quantity=Decimal("1"), printed_amount=Decimal("1.00"))
        for text in texts
    ]
    paid = Decimal(len(texts))
    return NormalizedReceipt(
        payload_version=1,
        chain_id=chain_id,
        store_name="SPAR",
        purchased_at=datetime(2026, 10, 24, 10, 34, tzinfo=UTC),
        total=paid,
        lines=lines,
        settlements=[Settlement(kind=SettlementKind.CARD, printed_text="KARTICA", amount=paid)],
    )


def _line_keys(conn: Conn, receipt_id: uuid.UUID) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT printed_text, item_key FROM resolver_v1.receipt_lines"
        " WHERE receipt_id = %s ORDER BY line_no",
        (receipt_id,),
    ).fetchall()


def test_uuid_generate_v5_matches_published_vectors(receipts_conn: Conn) -> None:
    row = receipts_conn.execute(
        "SELECT public.uuid_generate_v5(public.uuid_ns_dns(), 'www.example.com'),"
        " public.uuid_generate_v5(public.uuid_ns_url(), 'http://python.org/'),"
        " public.uuid_generate_v5(public.uuid_ns_url(), %s)",
        ("spar:Čaj zeleni 0,5l ß",),
    ).fetchone()
    assert row == (
        uuid.UUID("2ed6657d-e927-568b-95e1-2665a8aea6a2"),
        uuid.UUID("4c565f0d-3f5a-5890-b41b-20cf47701c5e"),
        uuid.UUID("165b574d-f4c8-528e-b1a8-7b8651ade646"),
    )


@pytest.mark.parametrize(("chain", "printed_text", "name", "expected"), VECTORS)
def test_item_key_vectors(
    receipts_conn: Conn, chain: str, printed_text: str, name: str, expected: str
) -> None:
    # The Python side of the contract: uuid5 over the final name in the URL namespace.
    assert uuid.uuid5(uuid.NAMESPACE_URL, name) == uuid.UUID(expected)
    assert _key(receipts_conn, chain, printed_text) == uuid.UUID(expected)


def test_item_key_is_immutable_strict_and_search_path_free(receipts_conn: Conn) -> None:
    row = receipts_conn.execute(
        "SELECT provolatile, proparallel, proisstrict FROM pg_proc"
        " WHERE oid = 'retail_receipts_import.item_key(text, text)'::regprocedure"
    ).fetchone()
    assert row == ("i", "s", True)
    assert _key(receipts_conn, "spar", None) is None
    with receipts_conn.transaction():
        receipts_conn.execute("SET LOCAL search_path = ''")
        assert _key(receipts_conn, "dm", "Žličica") == uuid.UUID(VECTORS[3][3])


def test_insert_sets_item_key_and_overrides_a_supplied_one(receipts_conn: Conn) -> None:
    receipt_id = uuid.uuid7()
    write_receipt(
        receipts_conn,
        receipt_id,
        _receipt(["Čaj  zeleni 0,5l ß", "Žličica"]),
        telegram_source(1, 1, "Ana"),
    )
    assert _line_keys(receipts_conn, receipt_id) == [
        ("Čaj  zeleni 0,5l ß", _key(receipts_conn, "spar", "Čaj  zeleni 0,5l ß")),
        ("Žličica", _key(receipts_conn, "spar", "Žličica")),
    ]
    assert _line_keys(receipts_conn, receipt_id)[0][1] == uuid.UUID(VECTORS[0][3])

    line_id = uuid.uuid7()
    receipts_conn.execute(
        f"INSERT INTO {SCHEMA}.receipt_lines (line_id, receipt_id, line_no, printed_text,"
        " quantity, printed_amount, included_discount, separate_discount, item_key)"
        " VALUES (%s, %s, 3, 'Kruh', 1, 1.00, 0, 0, %s)",
        (line_id, receipt_id, uuid.uuid4()),
    )
    stored = receipts_conn.execute(
        f"SELECT item_key FROM {SCHEMA}.receipt_lines WHERE line_id = %s", (line_id,)
    ).fetchone()
    assert stored == (_key(receipts_conn, "spar", "Kruh"),)


def test_printed_text_changes_rekey_the_line(receipts_conn: Conn) -> None:
    receipt_id = uuid.uuid7()
    write_receipt(
        receipts_conn,
        receipt_id,
        _receipt(["A", "B", "C"], chain_id="kaufland"),
        telegram_source(1, 1, "Ana"),
    )

    receipts_conn.execute(
        f"UPDATE {SCHEMA}.receipt_lines SET printed_text = 'MLIJEKO 2,8% 1L'"
        " WHERE receipt_id = %s AND line_no = 1",
        (receipt_id,),
    )
    line_2 = receipts_conn.execute(
        f"SELECT line_id FROM {SCHEMA}.receipt_lines WHERE receipt_id = %s AND line_no = 2",
        (receipt_id,),
    ).fetchone()
    assert line_2 is not None
    receipts_conn.execute(
        "CALL retail_receipts_import.update_line_printed_text(%s, %s)", (line_2[0], "Žličica")
    )
    receipts_conn.execute(
        "CALL retail_receipts_import.update_line_printed_text(%s, %s, %s)",
        (receipt_id, 3, "ŽLIČICA"),
    )

    assert _line_keys(receipts_conn, receipt_id) == [
        ("MLIJEKO 2,8% 1L", uuid.UUID(VECTORS[1][3])),
        ("Žličica", _key(receipts_conn, "kaufland", "Žličica")),
        ("ŽLIČICA", _key(receipts_conn, "kaufland", "ŽLIČICA")),
    ]


def test_item_key_is_not_null(receipts_conn: Conn) -> None:
    receipt_id = uuid.uuid7()
    write_receipt(receipts_conn, receipt_id, _receipt(["A"]), telegram_source(1, 1, "Ana"))
    # The trigger ignores updates that leave printed_text alone, so this reaches the constraint.
    with pytest.raises(errors.NotNullViolation):
        receipts_conn.execute(
            f"UPDATE {SCHEMA}.receipt_lines SET item_key = NULL WHERE receipt_id = %s",
            (receipt_id,),
        )


def test_view_exposes_item_key_last_as_uuid(receipts_conn: Conn) -> None:
    columns = receipts_conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = 'resolver_v1' AND table_name = 'receipt_lines'"
        " ORDER BY ordinal_position"
    ).fetchall()
    assert columns[-1] == ("item_key", "uuid")
    assert len(columns) == 14


def test_migration_0007_backfills_existing_lines(migrate_conn: Conn, tmp_path: Path) -> None:
    for migration in sorted((REPO / "migrations").glob("000[1-6]_*.sql")):
        (tmp_path / migration.name).write_bytes(migration.read_bytes())
    apply_migrations(migrate_conn, tmp_path)

    cases = [
        ("spar", datetime(2026, 10, 24, 10, 34, tzinfo=UTC), VECTORS[0]),
        ("lidl", datetime(2026, 10, 24, 11, 0, tzinfo=UTC), VECTORS[2]),
    ]
    for chain_id, purchased_at, (_, printed_text, _, _) in cases:
        receipt_id = uuid.uuid7()
        migrate_conn.execute(
            f"INSERT INTO {SCHEMA}.receipts (receipt_id, chain_id, store_name, currency,"
            " purchased_at, buyer_name, source_kind, source_ref, total)"
            " VALUES (%s, %s, 'X', 'EUR', %s, 'Ana', 'telegram', %s, 1.00)",
            (receipt_id, chain_id, purchased_at, str(receipt_id)),
        )
        migrate_conn.execute(
            f"INSERT INTO {SCHEMA}.receipt_lines (line_id, receipt_id, line_no, printed_text,"
            " quantity, printed_amount, included_discount, separate_discount)"
            " VALUES (%s, %s, 1, %s, 1.000, 1.00, 0, 0)",
            (uuid.uuid7(), receipt_id, printed_text),
        )

    assert "0007_receipt_line_item_key.sql" in apply_migrations(migrate_conn, REPO / "migrations")

    rows = migrate_conn.execute(
        "SELECT printed_text, item_key FROM resolver_v1.receipt_lines"
    ).fetchall()
    assert {row[0]: row[1] for row in rows} == {
        VECTORS[0][1]: uuid.UUID(VECTORS[0][3]),
        VECTORS[2][1]: uuid.UUID(VECTORS[2][3]),
    }
