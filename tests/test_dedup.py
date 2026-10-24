"""The dedup pre-check on a real queue and a throwaway PostgreSQL: resends end before pass 2."""

import contextlib
import dataclasses
import logging
import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic import BaseModel

from retail_receipts_import.adapters.files.store import FileStore
from retail_receipts_import.adapters.postgres.chains import ChainReference
from retail_receipts_import.adapters.postgres.receipts import find_other_source
from retail_receipts_import.adapters.queue.sqlite import Queue
from retail_receipts_import.app import jobs, loop
from retail_receipts_import.app.jobs import JobPorts
from retail_receipts_import.app.notify import Notifier
from retail_receipts_import.app.pipeline import Ports
from retail_receipts_import.app.service import pipeline_ports
from retail_receipts_import.config import Settings
from retail_receipts_import.domain.chains import KnownChain
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from retail_receipts_import.domain.intake import Accepted, FileKind
from retail_receipts_import.domain.jobs import JobState
from retail_receipts_import.domain.receipt import telegram_source
from tests.conftest import TEST_DSN_VAR
from tests.spar_samples import pass1_response, response
from tests.test_notify import ADMIN, TEXTS, RecordingTelegram

pytestmark = pytest.mark.integration

SPAR = KnownChain("spar", "Spar", ("SPAR", "Spar", "INTERSPAR"), ("46108893754",))
SPAR_ONLY = ChainReference(chains=(SPAR,), inactive_ids=(), rejected=())
PDF_BYTES = b"%PDF-1.7 receipt"
RETRY_DELAY = timedelta(seconds=600)
LOOP_SETTINGS = loop.LoopSettings(
    allowed_user_ids=frozenset({1}),
    poll_timeout_s=30,
    retry_delay=RETRY_DELAY,
    max_attempts=3,
)
START = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


@dataclass
class Gemini:
    """Answers pass 2 always the same and pass 1 as set per message, and counts the calls."""

    pass1: str = field(default_factory=pass1_response)
    pass2: str = field(default_factory=response)
    pass2_calls: int = 0

    def generate(self, data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        if schema is SparPass2:
            self.pass2_calls += 1
            return self.pass2
        return self.pass1


@dataclass
class Env:
    queue: Queue
    conn: psycopg.Connection[Any]
    settings: Settings
    files: FileStore
    gemini: Gemini = field(default_factory=Gemini)
    now: datetime = START

    @contextlib.contextmanager
    def open_pipeline(self) -> Iterator[Ports]:
        # Only the reference read is replaced: the dedup lookup and the writer are the real ones.
        ports = pipeline_ports(self.settings, self.conn, self.gemini.generate)
        yield dataclasses.replace(ports, read_chain_reference=lambda: SPAR_ONLY)

    def ports(self) -> JobPorts:
        return JobPorts(
            queue=self.queue,
            files=self.files,
            download=lambda file_id, size: PDF_BYTES,
            open_pipeline=self.open_pipeline,
            notify=Notifier(RecordingTelegram(), TEXTS, ADMIN),
            clock=lambda: self.now,
        )

    def send(self, message_id: int) -> int:
        """Queues one message of the allowed chat and returns its job id."""
        accepted = Accepted(
            chat_id=1,
            message_id=message_id,
            buyer_name="Ana",
            file_id=f"f{message_id}",
            kind=FileKind.DOCUMENT,
            mime="application/pdf",
            declared_size=len(PDF_BYTES),
        )
        self.queue.enqueue([accepted], message_id + 1, self.now)
        [job_id] = [
            row[0]
            for row in self.queue._conn.execute(
                "SELECT job_id FROM jobs WHERE message_id = ?", (message_id,)
            )
        ]
        return int(job_id)

    def advance(self, job_id: int) -> None:
        jobs.advance(self.queue.job(job_id), self.ports(), 3, RETRY_DELAY)

    def count(self, table: str) -> int:
        row = self.conn.execute(f"SELECT count(*) FROM retail_receipts_import.{table}").fetchone()
        assert row is not None
        return int(row[0])


@pytest.fixture
def env(
    tmp_path: Path, rri_env: dict[str, str], receipts_conn: psycopg.Connection[Any]
) -> Iterator[Env]:
    queue = Queue(tmp_path / "queue.sqlite3")
    yield Env(
        queue,
        receipts_conn,
        Settings(),  # type: ignore[call-arg]
        FileStore(tmp_path / "files"),
    )
    queue.close()


def test_resend_ends_as_duplicate_before_pass_2(env: Env) -> None:
    first, second = env.send(10), env.send(11)
    env.advance(first)
    assert env.queue.job(first).state is JobState.STORED
    assert env.gemini.pass2_calls == 1

    # Pass 1 prints the date without the trailing dot that pass 2 printed.
    env.gemini.pass1 = pass1_response(purchase_date="01.02.2030")
    env.advance(second)
    job = env.queue.job(second)
    assert job.state is JobState.DUPLICATE
    assert job.receipt_id == env.queue.job(first).receipt_id
    assert (job.attempts, job.pass1_json) == (0, None)
    assert env.gemini.pass2_calls == 1
    assert (env.count("receipts"), env.count("receipt_feed")) == (1, 1)


def test_unreadable_pass1_time_leaves_the_duplicate_to_the_writer(env: Env) -> None:
    first, second = env.send(10), env.send(11)
    env.advance(first)

    env.gemini.pass1 = pass1_response(purchase_time=None)
    env.advance(second)
    job = env.queue.job(second)
    assert job.state is JobState.DUPLICATE
    assert job.receipt_id == env.queue.job(first).receipt_id
    assert env.gemini.pass2_calls == 2
    assert (env.count("receipts"), env.count("receipt_feed")) == (1, 1)


def test_crash_after_the_commit_is_stored_on_the_rerun(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = env.send(10)
    real_finish: Callable[..., None] = env.queue.finish
    failures = [RuntimeError("killed after the commit")]

    def finish_once_failing(*args: Any, **kwargs: Any) -> None:
        if failures:
            raise failures.pop()
        real_finish(*args, **kwargs)

    monkeypatch.setattr(env.queue, "finish", finish_once_failing)
    ports = env.ports()
    loop.run_due(ports, LOOP_SETTINGS, threading.Event())
    # Committed to PostgreSQL, but the queue still says the write is pending.
    assert env.queue.job(job_id).state is JobState.WRITE_PENDING
    assert env.count("receipts") == 1

    env.now += RETRY_DELAY
    loop.run_due(ports, LOOP_SETTINGS, threading.Event())
    job = env.queue.job(job_id)
    assert job.state is JobState.STORED
    assert job.receipt_id is not None
    assert env.gemini.pass2_calls == 1
    assert (env.count("receipts"), env.count("receipt_feed")) == (1, 1)


def test_find_other_source_ignores_the_own_source(env: Env) -> None:
    job_id = env.send(10)
    env.advance(job_id)
    purchased_at = datetime(2030, 2, 1, 8, 5, tzinfo=UTC)
    stored_id = env.queue.job(job_id).receipt_id
    assert stored_id is not None

    own = telegram_source(1, 10, "Ana")
    other = telegram_source(1, 11, "Ana")
    assert find_other_source(env.conn, "spar", purchased_at, own) is None
    found = find_other_source(env.conn, "spar", purchased_at, other)
    assert found is not None and str(found) == stored_id
    assert find_other_source(env.conn, "spar", purchased_at + timedelta(minutes=1), other) is None


def test_find_other_source_on_a_closed_connection_answers_none(
    pg_conn: psycopg.Connection[Any], caplog: pytest.LogCaptureFixture
) -> None:
    # Its own connection, so closing it does not break the fixture's cleanup.
    dsn = os.environ[TEST_DSN_VAR]
    closed = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
    closed.close()
    purchased_at = datetime(2030, 2, 1, 8, 5, tzinfo=UTC)
    assert find_other_source(closed, "spar", purchased_at, telegram_source(1, 11, "Ana")) is None
    assert any(
        record.levelno == logging.WARNING and "OperationalError" in record.getMessage()
        for record in caplog.records
    )


def test_find_other_source_on_any_database_error_answers_none(
    pg_conn: psycopg.Connection[Any], caplog: pytest.LogCaptureFixture
) -> None:
    # An aborted transaction refuses every query with an error that is not OperationalError.
    dsn = os.environ[TEST_DSN_VAR]
    with psycopg.connect(dsn, connect_timeout=10) as aborted:
        with contextlib.suppress(psycopg.errors.DivisionByZero):
            aborted.execute("SELECT 1 / 0")
        purchased_at = datetime(2030, 2, 1, 8, 5, tzinfo=UTC)
        source = telegram_source(1, 11, "Ana")
        assert find_other_source(aborted, "spar", purchased_at, source) is None
    assert any(
        record.levelno == logging.WARNING and "InFailedSqlTransaction" in record.getMessage()
        for record in caplog.records
    )
