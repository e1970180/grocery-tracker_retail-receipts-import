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
    queue.finish(first.job_id, JobState.FAILED, NOW, failure_reason=FailureReason.FILE_TOO_LARGE)
    queue.postpone(second.job_id, NOW + timedelta(minutes=10), NOW)
    assert [j.accepted.message_id for j in queue.due_jobs(NOW)] == [3]
    later = NOW + timedelta(minutes=10)
    assert [j.accepted.message_id for j in queue.due_jobs(later)] == [2, 3]


def test_state_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite3"
    queue = Queue(path)
    queue.enqueue([accepted(1)], 101, NOW)
    [job] = queue.due_jobs(NOW)
    queue.to_chain_pending(job.job_id, NOW, attempts=1, unsupported=True)
    queue.close()
    reopened = Queue(path)
    assert reopened.read_offset() == 101
    [resumed] = reopened.due_jobs(NOW)
    assert (resumed.state, resumed.attempts, resumed.unsupported) == (
        JobState.CHAIN_PENDING,
        1,
        True,
    )


def test_unknown_file_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite3"
    Queue(path).close()
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 7")
    raw.close()
    with pytest.raises(QueueError, match="version 7"):
        Queue(path)


# The first layout as it shipped, kept literal so the upgrade is tested against the real thing.
V1_SCHEMA = """
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


def write_v1_queue(path: Path, state: JobState) -> None:
    raw = sqlite3.connect(path)
    raw.executescript(V1_SCHEMA)
    raw.execute(
        "INSERT INTO jobs (chat_id, message_id, buyer_name, file_id, kind, mime, declared_size,"
        " state, due_at, updated_at) VALUES (12345, 1, 'Ana', 'file1', 'photo', 'image/jpeg',"
        " 10, ?, ?, ?)",
        (state.value, NOW.timestamp(), NOW.timestamp()),
    )
    raw.execute("INSERT INTO poll_offset (id, next_offset) VALUES (1, 101)")
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()


def test_version_1_file_is_upgraded_in_place(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite3"
    write_v1_queue(path, JobState.CHAIN_PENDING)
    queue = Queue(path)
    assert queue.read_offset() == 101
    [job] = queue.due_jobs(NOW)
    assert (job.accepted, job.state) == (accepted(1), JobState.CHAIN_PENDING)
    assert (job.attempts, job.waits, job.step_starts, job.unsupported) == (0, 0, 0, False)
    assert (job.pass1_json, job.receipt_json, job.payload_version) == (None, None, None)
    assert queue._conn.execute("PRAGMA user_version").fetchone() == (2,)
    queue.close()
    # Opening the upgraded file again changes nothing.
    assert Queue(path).read_offset() == 101


def test_new_file_has_the_upgraded_layout(tmp_path: Path) -> None:
    write_v1_queue(tmp_path / "old.sqlite3", JobState.RECEIVED)
    upgraded, new = Queue(tmp_path / "old.sqlite3"), Queue(tmp_path / "new.sqlite3")
    layout = "SELECT name, type, \"notnull\", dflt_value FROM pragma_table_info('jobs')"
    assert upgraded._conn.execute(layout).fetchall() == new._conn.execute(layout).fetchall()


def step_starts(queue: Queue, job_id: int) -> int:
    return queue.job(job_id).step_starts


def test_step_starts_accumulate_until_recorded(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    queue.enqueue([accepted(1)], 101, NOW)
    [job] = queue.due_jobs(NOW)
    queue.start_step(job.job_id, NOW)
    queue.start_step(job.job_id, NOW)
    assert step_starts(queue, job.job_id) == 2
    queue.postpone(job.job_id, NOW, NOW)
    assert step_starts(queue, job.job_id) == 0
    queue.start_step(job.job_id, NOW)
    queue.to_chain_pending(job.job_id, NOW, attempts=0, unsupported=False)
    assert step_starts(queue, job.job_id) == 0
    queue.start_step(job.job_id, NOW)
    queue.wait(job.job_id, NOW + timedelta(seconds=37), NOW, waits=1)
    assert step_starts(queue, job.job_id) == 0
    assert queue.due_jobs(NOW) == []


def test_each_transition_keeps_exactly_what_the_next_step_needs(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    queue.enqueue([accepted(1)], 101, NOW)
    [job] = queue.due_jobs(NOW)
    queue.to_chain_pending(job.job_id, NOW, attempts=1, unsupported=True)
    queue.to_extract_pending(job.job_id, NOW, pass1_json='{"chain": "spar"}')
    extracting = queue.job(job.job_id)
    assert (extracting.attempts, extracting.unsupported) == (1, False)
    queue.to_write_pending(job.job_id, NOW, receipt_json="{}", payload_version=1, receipt_id="r-1")
    writing = queue.job(job.job_id)
    assert (writing.pass1_json, writing.receipt_json, writing.payload_version) == (
        '{"chain": "spar"}',
        "{}",
        1,
    )
    assert writing.receipt_id == "r-1"
    queue.to_chain_pending(job.job_id, NOW, attempts=2, unsupported=False)
    restarted = queue.job(job.job_id)
    assert (restarted.pass1_json, restarted.receipt_json, restarted.receipt_id) == (None,) * 3


def test_wait_count_is_kept_across_a_reopen_and_reset_by_a_transition(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite3"
    queue = Queue(path)
    queue.enqueue([accepted(1)], 101, NOW)
    queue.to_chain_pending(1, NOW, attempts=0, unsupported=False)
    queue.wait(1, NOW + timedelta(seconds=600), NOW, waits=1)
    queue.wait(1, NOW + timedelta(seconds=1200), NOW, waits=2)
    queue.close()
    reopened = Queue(path)
    assert reopened.job(1).waits == 2
    # An exception leaves the count; a transition starts it again.
    reopened.postpone(1, NOW, NOW)
    assert reopened.job(1).waits == 2
    reopened.to_extract_pending(1, NOW, pass1_json="{}")
    assert reopened.job(1).waits == 0


def test_retry_download_keeps_the_job_received_with_its_attempts(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    queue.enqueue([accepted(1)], 101, NOW)
    queue.start_step(1, NOW)
    queue.retry_download(1, NOW + timedelta(seconds=600), NOW, attempts=1)
    job = queue.job(1)
    assert (job.state, job.attempts, job.waits, job.step_starts) == (JobState.RECEIVED, 1, 0, 0)
    assert queue.due_jobs(NOW) == []
    assert [j.job_id for j in queue.due_jobs(NOW + timedelta(seconds=600))] == [1]


def test_next_due_at_is_the_earliest_unfinished_job_in_utc(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    assert queue.next_due_at() is None
    queue.enqueue([accepted(1), accepted(2)], 101, NOW)
    queue.finish(1, JobState.FAILED, NOW, failure_reason=FailureReason.FILE_UNAVAILABLE)
    queue.postpone(2, NOW + timedelta(seconds=7), NOW)
    due = queue.next_due_at()
    assert due == NOW + timedelta(seconds=7)
    assert due is not None and due.tzinfo is UTC
    queue.finish(2, JobState.STORED, NOW)
    assert queue.next_due_at() is None


def test_finish_keeps_the_receipt_id_but_no_receipt_content(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    queue.enqueue([accepted(1)], 101, NOW)
    queue.to_extract_pending(1, NOW, pass1_json='{"chain": "spar"}')
    queue.to_write_pending(1, NOW, receipt_json="{}", payload_version=1, receipt_id="r-1")
    queue.finish(1, JobState.STORED, NOW, receipt_id="r-1")
    job = queue.job(1)
    assert (job.state, job.receipt_id) == (JobState.STORED, "r-1")
    assert (job.pass1_json, job.receipt_json, job.payload_version) == (None, None, None)


def test_a_failed_upgrade_leaves_the_file_at_version_1(tmp_path: Path) -> None:
    path = tmp_path / "q.sqlite3"
    write_v1_queue(path, JobState.CHAIN_PENDING)
    # A column the upgrade adds last already exists, so the upgrade fails after its first steps.
    raw = sqlite3.connect(path)
    raw.execute("ALTER TABLE jobs ADD COLUMN payload_version INTEGER")
    raw.commit()
    raw.close()
    with pytest.raises(sqlite3.OperationalError, match="duplicate column"):
        Queue(path)
    raw = sqlite3.connect(path)
    columns = {row[1] for row in raw.execute("PRAGMA table_info(jobs)")}
    assert raw.execute("PRAGMA user_version").fetchone() == (1,)
    raw.close()
    assert not {"attempts", "waits", "step_starts", "pass1_json"} & columns


def test_only_a_final_state_finishes_a_job(tmp_path: Path) -> None:
    queue = Queue(tmp_path / "q.sqlite3")
    queue.enqueue([accepted(1)], 101, NOW)
    with pytest.raises(ValueError, match="not a final state"):
        queue.finish(1, JobState.WRITE_PENDING, NOW)
