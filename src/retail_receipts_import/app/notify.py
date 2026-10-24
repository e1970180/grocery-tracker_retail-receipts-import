"""Tells the sender and the admin how a receipt ended, with every text from the texts file.

Each send is best effort: the client has already applied Telegram's retry rules, so a failure
here is only logged, and it never stops the other sends or touches the job.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from retail_receipts_import.app.texts import Texts
from retail_receipts_import.domain.intake import Accepted
from retail_receipts_import.domain.jobs import JobState
from retail_receipts_import.domain.outcomes import FailureReason, Outcome

log = logging.getLogger(__name__)

# Failures the admin can only judge by looking at the receipt itself; the others have no
# usable file, as it was never downloaded.
COPY_TO_ADMIN = frozenset(
    {
        FailureReason.ITEMS_SETTLEMENT_MISMATCH,
        FailureReason.TOTAL_SETTLEMENT_MISMATCH,
        FailureReason.NO_VALID_RESULT,
    }
)


class Telegram(Protocol):
    def set_message_reaction(self, chat_id: int, message_id: int, reaction: str | None) -> None: ...

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None) -> None: ...

    def send_document(self, chat_id: int, path: Path, caption: str) -> None: ...


class Notifier:
    def __init__(self, telegram: Telegram, texts: Texts, admin_chat_id: int) -> None:
        self._telegram = telegram
        self._texts = texts
        self._admin_chat_id = admin_chat_id

    def finished(
        self,
        job_id: int,
        item: Accepted,
        state: JobState,
        path: Path,
        *,
        failure_reason: FailureReason | None = None,
        store_name: str | None = None,
    ) -> None:
        """Sends what a final state tells people; called only once that state is persisted."""
        where = f"job {job_id}"
        match state:
            case JobState.STORED:
                self._react(where, item, self._texts.reactions[Outcome.STORED])
            case JobState.DUPLICATE:
                self._react(where, item, self._texts.reactions[Outcome.DUPLICATE])
                self._reply(where, item, Outcome.DUPLICATE)
            case JobState.UNSUPPORTED_CHAIN:
                # An earlier Gemini wait may have left the in-progress reaction.
                self._react(where, item, None)
                self._reply(where, item, Outcome.UNSUPPORTED_CHAIN)
                self._admin(where, job_id, item, Outcome.UNSUPPORTED_CHAIN, store_name)
            case JobState.FAILED:
                if failure_reason is None:
                    raise ValueError(f"{where} failed without a reason")
                self._react(where, item, self._texts.reactions[Outcome.FAILED])
                self._reply(where, item, failure_reason)
                if failure_reason in COPY_TO_ADMIN:
                    self._admin_copy(where, job_id, item, failure_reason, path)
                else:
                    self._admin(where, job_id, item, failure_reason, None)
            case _:
                raise ValueError(f"{where}: {state} is not a final state")

    def in_progress(self, job_id: int, item: Accepted) -> None:
        self._react(f"job {job_id}", item, self._texts.reactions[Outcome.IN_PROGRESS])

    def not_accepted(self, chat_id: int, message_id: int) -> None:
        emoji = self._texts.reactions[Outcome.NOT_ACCEPTED]
        self._send(
            f"message {message_id}",
            "reaction",
            lambda: self._telegram.set_message_reaction(chat_id, message_id, emoji),
        )

    def _react(self, where: str, item: Accepted, emoji: str | None) -> None:
        self._send(
            where,
            "reaction",
            lambda: self._telegram.set_message_reaction(item.chat_id, item.message_id, emoji),
        )

    def _reply(self, where: str, item: Accepted, key: Outcome | FailureReason) -> None:
        text = self._texts.sender_messages[key]
        self._send(
            where,
            "sender message",
            lambda: self._telegram.send_message(item.chat_id, text, reply_to=item.message_id),
        )

    def _admin(
        self,
        where: str,
        job_id: int,
        item: Accepted,
        key: Outcome | FailureReason,
        store_name: str | None,
    ) -> None:
        text = _admin_text(self._texts.admin_messages[key], job_id, item, store_name)
        self._send(
            where, "admin message", lambda: self._telegram.send_message(self._admin_chat_id, text)
        )

    def _admin_copy(
        self, where: str, job_id: int, item: Accepted, reason: FailureReason, path: Path
    ) -> None:
        caption = _admin_text(self._texts.admin_messages[reason], job_id, item, None)
        self._send(
            where,
            "admin file copy",
            lambda: self._telegram.send_document(self._admin_chat_id, path, caption),
        )

    def _send(self, where: str, what: str, send: Callable[[], None]) -> None:
        try:
            send()
        except Exception as exc:
            log.error("%s: %s failed: %s: %s", where, what, type(exc).__name__, exc)


def _admin_text(text: str, job_id: int, item: Accepted, store_name: str | None) -> str:
    # Plain data lines after the text, so the texts file stays the only wording.
    lines = [text, item.buyer_name, f"#{job_id}"]
    if store_name:
        lines.append(store_name)
    return "\n".join(lines)
