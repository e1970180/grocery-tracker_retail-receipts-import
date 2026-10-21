"""Global pytest fixtures and configuration."""

import os
import socket
from collections.abc import Iterator

import psycopg
import pytest

# A dedicated variable, never libpq's PG* defaults: those may point at the production database.
TEST_DSN_VAR = "RRI_TEST_DATABASE_URL"


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
def pg_conn() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Connection to the throwaway test database; fails, not skips, so CI cannot go green empty."""
    dsn = os.environ.get(TEST_DSN_VAR)
    if not dsn:
        pytest.fail(f"{TEST_DSN_VAR} is not set; integration tests need a test PostgreSQL database")
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        yield conn
        # Leaving the block would commit; a test's uncommitted writes must not outlive it.
        conn.rollback()
