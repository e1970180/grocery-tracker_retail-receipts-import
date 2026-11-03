from typing import Any, cast

import psycopg
import pytest
from psycopg import errors

from retail_receipts_import.adapters.postgres.chains import (
    ChainReferenceError,
    RejectedRow,
    RejectReason,
    read_chain_reference,
)
from retail_receipts_import.domain.chains import KnownChain
from tests.conftest import REPO

Conn = psycopg.Connection[tuple[Any, ...]]
CONTRACT_SQL = REPO / "docs" / "contracts" / "chains_v1.sql"
SEEDED_IDS = ["dm", "kaufland", "lidl", "mueller", "spar"]


class _FailingConnection:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def execute(self, query: str) -> None:
        raise self.error


def _read_failing(error: Exception) -> None:
    read_chain_reference(cast(Conn, _FailingConnection(error)))


class _RowsConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def execute(self, query: str) -> _RowsConnection:
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def _read_rows(
    country_code: object, tax_numbers: object, aliases: object = ("A",)
) -> tuple[list[KnownChain], list[RejectedRow]]:
    # Aliases arrive from psycopg as a list.
    row = ("c", "C", list(cast(Any, aliases)), country_code, tax_numbers, True)
    reference = read_chain_reference(cast(Conn, _RowsConnection([row])))
    return list(reference.chains), list(reference.rejected)


@pytest.mark.parametrize(
    ("country_code", "tax_numbers", "expected"),
    [
        ("HR", ["46108893754"], ("46108893754",)),
        ("HR", ["46108893754", "94124811986"], ("46108893754", "94124811986")),
        ("HR", None, ()),
        ("HR", [], ()),
        ("DE", ["DE123"], ("DE123",)),
        ("DE", [" DE1"], (" DE1",)),
        ("DE", None, ()),
    ],
)
def test_valid_country_and_tax_numbers_are_accepted(
    country_code: str, tax_numbers: object, expected: tuple[str, ...]
) -> None:
    chains, rejected = _read_rows(country_code, tax_numbers)
    assert rejected == []
    assert chains == [KnownChain("c", "C", ("A",), country_code, expected)]


def test_null_country_is_reported_before_bad_aliases() -> None:
    chains, rejected = _read_rows(None, None, aliases=("A", ""))
    assert chains == []
    assert rejected == [RejectedRow("c", RejectReason.NULL_FIELD)]


@pytest.mark.parametrize(
    ("country_code", "tax_numbers", "reason"),
    [
        ("HR", ["12345"], RejectReason.BAD_TAX_NUMBERS),
        ("HR", ["46108893754", "123"], RejectReason.BAD_TAX_NUMBERS),
        ("HR", ["4610889375²"], RejectReason.BAD_TAX_NUMBERS),
        ("DE", [""], RejectReason.BAD_TAX_NUMBERS),
        ("DE", ["  "], RejectReason.BAD_TAX_NUMBERS),
        ("DE", ["a,b"], RejectReason.BAD_TAX_NUMBERS),
        ("DE", [None], RejectReason.BAD_TAX_NUMBERS),
        ("DE", [1], RejectReason.BAD_TAX_NUMBERS),
        ("DE", [["x"]], RejectReason.BAD_TAX_NUMBERS),
        ("DE", "{DE1}", RejectReason.BAD_TAX_NUMBERS),
        ("hr", ["46108893754"], RejectReason.BAD_COUNTRY_CODE),
        ("HRV", None, RejectReason.BAD_COUNTRY_CODE),
        ("", None, RejectReason.BAD_COUNTRY_CODE),
        ("H\n", None, RejectReason.BAD_COUNTRY_CODE),
        (3, None, RejectReason.BAD_COUNTRY_CODE),
        ("hr", ["12345"], RejectReason.BAD_COUNTRY_CODE),
        (None, None, RejectReason.NULL_FIELD),
    ],
)
def test_bad_country_or_tax_numbers_are_rejected(
    country_code: object, tax_numbers: object, reason: RejectReason
) -> None:
    chains, rejected = _read_rows(country_code, tax_numbers)
    assert chains == []
    assert rejected == [RejectedRow("c", reason)]


@pytest.mark.parametrize(
    "error",
    [
        errors.UndefinedTable("no view"),
        errors.InvalidSchemaName("no schema"),
        errors.UndefinedColumn("no column"),
        errors.InsufficientPrivilege("no select"),
    ],
)
def test_structural_fault_becomes_chain_reference_error(error: psycopg.Error) -> None:
    with pytest.raises(ChainReferenceError) as caught:
        _read_failing(error)
    assert caught.value.__cause__ is error


@pytest.mark.parametrize(
    "error",
    [
        psycopg.OperationalError("connection lost"),
        errors.AdminShutdown("terminating connection"),
        errors.QueryCanceled("statement timeout"),
    ],
)
def test_other_errors_propagate_unchanged(error: psycopg.Error) -> None:
    with pytest.raises(type(error)) as caught:
        _read_failing(error)
    assert caught.value is error


@pytest.fixture
def chains_conn(pg_conn: Conn) -> Conn:
    """The test connection with the contract's reference seeded inside its transaction."""
    existing = pg_conn.execute(
        "SELECT to_regclass('public.chains'), to_regclass('public.chains_v1')"
    ).fetchone()
    if existing != (None, None):
        pytest.fail(f"the test database already holds a chain reference: {existing}")
    pg_conn.execute(CONTRACT_SQL.read_text(encoding="utf-8"))
    return pg_conn


def _add_unchecked_rows(conn: Conn, rows: list[tuple[Any, ...]]) -> None:
    """Rows the contract table's constraints would refuse, served through the same view."""
    conn.execute(
        "CREATE TABLE public.chains_unchecked "
        "(chain_id text, display_name text, aliases text[], country_code text, "
        "tax_numbers text[], active boolean)"
    )
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO public.chains_unchecked VALUES (%s, %s, %s, %s, %s, %s)", rows)
    columns = "chain_id, display_name, aliases, country_code, tax_numbers, active"
    conn.execute(
        "CREATE OR REPLACE VIEW public.chains_v1 AS "
        f"SELECT {columns} FROM public.chains "
        "UNION ALL "
        f"SELECT {columns} FROM public.chains_unchecked"
    )


def _ids(conn: Conn) -> list[str]:
    return [chain.chain_id for chain in read_chain_reference(conn).chains]


@pytest.mark.integration
def test_reads_seeded_chains_in_order(chains_conn: Conn) -> None:
    reference = read_chain_reference(chains_conn)
    assert [chain.chain_id for chain in reference.chains] == SEEDED_IDS
    assert reference.rejected == ()
    assert reference.inactive_ids == ()
    spar = reference.chains[-1]
    assert spar == KnownChain("spar", "Spar", ("SPAR", "Spar", "INTERSPAR"), "HR", ("46108893754",))


@pytest.mark.integration
def test_inactive_chain_is_left_out(chains_conn: Conn) -> None:
    chains_conn.execute("UPDATE public.chains SET active = false WHERE chain_id = 'lidl'")
    reference = read_chain_reference(chains_conn)
    assert [chain.chain_id for chain in reference.chains] == ["dm", "kaufland", "mueller", "spar"]
    assert reference.inactive_ids == ("lidl",)
    assert reference.rejected == ()


@pytest.mark.integration
def test_bad_rows_are_rejected_and_valid_chains_kept(chains_conn: Conn) -> None:
    valid_oibs = ["46108893754"]
    _add_unchecked_rows(
        chains_conn,
        [
            ("Spar", "Spar", ["SPAR"], "HR", valid_oibs, True),
            ("other", "Other", [], "HR", valid_oibs, True),
            ("nameless", None, ["N"], "HR", valid_oibs, True),
            ("x", "X", ["X"], "HR", valid_oibs, True),
            ("x", "X again", ["X"], "HR", valid_oibs, False),
            (None, "No id", [], "HR", valid_oibs, True),
            ("unflagged", "Unflagged", [], "HR", valid_oibs, None),
            ("blank_alias", "Blank alias", ["B", ""], "HR", valid_oibs, True),
            ("null_aliases", "Null aliases", None, "HR", valid_oibs, True),
            ("short_oib", "Short OIB", ["S"], "HR", ["12345"], True),
            ("null_country", "Null country", ["N"], None, valid_oibs, True),
            ("bad_country", "Bad country", ["B"], "hr", valid_oibs, True),
            # No identifiers is valid, in HR as well as elsewhere.
            ("empty_oibs", "Empty OIBs", ["E"], "HR", [], True),
            ("null_oibs", "Null OIBs", ["N"], "HR", None, True),
            ("german", "German", ["G"], "DE", ["DE123"], True),
        ],
    )
    reference = read_chain_reference(chains_conn)
    assert [chain.chain_id for chain in reference.chains] == sorted(
        [*SEEDED_IDS, "empty_oibs", "null_oibs", "german"]
    )
    assert reference.inactive_ids == ()
    assert sorted(reference.rejected, key=repr) == sorted(
        [
            RejectedRow("Spar", RejectReason.INVALID_SLUG),
            RejectedRow("other", RejectReason.RESERVED_ID),
            RejectedRow("nameless", RejectReason.NULL_FIELD),
            RejectedRow("x", RejectReason.DUPLICATE_ID),
            RejectedRow("x", RejectReason.DUPLICATE_ID),
            RejectedRow(None, RejectReason.NULL_FIELD),
            RejectedRow("unflagged", RejectReason.NULL_FIELD),
            RejectedRow("blank_alias", RejectReason.BAD_ALIASES),
            RejectedRow("null_aliases", RejectReason.NULL_FIELD),
            RejectedRow("short_oib", RejectReason.BAD_TAX_NUMBERS),
            RejectedRow("null_country", RejectReason.NULL_FIELD),
            RejectedRow("bad_country", RejectReason.BAD_COUNTRY_CODE),
        ],
        key=repr,
    )


@pytest.mark.integration
def test_text_aliases_column_is_rejected_not_split(chains_conn: Conn) -> None:
    chains_conn.execute("DROP VIEW public.chains_v1")
    chains_conn.execute(
        "CREATE VIEW public.chains_v1 AS "
        "SELECT chain_id, display_name, aliases::text AS aliases, country_code, "
        "tax_numbers, active "
        "FROM public.chains"
    )
    reference = read_chain_reference(chains_conn)
    assert reference.chains == ()
    assert {row.reason for row in reference.rejected} == {RejectReason.BAD_ALIASES}


@pytest.mark.integration
def test_text_tax_numbers_column_is_rejected_not_split(chains_conn: Conn) -> None:
    chains_conn.execute("DROP VIEW public.chains_v1")
    chains_conn.execute(
        "CREATE VIEW public.chains_v1 AS "
        "SELECT chain_id, display_name, aliases, country_code, "
        "tax_numbers::text AS tax_numbers, active "
        "FROM public.chains"
    )
    reference = read_chain_reference(chains_conn)
    assert reference.chains == ()
    assert {row.reason for row in reference.rejected} == {RejectReason.BAD_TAX_NUMBERS}


@pytest.mark.integration
def test_non_text_chain_id_is_rejected_per_row(chains_conn: Conn) -> None:
    chains_conn.execute("DROP VIEW public.chains_v1")
    chains_conn.execute(
        "CREATE VIEW public.chains_v1 AS "
        "SELECT length(chain_id) AS chain_id, display_name, aliases, country_code, "
        "tax_numbers, active "
        "FROM public.chains"
    )
    reference = read_chain_reference(chains_conn)
    assert reference.chains == ()
    assert {row.reason for row in reference.rejected} == {RejectReason.INVALID_SLUG}


@pytest.mark.integration
def test_missing_view_raises(chains_conn: Conn) -> None:
    chains_conn.execute("DROP VIEW public.chains_v1")
    with pytest.raises(ChainReferenceError) as caught:
        read_chain_reference(chains_conn)
    assert isinstance(caught.value.__cause__, errors.UndefinedTable)


@pytest.mark.integration
def test_missing_column_raises(chains_conn: Conn) -> None:
    chains_conn.execute("DROP VIEW public.chains_v1")
    chains_conn.execute(
        "CREATE VIEW public.chains_v1 AS SELECT chain_id, display_name, active FROM public.chains"
    )
    with pytest.raises(ChainReferenceError) as caught:
        read_chain_reference(chains_conn)
    assert isinstance(caught.value.__cause__, errors.UndefinedColumn)


@pytest.mark.integration
def test_missing_select_raises(chains_conn: Conn) -> None:
    # Role and SET ROLE both vanish with the fixture's rollback.
    chains_conn.execute("CREATE ROLE rri_test_no_select NOLOGIN")
    chains_conn.execute("SET ROLE rri_test_no_select")
    with pytest.raises(ChainReferenceError) as caught:
        read_chain_reference(chains_conn)
    assert isinstance(caught.value.__cause__, errors.InsufficientPrivilege)
