"""Moves one job through its states; the only code that changes job state.

`received` downloads the file. `chain_pending` runs the whole pipeline, from pass 1 to the
PostgreSQL write, and ends the job. The success reaction follows the PostgreSQL commit and
the final state, and its failure is only logged.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from retail_receipts_import.adapters.files.store import FileStore
from retail_receipts_import.adapters.queue.sqlite import Queue
from retail_receipts_import.adapters.telegram.download import FileTooLarge
from retail_receipts_import.app.pipeline import Duplicate, Invalid, Result, Stored, Unsupported
from retail_receipts_import.domain.jobs import Job, JobState
from retail_receipts_import.domain.outcomes import FailureReason
from retail_receipts_import.domain.receipt import ReceiptSource, telegram_source

log = logging.getLogger(__name__)

Download = Callable[[str, int], bytes]
Process = Callable[[Path, str, ReceiptSource], Result]
React = Callable[[int, int], None]


@dataclass(frozen=True)
class JobPorts:
    queue: Queue
    files: FileStore
    download: Download
    process: Process
    react_stored: React
    clock: Callable[[], datetime]


def advance(job: Job, ports: JobPorts) -> None:
    """Runs the job's remaining steps; an exception leaves it in the last recorded state."""
    state = job.state
    if state is JobState.RECEIVED:
        state = _download(job, ports)
    if state is JobState.CHAIN_PENDING:
        _process(job, ports)


def _download(job: Job, ports: JobPorts) -> JobState:
    item = job.accepted
    try:
        data = ports.download(item.file_id, item.declared_size)
    except FileTooLarge as exc:
        log.info("job %s: %s", job.job_id, exc)
        return _set(job, ports, JobState.FAILED, failure_reason=FailureReason.FILE_TOO_LARGE)
    ports.files.save(ports.files.path_for(item.chat_id, item.message_id, item.mime), data)
    return _set(job, ports, JobState.CHAIN_PENDING)


def _process(job: Job, ports: JobPorts) -> None:
    item = job.accepted
    path = ports.files.path_for(item.chat_id, item.message_id, item.mime)
    source = telegram_source(item.chat_id, item.message_id, buyer_name=item.buyer_name)
    match ports.process(path, item.mime, source):
        case Stored(receipt_id):
            _set(job, ports, JobState.STORED, receipt_id=str(receipt_id))
            _react(job, ports)
        case Duplicate(receipt_id):
            _set(job, ports, JobState.DUPLICATE, receipt_id=str(receipt_id))
        case Unsupported(chain_id):
            log.info("job %s: chain %s is not supported", job.job_id, chain_id)
            _set(job, ports, JobState.UNSUPPORTED_CHAIN)
        case Invalid(reason, detail):
            log.info("job %s: %s: %s", job.job_id, reason, detail)
            _set(job, ports, JobState.FAILED, failure_reason=reason)


def _set(
    job: Job,
    ports: JobPorts,
    state: JobState,
    *,
    failure_reason: FailureReason | None = None,
    receipt_id: str | None = None,
) -> JobState:
    ports.queue.set_state(
        job.job_id, state, ports.clock(), failure_reason=failure_reason, receipt_id=receipt_id
    )
    log.info("job %s: %s", job.job_id, state)
    return state


def _react(job: Job, ports: JobPorts) -> None:
    # Best effort: the receipt is stored whatever happens to the reaction.
    try:
        ports.react_stored(job.accepted.chat_id, job.accepted.message_id)
    except Exception as exc:
        log.error("job %s: success reaction failed: %s: %s", job.job_id, type(exc).__name__, exc)
