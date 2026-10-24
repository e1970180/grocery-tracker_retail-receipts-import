"""Stores a normalized receipt in one transaction, and tells its own rerun from a duplicate."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import psycopg
from psycopg import errors

from retail_receipts_import.domain.receipt import (
    ItemsSettlementMismatch,
    NormalizedReceipt,
    ReceiptLine,
    ReceiptSource,
    Settlement,
    TotalSettlementMismatch,
    check_consistency,
    check_total,
)

log = logging.getLogger(__name__)

# Schema-qualified everywhere: the service role's search_path is not something this code sets.
SCHEMA = "retail_receipts_import"

FIND_BY_SOURCE = (
    f"SELECT receipt_id, source_kind, source_ref FROM {SCHEMA}.receipts"
    " WHERE source_kind = %s AND source_ref = %s"
)
FIND_BY_DEDUP_KEY = (
    f"SELECT receipt_id, source_kind, source_ref FROM {SCHEMA}.receipts"
    " WHERE chain_id = %s AND purchased_at = %s"
)
INSERT_RECEIPT = (
    f"INSERT INTO {SCHEMA}.receipts (receipt_id, chain_id, store_name, branch_number,"
    " receipt_number, store_address, loyalty_card_number, currency, purchased_at,"
    " total, buyer_name, source_kind, source_ref)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
# The generated amount columns are left out on purpose: they cannot drift from their sources.
INSERT_LINE = (
    f"INSERT INTO {SCHEMA}.receipt_lines (line_id, receipt_id, line_no, printed_text, quantity,"
    " unit, unit_price, printed_amount, included_discount, separate_discount, discount_text)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
INSERT_SETTLEMENT = (
    f"INSERT INTO {SCHEMA}.receipt_settlements (receipt_id, settlement_no, kind, printed_text,"
    " amount) VALUES (%s, %s, %s, %s, %s)"
)
INSERT_FEED_STORED = f"INSERT INTO {SCHEMA}.receipt_feed (receipt_id, event) VALUES (%s, 'stored')"


class WriteKind(StrEnum):
    STORED = "stored"
    OWN_WRITE = "own_write"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class StoredRef:
    receipt_id: uuid.UUID
    source_kind: str
    source_ref: str


@dataclass(frozen=True)
class WriteResult:
    kind: WriteKind
    # For a duplicate or own write, the receipt that is already stored.
    receipt_id: uuid.UUID


def find_by_source(
    conn: psycopg.Connection[tuple[Any, ...]], source: ReceiptSource
) -> StoredRef | None:
    row = conn.execute(FIND_BY_SOURCE, (source.kind.value, source.ref)).fetchone()
    return _stored_ref(row)


def find_by_dedup_key(
    conn: psycopg.Connection[tuple[Any, ...]], chain_id: str, purchased_at: datetime
) -> StoredRef | None:
    row = conn.execute(FIND_BY_DEDUP_KEY, (chain_id, purchased_at)).fetchone()
    return _stored_ref(row)


def find_other_source(
    conn: psycopg.Connection[tuple[Any, ...]],
    chain_id: str,
    purchased_at: datetime,
    source: ReceiptSource,
) -> uuid.UUID | None:
    """The receipt another source stored under this dedup key, for the early duplicate check.

    Advisory only: a failed lookup answers None and the writer's unique constraint decides later.
    The key's own source is no hit, because the writer turns that into the job's own write.
    """
    try:
        found = find_by_dedup_key(conn, chain_id, purchased_at)
    except psycopg.Error as exc:
        # The type alone: nothing from the connection may reach the log.
        log.warning("dedup pre-check lookup failed (%s), continuing without it", type(exc).__name__)
        return None
    if found is None or (found.source_kind, found.source_ref) == (source.kind.value, source.ref):
        return None
    return found.receipt_id


def write_receipt(
    conn: psycopg.Connection[tuple[Any, ...]],
    receipt_id: uuid.UUID,
    receipt: NormalizedReceipt,
    source: ReceiptSource,
) -> WriteResult:
    """Stores the receipt, or reports that it is already stored. Nothing is written otherwise.

    `conn` must be in autocommit: inside an outer transaction a savepoint would report STORED
    before the commit that makes it real.
    """
    if not conn.autocommit:
        raise ValueError("write_receipt needs an autocommit connection")
    # Before any SQL, so a receipt that does not add up never reaches the database.
    if difference := check_consistency(receipt):
        raise ItemsSettlementMismatch(difference)
    if difference := check_total(receipt):
        raise TotalSettlementMismatch(difference)

    existing = _existing(conn, receipt, source)
    if existing is not None:
        return existing

    try:
        with conn.transaction():
            _insert_receipt(conn, receipt_id, receipt, source)
            _insert_lines(conn, receipt_id, receipt.stored_lines())
            _insert_settlements(conn, receipt_id, receipt.settlements)
            conn.execute(INSERT_FEED_STORED, (receipt_id,))
    except errors.UniqueViolation:
        # A concurrent writer won the race: the transaction is rolled back, so the rerun sees
        # its row. If both lookups still miss, the violation is not ours to explain.
        rerun = _existing(conn, receipt, source)
        if rerun is None:
            raise
        return rerun
    return WriteResult(WriteKind.STORED, receipt_id)


def _existing(
    conn: psycopg.Connection[tuple[Any, ...]], receipt: NormalizedReceipt, source: ReceiptSource
) -> WriteResult | None:
    by_source = find_by_source(conn, source)
    if by_source is not None:
        return WriteResult(WriteKind.OWN_WRITE, by_source.receipt_id)
    by_key = find_by_dedup_key(conn, receipt.chain_id, receipt.purchased_at)
    if by_key is None:
        return None
    # A dedup hit from the same source is our own earlier write, not a second copy of the receipt.
    if (by_key.source_kind, by_key.source_ref) == (source.kind.value, source.ref):
        return WriteResult(WriteKind.OWN_WRITE, by_key.receipt_id)
    return WriteResult(WriteKind.DUPLICATE, by_key.receipt_id)


def _stored_ref(row: tuple[Any, ...] | None) -> StoredRef | None:
    if row is None:
        return None
    return StoredRef(receipt_id=row[0], source_kind=row[1], source_ref=row[2])


def _insert_receipt(
    conn: psycopg.Connection[tuple[Any, ...]],
    receipt_id: uuid.UUID,
    receipt: NormalizedReceipt,
    source: ReceiptSource,
) -> None:
    conn.execute(
        INSERT_RECEIPT,
        (
            receipt_id,
            receipt.chain_id,
            receipt.store_name,
            receipt.branch_number,
            receipt.receipt_number,
            receipt.store_address,
            receipt.loyalty_card_number,
            receipt.currency,
            receipt.purchased_at,
            receipt.total,
            source.buyer_name,
            source.kind.value,
            source.ref,
        ),
    )


def _insert_lines(
    conn: psycopg.Connection[tuple[Any, ...]], receipt_id: uuid.UUID, lines: list[ReceiptLine]
) -> None:
    for line_no, line in enumerate(lines, start=1):
        conn.execute(
            INSERT_LINE,
            (
                uuid.uuid7(),
                receipt_id,
                line_no,
                line.printed_text,
                line.quantity,
                line.unit,
                line.unit_price,
                line.printed_amount,
                line.included_discount,
                line.separate_discount,
                line.discount_text,
            ),
        )


def _insert_settlements(
    conn: psycopg.Connection[tuple[Any, ...]], receipt_id: uuid.UUID, settlements: list[Settlement]
) -> None:
    for settlement_no, settlement in enumerate(settlements, start=1):
        conn.execute(
            INSERT_SETTLEMENT,
            (
                receipt_id,
                settlement_no,
                settlement.kind.value,
                settlement.printed_text,
                settlement.amount,
            ),
        )
