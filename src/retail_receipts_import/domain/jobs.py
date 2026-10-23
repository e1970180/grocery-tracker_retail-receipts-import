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
