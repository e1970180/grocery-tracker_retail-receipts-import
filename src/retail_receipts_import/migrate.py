"""Applies numbered plain-SQL migrations, each once, in order, in its own transaction."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

SCHEMA = "retail_receipts_import"
MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

log = logging.getLogger(__name__)


class MigrationError(Exception):
    """A migration file is misnamed, or its SQL failed and was rolled back."""


@dataclass(frozen=True)
class Migration:
    version: int
    path: Path


def discover(directory: Path) -> list[Migration]:
    migrations: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_NAME.match(path.name)
        if not match:
            raise MigrationError(f"migration file name {path.name!r} is not NNNN_name.sql")
        version = int(match.group(1))
        if version in migrations:
            raise MigrationError(
                f"migrations {migrations[version].path.name} and {path.name} share a number"
            )
        migrations[version] = Migration(version, path)
    if not migrations:
        # A wrong working directory must not pass for "everything already applied".
        raise MigrationError(f"no migrations found in {directory.resolve()}")
    return [migrations[v] for v in sorted(migrations)]


def apply_migrations(conn: psycopg.Connection[tuple[object, ...]], directory: Path) -> list[str]:
    """Applies pending migrations and returns their file names. `conn` must be in autocommit.

    The schema itself is provisioned with the database roles, not here, so its owner and
    grants are fixed by provisioning rather than by whoever first runs migrate.
    """
    pending = discover(directory)
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {SCHEMA}.schema_migrations ("
        " version integer PRIMARY KEY,"
        " name text NOT NULL,"
        " applied_at timestamptz NOT NULL DEFAULT now())"
    )
    applied = {row[0] for row in conn.execute(f"SELECT version FROM {SCHEMA}.schema_migrations")}
    done: list[str] = []
    for migration in pending:
        if migration.version in applied:
            continue
        sql = migration.path.read_bytes()
        try:
            with conn.transaction():
                # Bytes, not str: a file's SQL is not a literal, and without parameters
                # psycopg sends it as one simple query, so a file may hold many statements.
                conn.execute(sql)
                conn.execute(
                    f"INSERT INTO {SCHEMA}.schema_migrations (version, name) VALUES (%s, %s)",
                    (migration.version, migration.path.name),
                )
        except psycopg.Error as exc:
            raise MigrationError(f"migration {migration.path.name} failed: {exc}") from exc
        log.info("applied migration %s", migration.path.name)
        done.append(migration.path.name)
    return done
