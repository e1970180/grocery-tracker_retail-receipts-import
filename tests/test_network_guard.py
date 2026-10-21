import psycopg
import pytest


def test_unit_tests_cannot_reach_postgres() -> None:
    # 192.0.2.1 is TEST-NET-1: never a real host.
    with pytest.raises(RuntimeError, match="PostgreSQL access disabled"):
        psycopg.connect("host=192.0.2.1 dbname=x user=x connect_timeout=2")
