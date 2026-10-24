"""The settings reach the pipeline ports and the loop; nothing here opens a connection."""

import io
from datetime import timedelta
from typing import Any, cast

import psycopg
import pytest
from PIL import Image

from retail_receipts_import.adapters.postgres.chains import ChainReferenceError
from retail_receipts_import.app.alerts import Alerts
from retail_receipts_import.app.notify import Notifier
from retail_receipts_import.app.service import loop_settings, pipeline_ports
from retail_receipts_import.config import Settings
from retail_receipts_import.domain.extraction import GeminiCallError
from retail_receipts_import.domain.outcomes import AlertKind
from tests.test_notify import ADMIN, TEXTS, RecordingTelegram

# Gemini unavailable with no delay of its own, so only the backoff settings decide the wait.
NO_SERVER_DELAY = GeminiCallError(code=503, status="UNAVAILABLE")


@pytest.fixture
def settings(rri_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Settings:
    # All distinct and none the default, so a setting bound to the wrong place shows.
    for name, value in {
        "RRI_GEMINI_BACKOFF_INITIAL_S": "700",
        "RRI_GEMINI_BACKOFF_CAP_S": "2000",
        "RRI_JOB_RETRY_DELAY_S": "900",
        "RRI_IMAGE_MAX_PIXELS": "100",
        "RRI_JOB_MAX_ATTEMPTS": "4",
        "RRI_TELEGRAM_POLL_TIMEOUT_S": "25",
    }.items():
        monkeypatch.setenv(name, value)
    return Settings()  # type: ignore[call-arg]


def test_pipeline_ports_take_the_backoff_and_pixel_cap_from_settings(settings: Settings) -> None:
    unused_conn = cast(psycopg.Connection[tuple[Any, ...]], object())
    alerts = Alerts(Notifier(RecordingTelegram(), TEXTS, ADMIN), TEXTS)
    ports = pipeline_ports(settings, unused_conn, lambda data, mime, prompt, schema: "", alerts)
    # The first wait alone cannot tell the initial delay from the cap.
    assert ports.classify(NO_SERVER_DELAY, 0).delay == timedelta(seconds=700)
    assert ports.classify(NO_SERVER_DELAY, 5).delay == timedelta(seconds=2000)

    image = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(image, format="PNG")
    prepared = Image.open(io.BytesIO(ports.prepare(image.getvalue(), "image/png")))
    assert prepared.width * prepared.height <= 100


def test_pipeline_ports_reads_reference_through_check(settings: Settings) -> None:
    class FailingConnection:
        def execute(self, *args: Any, **kwargs: Any) -> Any:
            err = psycopg.Error("no view")
            err.sqlstate = "42P01"
            raise err

    telegram = RecordingTelegram()
    alerts = Alerts(Notifier(telegram, TEXTS, ADMIN), TEXTS)
    ports = pipeline_ports(
        settings,
        cast(psycopg.Connection[tuple[Any, ...]], FailingConnection()),
        lambda d, m, p, s: "",
        alerts,
    )

    with pytest.raises(ChainReferenceError):
        ports.read_chain_reference()

    assert alerts.is_active(AlertKind.CHAIN_REFERENCE)
    assert len(telegram.calls) == 1
    assert "SQLSTATE 42P01" in telegram.calls[0][2]


def test_loop_settings_come_from_settings(settings: Settings) -> None:
    built = loop_settings(settings)
    assert built.retry_delay == timedelta(seconds=900)
    assert (built.max_attempts, built.poll_timeout_s) == (4, 25)
    assert built.allowed_user_ids == frozenset({12345})
