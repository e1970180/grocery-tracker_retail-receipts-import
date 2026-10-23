"""Global pytest fixtures and configuration."""

import os
import socket
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from retail_receipts_import.migrate import SCHEMA, apply_migrations

# A dedicated variable, never libpq's PG* defaults: those may point at the production database.
TEST_DSN_VAR = "RRI_TEST_DATABASE_URL"
REPO = Path(__file__).resolve().parents[1]
TOKEN = "123456:telegram-secret-token"
GEMINI_KEY = "gemini-secret-key"
DB_PASSWORD = "db-secret-password"


@pytest.fixture
def rri_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """A valid dev environment, isolated from the developer's real `.env` and shell."""
    for name in list(os.environ):
        if name.startswith("RRI_") and name != TEST_DSN_VAR:
            monkeypatch.delenv(name)
    # Settings reads `.env` from the working directory; the repo's holds real tokens.
    monkeypatch.chdir(tmp_path)
    values = {
        "RRI_ENV": "dev",
        "RRI_TELEGRAM_BOT_TOKEN": TOKEN,
        "RRI_GEMINI_API_KEY": GEMINI_KEY,
        "RRI_DB_HOST": "db.example",
        "RRI_DB_NAME": "grocery-tracker-dev",
        "RRI_DB_USER": "writer",
        "RRI_DB_PASSWORD": DB_PASSWORD,
        "RRI_TEXTS_PATH": str(REPO / "texts" / "messages.toml"),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


@pytest.fixture(autouse=True)
def block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Block external network connections during unit tests unless marked live or integration."""
    if "live" in request.keywords or "integration" in request.keywords:
        return

    def refused_pg_connect(*args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "PostgreSQL access disabled in unit tests; use @pytest.mark.integration."
        )

    # libpq connects from C, so the socket patch below never sees psycopg.
    monkeypatch.setattr(psycopg, "connect", refused_pg_connect)
    monkeypatch.setattr(psycopg.Connection, "connect", refused_pg_connect)

    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: tuple[str, int] | str | bytes) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "localhost", "::1"):
            real_connect(self, address)
            return
        raise RuntimeError(
            f"Network access disabled in unit tests (attempted connection to {host!r}). "
            "Mark test with @pytest.mark.live to allow."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def migrate_conn() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Autocommit connection to the throwaway test database with a fresh service schema."""
    dsn = os.environ.get(TEST_DSN_VAR)
    if not dsn:
        pytest.fail(f"{TEST_DSN_VAR} is not set; integration tests need a test PostgreSQL database")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as conn:
        # The fixture drops the real service schema; never let it near a project database.
        if "grocery-tracker" in conn.info.dbname:
            pytest.fail(f"{TEST_DSN_VAR} points at {conn.info.dbname!r}, not a throwaway database")
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        yield conn
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")


@pytest.fixture
def receipts_conn(
    migrate_conn: psycopg.Connection[tuple[object, ...]],
) -> psycopg.Connection[tuple[object, ...]]:
    """`migrate_conn` with every repo migration applied: the schema the writer runs against."""
    apply_migrations(migrate_conn, REPO / "migrations")
    return migrate_conn


@pytest.fixture
def pg_conn() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Connection to the throwaway test database; fails, not skips, so CI cannot go green empty."""
    dsn = os.environ.get(TEST_DSN_VAR)
    if not dsn:
        pytest.fail(f"{TEST_DSN_VAR} is not set; integration tests need a test PostgreSQL database")
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        # Tests seed and alter shared objects such as the chain reference; never a project database.
        if "grocery-tracker" in conn.info.dbname:
            pytest.fail(f"{TEST_DSN_VAR} points at {conn.info.dbname!r}, not a throwaway database")
        yield conn
        # Leaving the block would commit; a test's uncommitted writes must not outlive it.
        conn.rollback()
