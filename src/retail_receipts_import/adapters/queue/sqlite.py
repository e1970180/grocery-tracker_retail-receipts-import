"""Receipt jobs and the Telegram offset in one SQLite file on the compose volume.

The offset is stored in the transaction that inserts the batch's jobs, so an update is never
acknowledged without its durable job, and a crash between the two keeps neither.
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from retail_receipts_import.domain.intake import Accepted, FileKind
from retail_receipts_import.domain.jobs import FINAL_STATES, Job, JobState
from retail_receipts_import.domain.outcomes import FailureReason

# Raised when the file layout changes, so an older file on the volume is never misread.
SCHEMA_VERSION = 2

# The first layout. A new file is created at it and upgraded like a file from the volume, so
# both take the same path.
_SCHEMA_V1 = """
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

# Each entry upgrades the file from the version it is keyed by to the next one.
_UPGRADES = {
    1: """
ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN waits INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN step_starts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN unsupported INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN pass1_json TEXT;
ALTER TABLE jobs ADD COLUMN receipt_json TEXT;
ALTER TABLE jobs ADD COLUMN payload_version INTEGER;
""",
}

_FINAL = tuple(state.value for state in FINAL_STATES)
_JOB_COLUMNS = (
    "job_id, chat_id, message_id, buyer_name, file_id, kind, mime, declared_size, state,"
    " attempts, waits, step_starts, unsupported, pass1_json, receipt_json, payload_version,"
    " receipt_id"
)
# A new state starts its step afresh, with nothing carried from the state it left.
_STEP_RESET = {"step_starts": 0, "waits": 0}
_NO_RECEIPT = {"receipt_json": None, "payload_version": None, "receipt_id": None}


class QueueError(Exception):
    """The queue file has a layout this code does not know."""


class Queue:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, autocommit=True)
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self._conn.close()
            raise QueueError(f"queue {path} has version {version}, expected {SCHEMA_VERSION}")
        # One transaction, so a crash mid-upgrade leaves the file at its old version.
        with self._transaction():
            if version == 0:
                self._conn.executescript(_SCHEMA_V1)
                version = 1
            while version < SCHEMA_VERSION:
                self._conn.executescript(_UPGRADES[version])
                version += 1
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
            f"SELECT {_JOB_COLUMNS} FROM jobs"
            f" WHERE state NOT IN ({', '.join('?' * len(_FINAL))})"
            " AND due_at <= ? ORDER BY job_id",
            (*_FINAL, now.timestamp()),
        ).fetchall()
        return [_job(row) for row in rows]

    def final_jobs(self) -> list[Accepted]:
        """Sources of finished jobs, whose local files may be left over from a crash."""
        rows = self._conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs"
            f" WHERE state IN ({', '.join('?' * len(_FINAL))}) ORDER BY job_id",
            _FINAL,
        ).fetchall()
        return [_job(row).accepted for row in rows]

    def job(self, job_id: int) -> Job:
        row = self._conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return _job(row)

    def start_step(self, job_id: int, now: datetime) -> None:
        """Counted before the step runs, so a step that never returns still leaves a trace."""
        with self._transaction():
            self._conn.execute(
                "UPDATE jobs SET step_starts = step_starts + 1, updated_at = ? WHERE job_id = ?",
                (now.timestamp(), job_id),
            )

    def to_chain_pending(
        self, job_id: int, now: datetime, *, attempts: int, unsupported: bool
    ) -> None:
        """Pass 1 next: after the download, after an attempt, or after a chain is withdrawn."""
        self._update(
            job_id,
            now,
            state=JobState.CHAIN_PENDING.value,
            attempts=attempts,
            unsupported=int(unsupported),
            pass1_json=None,
            **_NO_RECEIPT,
            **_STEP_RESET,
        )

    def to_extract_pending(self, job_id: int, now: datetime, *, pass1_json: str) -> None:
        # A supported pass-1 result breaks a run of unsupported ones.
        self._update(
            job_id,
            now,
            state=JobState.EXTRACT_PENDING.value,
            unsupported=0,
            pass1_json=pass1_json,
            **_NO_RECEIPT,
            **_STEP_RESET,
        )

    def to_write_pending(
        self,
        job_id: int,
        now: datetime,
        *,
        receipt_json: str,
        payload_version: int,
        receipt_id: str,
    ) -> None:
        self._update(
            job_id,
            now,
            state=JobState.WRITE_PENDING.value,
            receipt_json=receipt_json,
            payload_version=payload_version,
            receipt_id=receipt_id,
            **_STEP_RESET,
        )

    def finish(
        self,
        job_id: int,
        state: JobState,
        now: datetime,
        *,
        failure_reason: FailureReason | None = None,
        receipt_id: str | None = None,
    ) -> None:
        if state not in FINAL_STATES:
            raise ValueError(f"{state} is not a final state")
        self._update(
            job_id,
            now,
            state=state.value,
            failure_reason=None if failure_reason is None else failure_reason.value,
            receipt_id=receipt_id,
            **_STEP_RESET,
        )

    def wait(self, job_id: int, due_at: datetime, now: datetime, *, waits: int) -> None:
        """A wait is a recorded result of the step, so its start count begins again."""
        self._update(job_id, now, due_at=due_at.timestamp(), step_starts=0, waits=waits)

    def retry_download(
        self, job_id: int, due_at: datetime, now: datetime, *, attempts: int
    ) -> None:
        """Telegram did not serve the file: the job stays `received` with one more attempt."""
        self._update(job_id, now, due_at=due_at.timestamp(), attempts=attempts, **_STEP_RESET)

    def postpone(self, job_id: int, due_at: datetime, now: datetime) -> None:
        """After an exception: the step produced no result, so its start count stays."""
        self._update(job_id, now, due_at=due_at.timestamp())

    def next_due_at(self) -> datetime | None:
        """When the earliest unfinished job is due, so the long poll can end in time for it."""
        [due_at] = self._conn.execute(
            f"SELECT min(due_at) FROM jobs WHERE state NOT IN ({', '.join('?' * len(_FINAL))})",
            _FINAL,
        ).fetchone()
        return None if due_at is None else datetime.fromtimestamp(due_at, UTC)

    def _update(self, job_id: int, now: datetime, **columns: object) -> None:
        # Column names come only from this module, never from data.
        assignments = ", ".join(f"{name} = ?" for name in columns)
        with self._transaction():
            self._conn.execute(
                f"UPDATE jobs SET {assignments}, updated_at = ? WHERE job_id = ?",
                (*columns.values(), now.timestamp(), job_id),
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


def _job(row: Any) -> Job:
    return Job(
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
        attempts=row[9],
        waits=row[10],
        step_starts=row[11],
        unsupported=bool(row[12]),
        pass1_json=row[13],
        receipt_json=row[14],
        payload_version=row[15],
        receipt_id=row[16],
    )
