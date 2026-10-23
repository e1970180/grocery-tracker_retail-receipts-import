import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from retail_receipts_import.adapters.files.store import FileStore
from retail_receipts_import.adapters.queue.sqlite import Queue
from retail_receipts_import.adapters.telegram.download import FileTooLarge
from retail_receipts_import.app import loop
from retail_receipts_import.app.jobs import JobPorts
from retail_receipts_import.app.pipeline import Duplicate, Invalid, Result, Stored, Unsupported
from retail_receipts_import.domain.jobs import JobState
from retail_receipts_import.domain.outcomes import FailureReason
from retail_receipts_import.domain.receipt import ReceiptSource, telegram_source

ALLOWED = 12345
RECEIPT_ID = uuid.UUID(int=7)
SETTINGS = loop.LoopSettings(
    allowed_user_ids=frozenset({ALLOWED}), poll_timeout_s=30, retry_delay=timedelta(seconds=600)
)
PDF_BYTES = b"%PDF-1.7 receipt"


def pdf_update(
    update_id: int, message_id: int, sender: int = ALLOWED, chat_type: str = "private"
) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": sender, "type": chat_type},
            "from": {"id": sender, "first_name": "Ana"},
            "document": {
                "file_id": f"f{message_id}",
                "file_size": 16,
                "mime_type": "application/pdf",
            },
        },
    }


@dataclass
class FakeTelegram:
    batches: list[list[dict[str, Any]]]
    offsets: list[int | None] = field(default_factory=list)

    def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        assert allowed_updates == ("message",)
        self.offsets.append(offset)
        return self.batches.pop(0) if self.batches else []


@dataclass
class Fakes:
    queue: Queue
    files: FileStore
    result: Result | Exception = field(default_factory=lambda: Stored(RECEIPT_ID))
    download_error: Exception | None = None
    react_error: Exception | None = None
    now: datetime = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    downloads: list[str] = field(default_factory=list)
    processed: list[tuple[Path, str, ReceiptSource]] = field(default_factory=list)
    reactions: list[tuple[int, int]] = field(default_factory=list)

    def download(self, file_id: str, declared_size: int) -> bytes:
        self.downloads.append(file_id)
        if self.download_error is not None:
            raise self.download_error
        return PDF_BYTES

    def process(self, path: Path, mime: str, source: ReceiptSource) -> Result:
        assert path.read_bytes() == PDF_BYTES
        self.processed.append((path, mime, source))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def react(self, chat_id: int, message_id: int) -> None:
        # The reaction comes only after the final state is durable.
        assert self.state() is JobState.STORED
        self.reactions.append((chat_id, message_id))
        if self.react_error is not None:
            raise self.react_error

    def ports(self) -> JobPorts:
        return JobPorts(
            queue=self.queue,
            files=self.files,
            download=self.download,
            process=self.process,
            react_stored=self.react,
            clock=lambda: self.now,
        )

    def state(self) -> JobState:
        [row] = self.queue._conn.execute("SELECT state FROM jobs").fetchall()
        return JobState(row[0])

    def failure_reason(self) -> str | None:
        [row] = self.queue._conn.execute("SELECT failure_reason FROM jobs").fetchall()
        return row[0]  # type: ignore[no-any-return]


@pytest.fixture
def fakes(tmp_path: Path) -> Fakes:
    return Fakes(Queue(tmp_path / "queue.sqlite3"), FileStore(tmp_path / "files"))


def cycle(telegram: FakeTelegram, fakes: Fakes) -> None:
    ports = fakes.ports()
    loop.poll(telegram, ports, SETTINGS)
    loop.run_due(ports, SETTINGS, threading.Event())


def test_stored_receipt_gets_the_success_reaction(fakes: Fakes) -> None:
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes)
    assert fakes.state() is JobState.STORED
    assert fakes.reactions == [(ALLOWED, 3)]
    [(path, mime, source)] = fakes.processed
    assert (path.name, mime) == (f"{ALLOWED}_3.pdf", "application/pdf")
    assert source == telegram_source(ALLOWED, 3, buyer_name="Ana")
    [row] = fakes.queue._conn.execute("SELECT receipt_id FROM jobs").fetchall()
    assert row[0] == str(RECEIPT_ID)


def test_failed_reaction_is_only_logged(fakes: Fakes, caplog: pytest.LogCaptureFixture) -> None:
    fakes.react_error = RuntimeError("telegram down")
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes)
    assert fakes.state() is JobState.STORED
    assert "success reaction failed" in caplog.text


@pytest.mark.parametrize(
    ("result", "state", "reason"),
    [
        (Duplicate(RECEIPT_ID), JobState.DUPLICATE, None),
        (Unsupported("other", "Konzum"), JobState.UNSUPPORTED_CHAIN, None),
        (Invalid(FailureReason.NO_VALID_RESULT, "unreadable"), JobState.FAILED, "no_valid_result"),
        (
            Invalid(FailureReason.ITEMS_SETTLEMENT_MISMATCH, "0.02"),
            JobState.FAILED,
            "items_settlement_mismatch",
        ),
    ],
)
def test_non_stored_result_ends_the_job_without_a_notice(
    fakes: Fakes, result: Result, state: JobState, reason: str | None
) -> None:
    fakes.result = result
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes)
    assert fakes.state() is state
    assert fakes.failure_reason() == reason
    assert fakes.reactions == []


def test_oversize_after_getfile_fails_the_job(fakes: Fakes) -> None:
    fakes.download_error = FileTooLarge("too big")
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes)
    assert fakes.state() is JobState.FAILED
    assert fakes.failure_reason() == "file_too_large"
    assert fakes.processed == []


@pytest.mark.parametrize(
    "update",
    [
        pdf_update(100, 3, sender=99999),
        pdf_update(100, 3, chat_type="group"),
        {
            "update_id": 100,
            "message": {
                "message_id": 3,
                "chat": {"id": ALLOWED, "type": "private"},
                "from": {"id": ALLOWED},
                "text": "hi",
            },
        },
    ],
    ids=["not-allowlisted", "group-chat", "text"],
)
def test_filtered_update_makes_no_job_but_is_acknowledged(
    fakes: Fakes, update: dict[str, Any]
) -> None:
    telegram = FakeTelegram([[update]])
    cycle(telegram, fakes)
    assert fakes.queue._conn.execute("SELECT count(*) FROM jobs").fetchone() == (0,)
    assert fakes.queue.read_offset() == 101
    assert fakes.downloads == [] and fakes.reactions == []


def test_redelivered_update_is_not_processed_twice(fakes: Fakes) -> None:
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes)
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes)
    assert len(fakes.processed) == 1


def test_exception_keeps_the_job_and_retries_after_the_delay(
    fakes: Fakes, caplog: pytest.LogCaptureFixture
) -> None:
    fakes.result = RuntimeError("boom")
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes)
    assert fakes.state() is JobState.CHAIN_PENDING
    assert "job 1 failed in its step" in caplog.text
    assert len(fakes.downloads) == 1

    fakes.result = Stored(RECEIPT_ID)
    fakes.now += timedelta(seconds=599)
    loop.run_due(fakes.ports(), SETTINGS, threading.Event())
    assert len(fakes.processed) == 1

    fakes.now += timedelta(seconds=1)
    loop.run_due(fakes.ports(), SETTINGS, threading.Event())
    assert fakes.state() is JobState.STORED
    # The file was saved before the failure, so the retry does not download it again.
    assert len(fakes.downloads) == 1


def test_download_exception_keeps_the_job_received(fakes: Fakes) -> None:
    fakes.download_error = RuntimeError("telegram unavailable")
    cycle(FakeTelegram([[pdf_update(100, 3)]]), fakes)
    assert fakes.state() is JobState.RECEIVED
    assert fakes.processed == []


def test_restart_fetches_from_the_committed_offset_and_resumes_jobs(
    fakes: Fakes, tmp_path: Path
) -> None:
    fakes.result = RuntimeError("crash before the pipeline finished")
    first = FakeTelegram([[pdf_update(100, 3), pdf_update(101, 4, sender=99999)]])
    cycle(first, fakes)
    assert first.offsets == [None]
    fakes.queue.close()

    restarted = Fakes(Queue(tmp_path / "queue.sqlite3"), FileStore(tmp_path / "files"))
    restarted.now = fakes.now + timedelta(seconds=600)
    second = FakeTelegram([])
    cycle(second, restarted)
    assert second.offsets == [102]
    assert restarted.state() is JobState.STORED
    assert restarted.downloads == []


def test_a_poll_failure_still_runs_due_jobs(fakes: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    loop.poll(FakeTelegram([[pdf_update(100, 3)]]), fakes.ports(), SETTINGS)
    monkeypatch.setattr(loop, "POLL_ERROR_BACKOFF_S", 0.0)
    stop = threading.Event()

    class DownThenStop:
        calls = 0

        def get_updates(
            self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
        ) -> list[dict[str, Any]]:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("telegram down")
            stop.set()
            return []

    loop.run(DownThenStop(), fakes.ports(), SETTINGS, stop)
    assert fakes.state() is JobState.STORED


def test_run_stops_and_survives_a_poll_failure(fakes: Fakes) -> None:
    stop = threading.Event()

    class Failing:
        calls = 0

        def get_updates(
            self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
        ) -> list[dict[str, Any]]:
            self.calls += 1
            stop.set()
            raise RuntimeError("network")

    telegram = Failing()
    loop.run(telegram, fakes.ports(), SETTINGS, stop)
    assert telegram.calls == 1
