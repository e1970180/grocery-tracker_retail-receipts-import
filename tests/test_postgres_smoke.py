import psycopg
import pytest


@pytest.mark.integration
def test_postgres_answers(pg_conn: psycopg.Connection[tuple[object, ...]]) -> None:
    assert pg_conn.execute("SELECT 1").fetchone() == (1,)
