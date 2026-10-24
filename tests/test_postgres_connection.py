"""Tests PostgreSQL connection-error classification predicate."""

import psycopg
import pytest
from psycopg import errors

from retail_receipts_import.adapters.postgres import is_connection_error


def _with_sqlstate(exc: psycopg.Error, sqlstate: str) -> psycopg.Error:
    # Assigns the SQLSTATE code on the error instance for classification testing.
    exc.sqlstate = sqlstate
    return exc


@pytest.mark.parametrize(
    "exc",
    [
        psycopg.OperationalError("server closed the connection unexpectedly"),
        psycopg.InterfaceError("connection already closed"),
        _with_sqlstate(psycopg.OperationalError("connection failed"), "08006"),
        _with_sqlstate(psycopg.OperationalError("client unable to connect"), "08001"),
        _with_sqlstate(psycopg.OperationalError("connection exception"), "08000"),
        _with_sqlstate(psycopg.OperationalError("admin shutdown"), "57P01"),
        _with_sqlstate(psycopg.OperationalError("crash shutdown"), "57P02"),
        _with_sqlstate(psycopg.OperationalError("cannot connect now"), "57P03"),
        errors.AdminShutdown("terminating connection"),
        errors.CrashShutdown("server crashed"),
        errors.CannotConnectNow("recovery in progress"),
        errors.ConnectionFailure("connection lost"),
    ],
    ids=[
        "operational-no-sqlstate",
        "interface-no-sqlstate",
        "sqlstate-08006",
        "sqlstate-08001",
        "sqlstate-08000",
        "sqlstate-57P01",
        "sqlstate-57P02",
        "sqlstate-57P03",
        "errors-admin-shutdown",
        "errors-crash-shutdown",
        "errors-cannot-connect-now",
        "errors-connection-failure",
    ],
)
def test_connection_class_errors_are_true(exc: Exception) -> None:
    assert is_connection_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        psycopg.ProgrammingError("syntax error"),
        _with_sqlstate(psycopg.ProgrammingError("table missing"), "42P01"),
        _with_sqlstate(psycopg.OperationalError("query canceled"), "57014"),
        errors.QueryCanceled("canceling statement"),
        psycopg.DataError("value out of range"),
        _with_sqlstate(psycopg.DataError("string length error"), "22001"),
        psycopg.IntegrityError("unique constraint violated"),
        _with_sqlstate(psycopg.IntegrityError("duplicate key"), "23505"),
        errors.UniqueViolation("duplicate key value"),
        psycopg.InternalError("backend crash"),
        RuntimeError("something else"),
        ConnectionRefusedError("os connection refused"),
        ValueError("bad argument"),
        Exception("generic"),
    ],
    ids=[
        "programming-no-sqlstate",
        "programming-42P01",
        "operational-57014",
        "errors-query-canceled",
        "data-no-sqlstate",
        "data-22001",
        "integrity-no-sqlstate",
        "integrity-23505",
        "errors-unique-violation",
        "internal-no-sqlstate",
        "runtime-error",
        "connection-refused-os-error",
        "value-error",
        "generic-exception",
    ],
)
def test_non_connection_errors_are_false(exc: Exception) -> None:
    assert is_connection_error(exc) is False
