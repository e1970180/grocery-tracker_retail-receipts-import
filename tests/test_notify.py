"""What each final state tells the sender and the admin, with the real texts file."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from retail_receipts_import.app.notify import COPY_TO_ADMIN, Notifier
from retail_receipts_import.app.texts import load_texts
from retail_receipts_import.domain.intake import Accepted, FileKind
from retail_receipts_import.domain.jobs import JobState
from retail_receipts_import.domain.outcomes import FailureReason
from tests.conftest import REPO

TEXTS = load_texts(REPO / "texts" / "messages.toml")
SENDER = 12345
ADMIN = 777
ITEM = Accepted(
    chat_id=SENDER,
    message_id=3,
    buyer_name="Ana",
    file_id="f3",
    kind=FileKind.DOCUMENT,
    mime="application/pdf",
    declared_size=16,
)
NO_COPY = sorted(set(FailureReason) - COPY_TO_ADMIN)


@dataclass
class RecordingTelegram:
    """Records every send; `fail` makes each one raise after it is recorded."""

    calls: list[tuple[Any, ...]] = field(default_factory=list)
    # What was durable at each send, from `observe`, so a test can prove the order of effects.
    seen: list[Any] = field(default_factory=list)
    observe: Callable[[], Any] | None = None
    fail: bool = False

    def set_message_reaction(self, chat_id: int, message_id: int, reaction: str | None) -> None:
        self._record("reaction", chat_id, message_id, reaction)

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None) -> None:
        self._record("message", chat_id, text, reply_to)

    def send_document(self, chat_id: int, path: Path, caption: str) -> None:
        self._record("document", chat_id, path.name, caption)

    def _record(self, *call: Any) -> None:
        self.calls.append(call)
        self.seen.append(None if self.observe is None else self.observe())
        if self.fail:
            raise RuntimeError("telegram down")


def admin_text(reason: str, *extra: str) -> str:
    return "\n".join([TEXTS.admin_messages[FailureReason(reason)], "Ana", "#5", *extra])


@pytest.fixture
def telegram() -> RecordingTelegram:
    return RecordingTelegram()


def finish(telegram: RecordingTelegram, state: JobState, **kwargs: Any) -> None:
    Notifier(telegram, TEXTS, ADMIN).finished(5, ITEM, state, Path("12345_3.pdf"), **kwargs)


def test_stored_gets_only_the_success_reaction(telegram: RecordingTelegram) -> None:
    finish(telegram, JobState.STORED)
    assert telegram.calls == [("reaction", SENDER, 3, "👍")]


def test_duplicate_gets_its_reaction_and_message(telegram: RecordingTelegram) -> None:
    finish(telegram, JobState.DUPLICATE)
    assert telegram.calls == [
        ("reaction", SENDER, 3, "🤝"),
        ("message", SENDER, "Данный чек уже внесен в систему", 3),
    ]


@pytest.mark.parametrize(("store_name", "extra"), [("KONZUM", ["KONZUM"]), (None, [])])
def test_unsupported_chain_clears_the_reaction_and_tells_both(
    telegram: RecordingTelegram, store_name: str | None, extra: list[str]
) -> None:
    finish(telegram, JobState.UNSUPPORTED_CHAIN, store_name=store_name)
    admin = "\n".join(["Чек неподдерживаемой сети.", "Ana", "#5", *extra])
    assert telegram.calls == [
        ("reaction", SENDER, 3, None),
        ("message", SENDER, "Чеки этой сети пока не поддерживаются.", 3),
        ("message", ADMIN, admin, None),
    ]


@pytest.mark.parametrize("reason", sorted(COPY_TO_ADMIN))
def test_failure_the_admin_must_see_comes_with_the_file(
    telegram: RecordingTelegram, reason: FailureReason
) -> None:
    finish(telegram, JobState.FAILED, failure_reason=reason)
    assert telegram.calls == [
        ("reaction", SENDER, 3, "👎"),
        ("message", SENDER, TEXTS.sender_messages[reason], 3),
        ("document", ADMIN, "12345_3.pdf", admin_text(reason)),
    ]


@pytest.mark.parametrize("reason", NO_COPY)
def test_failure_without_a_file_sends_the_admin_a_message(
    telegram: RecordingTelegram, reason: FailureReason
) -> None:
    finish(telegram, JobState.FAILED, failure_reason=reason)
    assert telegram.calls == [
        ("reaction", SENDER, 3, "👎"),
        ("message", SENDER, TEXTS.sender_messages[reason], 3),
        ("message", ADMIN, admin_text(reason), None),
    ]


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (JobState.DUPLICATE, None),
        (JobState.UNSUPPORTED_CHAIN, None),
        (JobState.FAILED, FailureReason.NO_VALID_RESULT),
    ],
)
def test_a_failed_send_skips_no_other_send(
    telegram: RecordingTelegram,
    caplog: pytest.LogCaptureFixture,
    state: JobState,
    reason: FailureReason | None,
) -> None:
    finish(telegram, state, failure_reason=reason)
    working = list(telegram.calls)
    failing = RecordingTelegram(fail=True)
    finish(failing, state, failure_reason=reason)
    assert failing.calls == working
    assert caplog.text.count("job 5:") == len(working)


def test_in_progress_and_not_accepted_reactions(telegram: RecordingTelegram) -> None:
    notifier = Notifier(telegram, TEXTS, ADMIN)
    notifier.in_progress(5, ITEM)
    notifier.not_accepted(SENDER, 9)
    assert telegram.calls == [("reaction", SENDER, 3, "👀"), ("reaction", SENDER, 9, "🙈")]


def test_reactions_that_fail_are_only_logged(caplog: pytest.LogCaptureFixture) -> None:
    notifier = Notifier(RecordingTelegram(fail=True), TEXTS, ADMIN)
    notifier.in_progress(5, ITEM)
    notifier.not_accepted(SENDER, 9)
    assert "job 5: reaction failed" in caplog.text
    assert "message 9: reaction failed" in caplog.text


def test_admin_sends_message_to_admin_chat(telegram: RecordingTelegram) -> None:
    notifier = Notifier(telegram, TEXTS, ADMIN)
    notifier.admin("alert test", "alert text")
    assert telegram.calls == [("message", ADMIN, "alert text", None)]


def test_admin_failure_is_only_logged(caplog: pytest.LogCaptureFixture) -> None:
    notifier = Notifier(RecordingTelegram(fail=True), TEXTS, ADMIN)
    notifier.admin("alert test", "alert text")
    assert "alert test: admin message failed" in caplog.text
