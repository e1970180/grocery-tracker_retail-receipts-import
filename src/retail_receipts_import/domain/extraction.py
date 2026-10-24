"""What a failed Gemini call means for the job: wait, wait for the admin, or give up on the file.

Pure: the adapter fills `GeminiCallError` with plain values, and `classify` decides from those
alone, so every unit that meets a Gemini failure reads it the same way.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class ExtractionClass(StrEnum):
    """Categorizes the nature of a Gemini API error for retry or abandonment decisions."""

    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    INVALID = "invalid"


@dataclass(eq=False)
class GeminiCallError(Exception):
    """A failed Gemini call, reduced to the values the classification needs.

    It holds no SDK or httpx object: those reach the request and its API key header.
    """

    code: int | None = None
    status: str | None = None
    reason: str | None = None
    retry_delay_s: int | None = None
    retry_after_s: int | None = None
    transport: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        super().__init__(self.detail)

    def __str__(self) -> str:
        return f"{self.code} {self.status} {self.reason}: {self.detail}"


@dataclass(frozen=True)
class Classification:
    """Classification of an extraction error along with required backoff retry delay."""

    kind: ExtractionClass
    # How long the job waits before the next try; zero for an invalid result.
    delay: timedelta


# Statuses that no retry can fix: the key, the project or the model must change first.
_CONFIG_STATUSES = frozenset(
    {"UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND", "FAILED_PRECONDITION"}
)
_CONFIG_REASONS = frozenset({"API_KEY_INVALID"})
# A non-JSON error body carries only the HTTP reason phrase, so these codes stand on their own.
_CONFIG_CODES = frozenset({401, 403, 404})
# Request timeout, aborted and cancelled: the request failed in passing, not because of the file.
_TRANSIENT_CODES = frozenset({408, 409, 499})
# A quota the project does not have at all reads like a rate limit; only the message tells.
_ZERO_QUOTA = re.compile(r"limit: 0(?![\d.])")


def classify(error: GeminiCallError, waits: int, initial_s: int, cap_s: int) -> Classification:
    """Maps a sanitized Gemini error to its failure category and backoff delay."""
    kind = _kind(error)
    if kind is ExtractionClass.INVALID:
        return Classification(kind, timedelta(0))
    # A blocked job waits for the admin, so a short server delay would only repeat the refusal.
    if kind is ExtractionClass.BLOCKED:
        delay_s = _backoff_s(waits, initial_s, cap_s)
    else:
        delay_s = _delay_s(error, waits, initial_s, cap_s)
    return Classification(kind, timedelta(seconds=delay_s))


def _kind(error: GeminiCallError) -> ExtractionClass:
    if error.transport or error.code is None:
        return ExtractionClass.UNAVAILABLE
    if error.code == 429:
        if _ZERO_QUOTA.search(error.detail):
            return ExtractionClass.BLOCKED
        return ExtractionClass.UNAVAILABLE
    if not 400 <= error.code < 500 or error.code in _TRANSIENT_CODES:
        return ExtractionClass.UNAVAILABLE
    if (
        error.status in _CONFIG_STATUSES
        or error.reason in _CONFIG_REASONS
        or error.code in _CONFIG_CODES
    ):
        return ExtractionClass.BLOCKED
    return ExtractionClass.INVALID


def _delay_s(error: GeminiCallError, waits: int, initial_s: int, cap_s: int) -> int:
    if error.retry_delay_s is not None:
        delay = error.retry_delay_s
    elif error.retry_after_s is not None:
        delay = error.retry_after_s
    else:
        delay = _backoff_s(waits, initial_s, cap_s)
    return max(1, delay)


def _backoff_s(waits: int, initial_s: int, cap_s: int) -> int:
    return max(1, min(cap_s, initial_s << waits))
