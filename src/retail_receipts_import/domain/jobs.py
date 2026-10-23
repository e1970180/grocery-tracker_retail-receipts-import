"""A receipt job and its states. The jobs module in `app` is the only one that changes them."""

from dataclasses import dataclass
from enum import StrEnum

from retail_receipts_import.domain.intake import Accepted


class JobState(StrEnum):
    RECEIVED = "received"
    CHAIN_PENDING = "chain_pending"
    EXTRACT_PENDING = "extract_pending"
    WRITE_PENDING = "write_pending"
    STORED = "stored"
    DUPLICATE = "duplicate"
    UNSUPPORTED_CHAIN = "unsupported_chain"
    FAILED = "failed"


FINAL_STATES = frozenset(
    {JobState.STORED, JobState.DUPLICATE, JobState.UNSUPPORTED_CHAIN, JobState.FAILED}
)


@dataclass(frozen=True)
class Job:
    job_id: int
    accepted: Accepted
    state: JobState
    # Gemini results the file got wrong so far, across both passes.
    attempts: int = 0
    # Gemini waits since the last transition or attempt; nothing grows it yet.
    waits: int = 0
    # Starts of the current step with no result recorded, so a crash inside a step shows.
    step_starts: int = 0
    # The last attempt was an unsupported chain; a second one in a row ends the job.
    unsupported: bool = False
    # The pass-1 result, kept from `extract_pending` on so a restart does not repeat pass 1.
    pass1_json: str | None = None
    # The checked receipt and its payload version, kept in `write_pending` with its id.
    receipt_json: str | None = None
    payload_version: int | None = None
    receipt_id: str | None = None
