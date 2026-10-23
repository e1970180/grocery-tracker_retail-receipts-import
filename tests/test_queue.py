import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from retail_receipts_import.adapters.queue.sqlite import Queue, QueueError
from retail_receipts_import.domain.intake import Accepted, FileKind
from retail_receipts_import.domain.jobs import JobState
from retail_receipts_import.domain.outcomes import FailureReason

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def accepted(message_id: int) -> Accepted:
    return Accepted(12345, message_id, "Ana", f"file{message_id}", FileKind.PHOTO, "image/jpeg", 10)


def test_enqueue_stores_jobs_and_offset_together(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    assert queue.read_offset() is None
    queue.enqueue([accepted(1), accepted(2)], 101, NOW)
    assert queue.read_offset() == 101
    jobs = queue.due_jobs(NOW)
    assert [(j.accepted, j.state) for j in jobs] == [
        (accepted(1), JobState.RECEIVED),
        (accepted(2), JobState.RECEIVED),
    ]


def test_a_redelivered_message_is_not_a_second_job(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    queue.enqueue([accepted(1)], 101, NOW)
    queue.enqueue([accepted(1)], 102, NOW)
    assert len(queue.due_jobs(NOW)) == 1
    assert queue.read_offset() == 102


def test_a_failure_inside_enqueue_keeps_neither_jobs_nor_offset(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite3"
    queue = Queue(path)
    queue.enqueue([accepted(1)], 101, NOW)
    # The offset write comes after the job insert; break it so the transaction fails midway.
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TRIGGER refuse_offset BEFORE UPDATE ON poll_offset"
        " BEGIN SELECT RAISE(ABORT, 'injected'); END"
    )
    raw.commit()
    raw.close()
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        queue.enqueue([accepted(2)], 102, NOW)
    assert queue.read_offset() == 101
    assert [j.accepted.message_id for j in queue.due_jobs(NOW)] == [1]


def test_final_and_postponed_jobs_are_not_due(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    queue.enqueue([accepted(1), accepted(2), accepted(3)], 101, NOW)
    first, second, _ = queue.due_jobs(NOW)
    queue.set_state(first.job_id, JobState.FAILED, NOW, failure_reason=FailureReason.FILE_TOO_LARGE)
    queue.postpone(second.job_id, NOW + timedelta(minutes=10), NOW)
    assert [j.accepted.message_id for j in queue.due_jobs(NOW)] == [3]
    later = NOW + timedelta(minutes=10)
    assert [j.accepted.message_id for j in queue.due_jobs(later)] == [2, 3]


def test_state_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite3"
    queue = Queue(path)
    queue.enqueue([accepted(1)], 101, NOW)
    [job] = queue.due_jobs(NOW)
    queue.set_state(job.job_id, JobState.CHAIN_PENDING, NOW)
    queue.close()
    reopened = Queue(path)
    assert reopened.read_offset() == 101
    assert [j.state for j in reopened.due_jobs(NOW)] == [JobState.CHAIN_PENDING]


def test_unknown_file_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite3"
    Queue(path).close()
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 7")
    raw.close()
    with pytest.raises(QueueError, match="version 7"):
        Queue(path)
