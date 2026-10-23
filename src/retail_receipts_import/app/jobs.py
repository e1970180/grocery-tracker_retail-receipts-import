"""Moves one job through its states; the only code that changes job state.

Each state is one step whose result is persisted before the next step starts, so a restart
resumes where the job stopped: `received` downloads the file, `chain_pending` runs pass 1,
`extract_pending` runs pass 2 and its checks, and `write_pending` stores the kept receipt
without calling Gemini again. The success reaction follows the PostgreSQL commit and the final
state, and its failure is only logged.
"""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from retail_receipts_import.adapters.files.store import FileStore
from retail_receipts_import.adapters.queue.sqlite import Queue
from retail_receipts_import.adapters.telegram.download import FileTooLarge, FileUnavailable
from retail_receipts_import.app import pipeline
from retail_receipts_import.app.pipeline import (
    ChainFound,
    ChainWithdrawn,
    Duplicate,
    Extracted,
    ExtractionWait,
    Invalid,
    Ports,
    Stored,
    Unsupported,
)
from retail_receipts_import.domain.chains.pass1 import Pass1Response
from retail_receipts_import.domain.extraction import ExtractionClass
from retail_receipts_import.domain.jobs import FINAL_STATES, Job, JobState
from retail_receipts_import.domain.outcomes import FailureReason
from retail_receipts_import.domain.receipt import (
    PAYLOAD_VERSION,
    NormalizedReceipt,
    ReceiptSource,
    telegram_source,
)

log = logging.getLogger(__name__)

Download = Callable[[str, int], bytes]
# Opened once per job and shared by its steps, e.g. around one PostgreSQL connection.
OpenPipeline = Callable[[], AbstractContextManager[Ports]]
React = Callable[[int, int], None]


@dataclass(frozen=True)
class JobPorts:
    queue: Queue
    files: FileStore
    download: Download
    open_pipeline: OpenPipeline
    react_stored: React
    clock: Callable[[], datetime]


def advance(job: Job, ports: JobPorts, max_attempts: int, retry_delay: timedelta) -> None:
    """Runs the job's steps until it ends or waits; an exception leaves the last recorded state."""
    if job.state is JobState.RECEIVED:
        _start_step(job, ports)
        _download(job, ports, max_attempts, retry_delay)
        job = ports.queue.job(job.job_id)
        # Failed, or still `received` and due again later: nothing for the pipeline yet.
        if job.state is not JobState.CHAIN_PENDING:
            return
    # Opened after the download, so a PostgreSQL outage does not hold back Telegram downloads.
    with ports.open_pipeline() as steps:
        while job.state not in FINAL_STATES:
            _start_step(job, ports)
            try:
                _STEPS[job.state](job, ports, steps, max_attempts)
            except ExtractionWait as wait:
                _wait(job, ports, wait)
                return
            # Read back, so the next step runs on exactly what a restart would see.
            job = ports.queue.job(job.job_id)


def _start_step(job: Job, ports: JobPorts) -> None:
    ports.queue.start_step(job.job_id, ports.clock())


def _download(job: Job, ports: JobPorts, max_attempts: int, retry_delay: timedelta) -> None:
    item = job.accepted
    try:
        data = ports.download(item.file_id, item.declared_size)
    except FileTooLarge as exc:
        log.info("job %s: %s", job.job_id, exc)
        _finish(job, ports, JobState.FAILED, failure_reason=FailureReason.FILE_TOO_LARGE)
        return
    except FileUnavailable as exc:
        _file_unavailable(job, ports, exc, max_attempts, retry_delay)
        return
    ports.files.save(_path(job, ports), data)
    # Gemini gets all its attempts whatever the download took.
    ports.queue.to_chain_pending(job.job_id, ports.clock(), attempts=0, unsupported=False)
    log.info("job %s: %s", job.job_id, JobState.CHAIN_PENDING)


def _file_unavailable(
    job: Job, ports: JobPorts, exc: FileUnavailable, max_attempts: int, retry_delay: timedelta
) -> None:
    # Telegram may only be unable to serve the file for now, so it gets the attempts.
    attempts = job.attempts + 1
    log.info("job %s: file unavailable: %s (attempt %d)", job.job_id, exc, attempts)
    if attempts >= max_attempts:
        _finish(job, ports, JobState.FAILED, failure_reason=FailureReason.FILE_UNAVAILABLE)
        return
    now = ports.clock()
    ports.queue.retry_download(job.job_id, now + retry_delay, now, attempts=attempts)


def _detect_chain(job: Job, ports: JobPorts, steps: Ports, max_attempts: int) -> None:
    match pipeline.detect_chain(_path(job, ports), job.accepted.mime, steps, waits=job.waits):
        case ChainFound(pass1):
            ports.queue.to_extract_pending(
                job.job_id, ports.clock(), pass1_json=pass1.model_dump_json()
            )
            log.info("job %s: %s (%s)", job.job_id, JobState.EXTRACT_PENDING, pass1.chain)
        case Unsupported(chain_id):
            _unsupported(job, ports, chain_id, max_attempts)
        case Invalid() as invalid:
            _invalid(job, ports, invalid, max_attempts)


def _extract(job: Job, ports: JobPorts, steps: Ports, max_attempts: int) -> None:
    pass1 = Pass1Response.model_validate_json(_pass1_json(job))
    match pipeline.extract(_path(job, ports), job.accepted.mime, pass1, steps, waits=job.waits):
        case Extracted(receipt):
            ports.queue.to_write_pending(
                job.job_id,
                ports.clock(),
                receipt_json=receipt.model_dump_json(),
                payload_version=PAYLOAD_VERSION,
                receipt_id=str(uuid.uuid7()),
            )
            log.info("job %s: %s", job.job_id, JobState.WRITE_PENDING)
        case ChainWithdrawn(chain_id):
            # The reference changed, not the file, so no attempt is consumed.
            log.info("job %s: chain %s is no longer supported, pass 1 again", job.job_id, chain_id)
            ports.queue.to_chain_pending(
                job.job_id, ports.clock(), attempts=job.attempts, unsupported=False
            )
        case Invalid() as invalid:
            _invalid(job, ports, invalid, max_attempts)


def _write(job: Job, ports: JobPorts, steps: Ports, max_attempts: int) -> None:
    receipt = _kept_receipt(job)
    if receipt is None or job.receipt_id is None:
        # Kept by another version of this code; pass 2 is redone, not the whole job.
        log.info(
            "job %s: kept receipt is not version %s, pass 2 again", job.job_id, PAYLOAD_VERSION
        )
        ports.queue.to_extract_pending(job.job_id, ports.clock(), pass1_json=_pass1_json(job))
        return
    source = _source(job)
    match pipeline.store(uuid.UUID(job.receipt_id), receipt, source, steps):
        case Stored(receipt_id):
            _finish(job, ports, JobState.STORED, receipt_id=str(receipt_id))
            _react(job, ports)
        case Duplicate(receipt_id):
            _finish(job, ports, JobState.DUPLICATE, receipt_id=str(receipt_id))


_STEPS = {
    JobState.CHAIN_PENDING: _detect_chain,
    JobState.EXTRACT_PENDING: _extract,
    JobState.WRITE_PENDING: _write,
}


def _unsupported(job: Job, ports: JobPorts, chain_id: str, max_attempts: int) -> None:
    attempts = job.attempts + 1
    log.info("job %s: chain %s is not supported (attempt %d)", job.job_id, chain_id, attempts)
    # Only a second unsupported result in a row is believed; one on the last attempt ends too.
    if job.unsupported or attempts >= max_attempts:
        _finish(job, ports, JobState.UNSUPPORTED_CHAIN)
        return
    ports.queue.to_chain_pending(job.job_id, ports.clock(), attempts=attempts, unsupported=True)
    log.info("job %s: %s", job.job_id, JobState.CHAIN_PENDING)


def _invalid(job: Job, ports: JobPorts, invalid: Invalid, max_attempts: int) -> None:
    attempts = job.attempts + 1
    log.info("job %s: %s: %s (attempt %d)", job.job_id, invalid.reason, invalid.detail, attempts)
    if attempts >= max_attempts:
        _finish(job, ports, JobState.FAILED, failure_reason=invalid.reason)
        return
    ports.queue.to_chain_pending(job.job_id, ports.clock(), attempts=attempts, unsupported=False)
    log.info("job %s: %s", job.job_id, JobState.CHAIN_PENDING)


def _wait(job: Job, ports: JobPorts, wait: ExtractionWait) -> None:
    # An expected state of the outside world, so one line and no traceback.
    level = logging.WARNING if wait.kind is ExtractionClass.UNAVAILABLE else logging.ERROR
    error = wait.error
    log.log(
        level,
        # The message is the only place a zero quota shows, after two link sentences.
        # Flattened to keep one line, and cut, as a proxy may send a whole page.
        "job %s: gemini %s (code=%s status=%s reason=%s: %.500s); retrying in %ds",
        job.job_id,
        wait.kind,
        error.code,
        error.status,
        error.reason,
        " ".join(error.detail.split()),
        wait.delay.total_seconds(),
    )
    now = ports.clock()
    ports.queue.wait(job.job_id, now + wait.delay, now, waits=job.waits + 1)


def _kept_receipt(job: Job) -> NormalizedReceipt | None:
    if job.payload_version != PAYLOAD_VERSION or job.receipt_json is None:
        return None
    try:
        return NormalizedReceipt.model_validate_json(job.receipt_json)
    except ValidationError:
        return None


def _pass1_json(job: Job) -> str:
    if job.pass1_json is None:
        raise RuntimeError(f"job {job.job_id} is in {job.state} without its pass-1 result")
    return job.pass1_json


def _path(job: Job, ports: JobPorts) -> Path:
    item = job.accepted
    return ports.files.path_for(item.chat_id, item.message_id, item.mime)


def _source(job: Job) -> ReceiptSource:
    item = job.accepted
    return telegram_source(item.chat_id, item.message_id, buyer_name=item.buyer_name)


def _finish(
    job: Job,
    ports: JobPorts,
    state: JobState,
    *,
    failure_reason: FailureReason | None = None,
    receipt_id: str | None = None,
) -> None:
    ports.queue.finish(
        job.job_id, state, ports.clock(), failure_reason=failure_reason, receipt_id=receipt_id
    )
    log.info("job %s: %s", job.job_id, state)


def _react(job: Job, ports: JobPorts) -> None:
    # Best effort: the receipt is stored whatever happens to the reaction.
    try:
        ports.react_stored(job.accepted.chat_id, job.accepted.message_id)
    except Exception as exc:
        log.error("job %s: success reaction failed: %s: %s", job.job_id, type(exc).__name__, exc)
