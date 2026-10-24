"""Closed sets of receipt outcomes and failure reasons, and what each one tells people.

The texts file is keyed by these values, so renaming a member is a texts-file change too.
"""

from enum import StrEnum


class Outcome(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    UNSUPPORTED_CHAIN = "unsupported_chain"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    NOT_ACCEPTED = "not_accepted"


class FailureReason(StrEnum):
    ITEMS_SETTLEMENT_MISMATCH = "items_settlement_mismatch"
    TOTAL_SETTLEMENT_MISMATCH = "total_settlement_mismatch"
    NO_VALID_RESULT = "no_valid_result"
    FILE_TOO_LARGE = "file_too_large"
    FILE_UNAVAILABLE = "file_unavailable"
    INTERNAL_ERROR = "internal_error"


class AlertKind(StrEnum):
    POSTGRES_UNREACHABLE = "postgres_unreachable"
    GEMINI_CONFIG = "gemini_config"
    TELEGRAM_UNREACHABLE = "telegram_unreachable"
    CHAIN_REFERENCE = "chain_reference"
    INTERNAL = "internal"


# Which outcomes carry which kind of text. A failed outcome takes its sender message and
# admin notice from its failure reason, so FAILED itself carries only the reaction.
OUTCOMES_WITH_REACTION = frozenset(
    {
        Outcome.STORED,
        Outcome.DUPLICATE,
        Outcome.FAILED,
        Outcome.IN_PROGRESS,
        Outcome.NOT_ACCEPTED,
    }
)
OUTCOMES_WITH_SENDER_MESSAGE = frozenset({Outcome.DUPLICATE, Outcome.UNSUPPORTED_CHAIN})
OUTCOMES_WITH_ADMIN_MESSAGE = frozenset({Outcome.UNSUPPORTED_CHAIN})
