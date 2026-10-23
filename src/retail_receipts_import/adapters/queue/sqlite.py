"""Receipt jobs and the Telegram offset in one SQLite file on the compose volume.

The offset is stored in the transaction that inserts the batch's jobs, so an update is never
acknowledged without its durable job, and a crash between the two keeps neither.
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from retail_receipts_import.domain.intake import Accepted, FileKind
from retail_receipts_import.domain.jobs import FINAL_STATES, Job, JobState
from retail_receipts_import.domain.outcomes import FailureReason

# Raised when the file layout changes, so an older file on the volume is never misread.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE jobs (
    job_id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    buyer_name TEXT NOT NULL,
    file_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    mime TEXT NOT NULL,
    declared_size INTEGER NOT NULL,
    state TEXT NOT NULL,
    failure_reason TEXT,
    receipt_id TEXT,
    due_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (chat_id, message_id)
) STRICT;
CREATE TABLE poll_offset (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    next_offset INTEGER NOT NULL
) STRICT;
"""

_FINAL = tuple(state.value for state in FINAL_STATES)


class QueueError(Exception):
    """The queue file has a layout this code does not know."""


class Queue:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, autocommit=True)
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            with self._transaction():
                self._conn.executescript(_SCHEMA)
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            self._conn.close()
            raise QueueError(f"queue {path} has version {version}, expected {SCHEMA_VERSION}")

    def close(self) -> None:
        self._conn.close()

    def read_offset(self) -> int | None:
        row = self._conn.execute("SELECT next_offset FROM poll_offset WHERE id = 1").fetchone()
        return None if row is None else int(row[0])

    def enqueue(self, accepted: Sequence[Accepted], next_offset: int, now: datetime) -> None:
        """Inserts the batch's jobs and acknowledges the batch, both or neither."""
        at = now.timestamp()
        with self._transaction():
            # A redelivered or edited message has the same source and must not become a job twice.
            self._conn.executemany(
                "INSERT OR IGNORE INTO jobs (chat_id, message_id, buyer_name, file_id, kind,"
                " mime, declared_size, state, due_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        a.chat_id,
                        a.message_id,
                        a.buyer_name,
                        a.file_id,
                        a.kind.value,
                        a.mime,
                        a.declared_size,
                        JobState.RECEIVED.value,
                        at,
                        at,
                    )
                    for a in accepted
                ],
            )
            self._conn.execute(
                "INSERT INTO poll_offset (id, next_offset) VALUES (1, ?)"
                " ON CONFLICT (id) DO UPDATE SET next_offset = excluded.next_offset",
                (next_offset,),
            )

    def due_jobs(self, now: datetime) -> list[Job]:
        rows = self._conn.execute(
            "SELECT job_id, chat_id, message_id, buyer_name, file_id, kind, mime, declared_size,"
            f" state FROM jobs WHERE state NOT IN ({', '.join('?' * len(_FINAL))})"
            " AND due_at <= ? ORDER BY job_id",
            (*_FINAL, now.timestamp()),
        ).fetchall()
        return [
            Job(
                job_id=row[0],
                accepted=Accepted(
                    chat_id=row[1],
                    message_id=row[2],
                    buyer_name=row[3],
                    file_id=row[4],
                    kind=FileKind(row[5]),
                    mime=row[6],
                    declared_size=row[7],
                ),
                state=JobState(row[8]),
            )
            for row in rows
        ]

    def set_state(
        self,
        job_id: int,
        state: JobState,
        now: datetime,
        *,
        failure_reason: FailureReason | None = None,
        receipt_id: str | None = None,
    ) -> None:
        with self._transaction():
            self._conn.execute(
                "UPDATE jobs SET state = ?, failure_reason = ?, receipt_id = ?, updated_at = ?"
                " WHERE job_id = ?",
                (
                    state.value,
                    None if failure_reason is None else failure_reason.value,
                    receipt_id,
                    now.timestamp(),
                    job_id,
                ),
            )

    def postpone(self, job_id: int, due_at: datetime, now: datetime) -> None:
        with self._transaction():
            self._conn.execute(
                "UPDATE jobs SET due_at = ?, updated_at = ? WHERE job_id = ?",
                (due_at.timestamp(), now.timestamp(), job_id),
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")
