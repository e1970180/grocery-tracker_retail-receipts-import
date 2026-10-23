from pathlib import Path

import psycopg
import pytest

from retail_receipts_import.migrate import (
    SCHEMA,
    MigrationError,
    apply_migrations,
    discover,
)
from tests.conftest import REPO


def test_discover_orders_by_number(tmp_path: Path) -> None:
    for name in ("0010_later.sql", "0002_second.sql", "0001_first.sql"):
        (tmp_path / name).write_text("SELECT 1;")
    assert [m.version for m in discover(tmp_path)] == [1, 2, 10]


@pytest.mark.parametrize("name", ["1_short.sql", "0001-dash.sql", "0001_Upper.sql"])
def test_discover_refuses_misnamed_file(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="not NNNN_name.sql"):
        discover(tmp_path)


def test_discover_refuses_missing_or_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(MigrationError, match="no migrations"):
        discover(tmp_path / "absent")
    with pytest.raises(MigrationError, match="no migrations"):
        discover(tmp_path)


def test_discover_refuses_duplicate_number(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("SELECT 1;")
    (tmp_path / "0001_b.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="share a number"):
        discover(tmp_path)


def _versions(conn: psycopg.Connection[tuple[object, ...]]) -> list[object]:
    rows = conn.execute(f"SELECT version FROM {SCHEMA}.schema_migrations ORDER BY version")
    return [row[0] for row in rows]


@pytest.mark.integration
def test_repo_migrations_apply_once(migrate_conn: psycopg.Connection[tuple[object, ...]]) -> None:
    first = apply_migrations(migrate_conn, REPO / "migrations")
    assert first == [m.path.name for m in discover(REPO / "migrations")]
    assert apply_migrations(migrate_conn, REPO / "migrations") == []


@pytest.mark.integration
def test_failed_migration_rolls_back_and_stops(
    migrate_conn: psycopg.Connection[tuple[object, ...]], tmp_path: Path
) -> None:
    (tmp_path / "0001_ok.sql").write_text(f"CREATE TABLE {SCHEMA}.first (id int);")
    (tmp_path / "0002_bad.sql").write_text(
        f"CREATE TABLE {SCHEMA}.second (id int);\nSELECT no_such_column FROM {SCHEMA}.second;"
    )
    (tmp_path / "0003_after.sql").write_text(f"CREATE TABLE {SCHEMA}.third (id int);")

    with pytest.raises(MigrationError, match="0002_bad.sql"):
        apply_migrations(migrate_conn, tmp_path)

    assert _versions(migrate_conn) == [1]
    tables = migrate_conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (SCHEMA,),
    ).fetchall()
    assert {row[0] for row in tables} == {"schema_migrations", "first"}
