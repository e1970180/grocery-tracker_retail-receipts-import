"""Integration tests for the resolver_v1 feed contract views and access rules."""

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo

from retail_receipts_import.adapters.postgres.receipts import write_receipt
from retail_receipts_import.domain.receipt import (
    NormalizedReceipt,
    ReceiptLine,
    Settlement,
    SettlementKind,
    telegram_source,
)
from retail_receipts_import.migrate import apply_migrations
from tests.conftest import REPO, RESOLVER_SCHEMA, TEST_DSN_VAR

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class ResolverSession:
    admin_conn: psycopg.Connection[tuple[object, ...]]
    resolver_conn: psycopg.Connection[tuple[object, ...]]


@pytest.fixture
def resolver_session(
    migrate_conn: psycopg.Connection[tuple[object, ...]],
) -> Iterator[ResolverSession]:
    """A fresh Resolver login role, provisioned as the admin would, then the repo migrations.

    The grants come only from the default privileges set before the views exist, so the tests
    prove the provisioning path the contract documents, not a grant added afterwards.
    """
    # Roles are cluster-wide and CREATE ROLE has no IF NOT EXISTS, so each test gets its own.
    role_name = f"test_resolver_{uuid.uuid4().hex[:12]}"
    role = sql.Identifier(role_name)
    password = uuid.uuid4().hex
    schema = sql.Identifier(RESOLVER_SCHEMA)
    # The local throwaway database checks passwords while CI trusts every login; set one for both.
    migrate_conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password))
    )
    try:
        migrate_conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role))
        migrate_conn.execute(
            sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(
                schema, role
            )
        )
        apply_migrations(migrate_conn, REPO / "migrations")
        dsn = make_conninfo(os.environ[TEST_DSN_VAR], user=role_name, password=password)
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as resolver_conn:
            yield ResolverSession(admin_conn=migrate_conn, resolver_conn=resolver_conn)
    finally:
        # DROP OWNED removes the role's grants and default privileges so the role can go.
        migrate_conn.execute(sql.SQL("DROP OWNED BY {}").format(role))
        migrate_conn.execute(sql.SQL("DROP ROLE {}").format(role))


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
    store_name: str | None = "SPAR",
    purchased_at: datetime = datetime(2026, 10, 24, 10, 34, tzinfo=UTC),
    **extra: Any,
) -> NormalizedReceipt:
    paid = sum((line.effective_amount for line in lines), Decimal(0))
    return NormalizedReceipt(
        payload_version=1,
        chain_id=chain_id,
        store_name=store_name,
        purchased_at=purchased_at,
        total=Decimal(total) if total is not None else paid,
        lines=lines,
        settlements=settlements if settlements is not None else [_card(str(paid))],
        **extra,
    )


def test_cursor_orders_and_filters_feed(resolver_session: ResolverSession) -> None:
    r1 = write_receipt(
        resolver_session.admin_conn,
        uuid.uuid7(),
        _receipt(
            [_line("A")],
            chain_id="spar",
            purchased_at=datetime(2026, 7, 15, 10, 0, tzinfo=UTC),
        ),
        telegram_source(1, 1, "Ana"),
    )
    r2 = write_receipt(
        resolver_session.admin_conn,
        uuid.uuid7(),
        _receipt(
            [_line("B")],
            chain_id="spar",
            purchased_at=datetime(2026, 7, 15, 11, 0, tzinfo=UTC),
        ),
        telegram_source(1, 2, "Ana"),
    )
    r3 = write_receipt(
        resolver_session.admin_conn,
        uuid.uuid7(),
        _receipt(
            [_line("C")],
            chain_id="spar",
            purchased_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
        ),
        telegram_source(1, 3, "Ana"),
    )

    rows = resolver_session.resolver_conn.execute(
        "SELECT seq, receipt_id, event FROM resolver_v1.feed WHERE seq > 1 ORDER BY seq"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (2, r2.receipt_id, "stored")
    assert rows[1] == (3, r3.receipt_id, "stored")
    assert r1.receipt_id != r2.receipt_id


def test_stored_summer_timestamps_and_money(resolver_session: ResolverSession) -> None:
    # 2026-07-15 14:05 Zagreb is UTC+2 (CEST), so 12:05:00 UTC.
    purchased_at = datetime(2026, 7, 15, 12, 5, tzinfo=UTC)
    receipt_id = uuid.uuid7()
    write_receipt(
        resolver_session.admin_conn,
        receipt_id,
        _receipt([_line("Kruh", printed="1.50")], purchased_at=purchased_at),
        telegram_source(1, 1, "Ana"),
    )

    row = resolver_session.resolver_conn.execute(
        "SELECT purchased_at, purchased_at_local FROM resolver_v1.receipts WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()
    assert row == ("2026-07-15T12:05:00Z", "2026-07-15T14:05:00+02:00")

    line_row = resolver_session.resolver_conn.execute(
        "SELECT printed_amount FROM resolver_v1.receipt_lines WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()
    assert line_row == ("1.50",)


def test_winter_timestamps_offset(resolver_session: ResolverSession) -> None:
    # 2026-01-15 14:05 Zagreb is UTC+1 (CET), so 13:05:00 UTC.
    purchased_at = datetime(2026, 1, 15, 13, 5, tzinfo=UTC)
    receipt_id = uuid.uuid7()
    write_receipt(
        resolver_session.admin_conn,
        receipt_id,
        _receipt([_line("Kruh", printed="2.00")], purchased_at=purchased_at),
        telegram_source(1, 1, "Ana"),
    )

    row = resolver_session.resolver_conn.execute(
        "SELECT purchased_at, purchased_at_local FROM resolver_v1.receipts WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()
    assert row == ("2026-01-15T13:05:00Z", "2026-01-15T14:05:00+01:00")


def test_session_tz_independence(resolver_session: ResolverSession) -> None:
    purchased_at = datetime(2026, 7, 15, 12, 5, tzinfo=UTC)
    receipt_id = uuid.uuid7()
    write_receipt(
        resolver_session.admin_conn,
        receipt_id,
        _receipt([_line("Kruh", printed="1.50")], purchased_at=purchased_at),
        telegram_source(1, 1, "Ana"),
    )

    utc_row = resolver_session.resolver_conn.execute(
        "SELECT purchased_at, purchased_at_local FROM resolver_v1.receipts WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()

    resolver_session.resolver_conn.execute("SET TimeZone = 'America/New_York'")
    ny_row = resolver_session.resolver_conn.execute(
        "SELECT purchased_at, purchased_at_local FROM resolver_v1.receipts WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()

    assert ny_row == utc_row
    assert ny_row == ("2026-07-15T12:05:00Z", "2026-07-15T14:05:00+02:00")


def test_internal_tables_refused(resolver_session: ResolverSession) -> None:
    with pytest.raises(errors.InsufficientPrivilege) as exc_receipts:
        resolver_session.resolver_conn.execute("SELECT * FROM retail_receipts_import.receipts")
    assert exc_receipts.value.sqlstate == "42501"

    with pytest.raises(errors.InsufficientPrivilege) as exc_migrations:
        resolver_session.resolver_conn.execute(
            "SELECT * FROM retail_receipts_import.schema_migrations"
        )
    assert exc_migrations.value.sqlstate == "42501"

    for table in ("receipt_lines", "receipt_settlements", "receipt_feed"):
        with pytest.raises(errors.InsufficientPrivilege):
            resolver_session.resolver_conn.execute(
                sql.SQL("SELECT * FROM retail_receipts_import.{}").format(sql.Identifier(table))
            )


def test_stored_receipt_read_back_field_by_field(resolver_session: ResolverSession) -> None:
    receipt_id = uuid.uuid7()
    lines = [
        _line(
            text="Čokolada",
            quantity="2.500",
            printed="3.00",
            included="0.50",
            separate="0.20",
            unit="kom",
            unit_price=Decimal("1.20"),
            discount_text="Akcija",
        )
    ]
    settlements = [
        Settlement(kind=SettlementKind.COUPON, printed_text="KUPON", amount=Decimal("0.80")),
        Settlement(kind=SettlementKind.CARD, printed_text="KARTICA", amount=Decimal("2.00")),
    ]
    purchased_at = datetime(2026, 7, 15, 12, 5, tzinfo=UTC)
    receipt = NormalizedReceipt(
        payload_version=1,
        chain_id="spar",
        store_name="SPAR",
        branch_number="042",
        receipt_number="12345/01",
        store_address="Slavonska avenija 11, Zagreb",
        loyalty_card_number="**** 9999",
        purchased_at=purchased_at,
        total=Decimal("2.00"),
        lines=lines,
        settlements=settlements,
    )
    write_receipt(
        resolver_session.admin_conn,
        receipt_id,
        receipt,
        telegram_source(1, 1, "Ana"),
    )

    header = resolver_session.resolver_conn.execute(
        "SELECT receipt_id, chain_id, store_name, branch_number, receipt_number, store_address,"
        " currency, purchased_at, purchased_at_local, buyer_name"
        " FROM resolver_v1.receipts WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()
    assert header == (
        receipt_id,
        "spar",
        "SPAR",
        "042",
        "12345/01",
        "Slavonska avenija 11, Zagreb",
        "EUR",
        "2026-07-15T12:05:00Z",
        "2026-07-15T14:05:00+02:00",
        "Ana",
    )

    line = resolver_session.resolver_conn.execute(
        "SELECT line_id, receipt_id, line_no, printed_text, quantity, unit, unit_price,"
        " printed_amount, included_discount, separate_discount, discount_text,"
        " regular_amount, effective_amount"
        " FROM resolver_v1.receipt_lines WHERE receipt_id = %s",
        (receipt_id,),
    ).fetchone()
    assert line is not None
    assert isinstance(line[0], uuid.UUID) and line[0].version == 7
    assert line[1] == receipt_id
    assert line[2] == 1
    assert line[3] == "Čokolada"
    assert line[4] == "2.500"
    assert line[5] == "kom"
    assert line[6] == "1.20"
    assert line[7] == "3.00"
    assert line[8] == "0.50"
    assert line[9] == "0.20"
    assert line[10] == "Akcija"
    assert line[11] == "3.50"
    assert line[12] == "2.80"

    settled = resolver_session.resolver_conn.execute(
        "SELECT receipt_id, settlement_no, kind, printed_text, amount"
        " FROM resolver_v1.receipt_settlements WHERE receipt_id = %s ORDER BY settlement_no",
        (receipt_id,),
    ).fetchall()
    assert settled == [
        (receipt_id, 1, "coupon", "KUPON", "0.80"),
        (receipt_id, 2, "card", "KARTICA", "2.00"),
    ]


def test_deleted_receipt_leaves_only_its_feed_events(resolver_session: ResolverSession) -> None:
    receipt_id = uuid.uuid7()
    write_receipt(
        resolver_session.admin_conn,
        receipt_id,
        _receipt([_line("Kruh")]),
        telegram_source(1, 1, "Ana"),
    )
    # The delete command does not exist yet; this is the one transaction it is meant to run.
    with resolver_session.admin_conn.transaction():
        resolver_session.admin_conn.execute(
            "DELETE FROM retail_receipts_import.receipts WHERE receipt_id = %s", (receipt_id,)
        )
        resolver_session.admin_conn.execute(
            "INSERT INTO retail_receipts_import.receipt_feed (receipt_id, event)"
            " VALUES (%s, 'deleted')",
            (receipt_id,),
        )

    events = resolver_session.resolver_conn.execute(
        "SELECT event FROM resolver_v1.feed WHERE receipt_id = %s ORDER BY seq", (receipt_id,)
    ).fetchall()
    assert events == [("stored",), ("deleted",)]
    for view in ("receipts", "receipt_lines", "receipt_settlements"):
        count = resolver_session.resolver_conn.execute(
            sql.SQL("SELECT count(*) FROM resolver_v1.{} WHERE receipt_id = %s").format(
                sql.Identifier(view)
            ),
            (receipt_id,),
        ).fetchone()
        assert count == (0,), view


def test_schema_comment_identifies_resolver_contract(
    resolver_session: ResolverSession,
) -> None:
    row = resolver_session.resolver_conn.execute(
        "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace"
        " WHERE nspname = 'resolver_v1'"
    ).fetchone()
    assert row == ("Resolver feed contract resolver_v1",)
