"""Unit tests for operational alerts."""

import logging

import pytest
from pydantic import BaseModel

from retail_receipts_import.adapters.postgres.chains import (
    ChainReference,
    ChainReferenceError,
    RejectedRow,
    RejectReason,
)
from retail_receipts_import.app.alerts import Alerts
from retail_receipts_import.app.notify import Notifier
from retail_receipts_import.domain.chains import KnownChain
from retail_receipts_import.domain.jobs import JobState
from retail_receipts_import.domain.outcomes import AlertKind
from tests.test_notify import ADMIN, TEXTS, RecordingTelegram

SPAR = KnownChain("spar", "Spar", ("SPAR", "Spar", "INTERSPAR"), ("46108893754",))
LIDL = KnownChain("lidl", "Lidl", ("LIDL", "Lidl"), ("66089976432",))
KAUFLAND = KnownChain("kaufland", "Kaufland", ("KAUFLAND", "Kaufland"), ("47432874968",))
DM = KnownChain("dm", "dm", ("DM", "dm"), ("94124811986",))
CLEAN_REFERENCE = ChainReference(chains=(SPAR, LIDL, KAUFLAND, DM), inactive_ids=(), rejected=())


@pytest.fixture
def telegram() -> RecordingTelegram:
    return RecordingTelegram()


@pytest.fixture
def alerts(telegram: RecordingTelegram) -> Alerts:
    return Alerts(Notifier(telegram, TEXTS, ADMIN), TEXTS)


def test_start_and_recover_send_once_to_admin(telegram: RecordingTelegram, alerts: Alerts) -> None:
    alerts.start(AlertKind.TELEGRAM_UNREACHABLE, "TelegramAPIError getUpdates")
    alerts.start(AlertKind.TELEGRAM_UNREACHABLE, "TelegramAPIError getUpdates")

    assert len(telegram.calls) == 1
    call = telegram.calls[0]
    assert call[0] == "message"
    assert call[1] == ADMIN
    assert call[2] == (
        f"{TEXTS.alerts[AlertKind.TELEGRAM_UNREACHABLE]}\n"
        "telegram_unreachable\n"
        "TelegramAPIError getUpdates"
    )

    alerts.recover(AlertKind.TELEGRAM_UNREACHABLE)
    alerts.recover(AlertKind.TELEGRAM_UNREACHABLE)

    assert len(telegram.calls) == 2
    rec = telegram.calls[1]
    assert rec[0] == "message"
    assert rec[1] == ADMIN
    assert rec[2] == (f"{TEXTS.recoveries[AlertKind.TELEGRAM_UNREACHABLE]}\ntelegram_unreachable")


def test_recover_inactive_key_sends_nothing(telegram: RecordingTelegram, alerts: Alerts) -> None:
    alerts.recover(AlertKind.GEMINI_CONFIG)
    assert telegram.calls == []


def test_failed_send_is_logged_and_recovery_still_sent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    telegram = RecordingTelegram(fail=True)
    alerts = Alerts(Notifier(telegram, TEXTS, ADMIN), TEXTS)

    with caplog.at_level(logging.ERROR):
        alerts.start(AlertKind.GEMINI_CONFIG, "code=404 status=NOT_FOUND reason=None")

    assert "alert gemini_config: admin message failed: RuntimeError" in caplog.text
    assert alerts.is_active(AlertKind.GEMINI_CONFIG)

    telegram.fail = False
    alerts.recover(AlertKind.GEMINI_CONFIG)

    assert len(telegram.calls) == 2
    assert telegram.calls[1] == (
        "message",
        ADMIN,
        f"{TEXTS.recoveries[AlertKind.GEMINI_CONFIG]}\ngemini_config",
        None,
    )
    assert not alerts.is_active(AlertKind.GEMINI_CONFIG)


def test_internal_state_keys_are_independent(telegram: RecordingTelegram, alerts: Alerts) -> None:
    alerts.start(AlertKind.INTERNAL, "step failed", JobState.CHAIN_PENDING)
    alerts.start(AlertKind.INTERNAL, "step failed", JobState.EXTRACT_PENDING)

    assert len(telegram.calls) == 2
    assert telegram.calls[0][2] == (
        f"{TEXTS.alerts[AlertKind.INTERNAL]}\ninternal:chain_pending\nstep failed"
    )
    assert telegram.calls[1][2] == (
        f"{TEXTS.alerts[AlertKind.INTERNAL]}\ninternal:extract_pending\nstep failed"
    )

    alerts.recover(AlertKind.INTERNAL, JobState.CHAIN_PENDING)
    assert len(telegram.calls) == 3
    assert telegram.calls[2][2] == (
        f"{TEXTS.recoveries[AlertKind.INTERNAL]}\ninternal:chain_pending"
    )

    assert not alerts.is_active(AlertKind.INTERNAL, JobState.CHAIN_PENDING)
    assert alerts.is_active(AlertKind.INTERNAL, JobState.EXTRACT_PENDING)


def test_check_reference_detects_missing_plugin(
    telegram: RecordingTelegram, alerts: Alerts
) -> None:
    ref = ChainReference(chains=(), inactive_ids=(), rejected=())
    returned = alerts.check_reference(ref)

    assert returned is ref
    assert len(telegram.calls) == 1
    assert "missing plug-in: spar" in telegram.calls[0][2]


def test_check_reference_detects_inactive_plugin(
    telegram: RecordingTelegram, alerts: Alerts
) -> None:
    ref = ChainReference(chains=(LIDL, KAUFLAND, DM), inactive_ids=("spar",), rejected=())
    returned = alerts.check_reference(ref)

    assert returned is ref
    assert len(telegram.calls) == 1
    assert "inactive plug-in: spar" in telegram.calls[0][2]


def test_check_reference_detects_rejected_rows(telegram: RecordingTelegram, alerts: Alerts) -> None:
    rejected = (
        RejectedRow("spar", RejectReason.DUPLICATE_ID),
        RejectedRow(None, RejectReason.NULL_FIELD),
    )
    ref = ChainReference(chains=(SPAR, LIDL, KAUFLAND, DM), inactive_ids=(), rejected=rejected)
    returned = alerts.check_reference(ref)

    assert returned is ref
    assert len(telegram.calls) == 1
    assert "rejected rows: spar: duplicate_id, null: null_field" in telegram.calls[0][2]


def test_check_reference_recovers_when_clean(telegram: RecordingTelegram, alerts: Alerts) -> None:
    bad_ref = ChainReference(chains=(LIDL, KAUFLAND, DM), inactive_ids=("spar",), rejected=())
    alerts.check_reference(bad_ref)
    assert alerts.is_active(AlertKind.CHAIN_REFERENCE)

    returned = alerts.check_reference(CLEAN_REFERENCE)
    assert returned is CLEAN_REFERENCE
    assert not alerts.is_active(AlertKind.CHAIN_REFERENCE)
    assert len(telegram.calls) == 2
    assert telegram.calls[1][2] == (
        f"{TEXTS.recoveries[AlertKind.CHAIN_REFERENCE]}\nchain_reference"
    )


def test_watch_generate_recovers_gemini_config(telegram: RecordingTelegram, alerts: Alerts) -> None:
    alerts.start(AlertKind.GEMINI_CONFIG, "code=403 status=PERMISSION_DENIED reason=None")
    assert alerts.is_active(AlertKind.GEMINI_CONFIG)

    def generate(data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        return "{}"

    watched = alerts.watch_generate(generate)
    result = watched(b"data", "image/png", "prompt", BaseModel)
    assert result == "{}"
    assert not alerts.is_active(AlertKind.GEMINI_CONFIG)
    assert len(telegram.calls) == 2
    assert telegram.calls[1][2] == f"{TEXTS.recoveries[AlertKind.GEMINI_CONFIG]}\ngemini_config"


def test_watch_generate_does_not_recover_on_exception(
    telegram: RecordingTelegram, alerts: Alerts
) -> None:
    alerts.start(AlertKind.GEMINI_CONFIG, "code=403 status=PERMISSION_DENIED reason=None")

    def failing_generate(data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        raise RuntimeError("api error")

    watched = alerts.watch_generate(failing_generate)
    with pytest.raises(RuntimeError, match="api error"):
        watched(b"data", "image/png", "prompt", BaseModel)

    assert alerts.is_active(AlertKind.GEMINI_CONFIG)
    assert len(telegram.calls) == 1


def test_read_checked_starts_alert_and_reraises_on_chain_reference_error(
    telegram: RecordingTelegram, alerts: Alerts
) -> None:
    error = ChainReferenceError("chain reference public.chains_v1 is unreadable (SQLSTATE 42P01)")

    def failing_read() -> ChainReference:
        raise error

    with pytest.raises(ChainReferenceError) as exc_info:
        alerts.read_checked(failing_read)

    assert exc_info.value is error
    assert alerts.is_active(AlertKind.CHAIN_REFERENCE)
    assert len(telegram.calls) == 1
    assert "SQLSTATE 42P01" in telegram.calls[0][2]


def test_read_checked_delegates_to_check_reference_on_success(
    telegram: RecordingTelegram, alerts: Alerts
) -> None:
    ref = alerts.read_checked(lambda: CLEAN_REFERENCE)
    assert ref is CLEAN_REFERENCE
    assert not alerts.is_active(AlertKind.CHAIN_REFERENCE)
    assert telegram.calls == []
