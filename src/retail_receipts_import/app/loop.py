"""The service's single loop: long-poll Telegram, persist new jobs, run every due job, repeat."""

import logging
import math
import threading
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from retail_receipts_import.adapters.telegram.client import (
    TelegramAPIError,
    TelegramRetryExhaustedError,
)
from retail_receipts_import.app import jobs
from retail_receipts_import.app.jobs import JobPorts
from retail_receipts_import.domain.intake import Accepted, NotAccepted, accept
from retail_receipts_import.domain.outcomes import AlertKind

log = logging.getLogger(__name__)

# Only new messages: an edit would arrive as a second copy of a receipt already taken.
ALLOWED_UPDATES = ("message",)
# The client has already retried; this only keeps an outage from spinning the loop.
POLL_ERROR_BACKOFF_S = 5.0


class Updates(Protocol):
    """Protocol for fetching new updates from the Telegram Bot API."""

    def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        """Polls for pending Telegram updates."""
        ...


@dataclass(frozen=True)
class LoopSettings:
    """Configuration parameters governing the main polling loop and job retry cadence."""

    allowed_user_ids: Collection[int]
    poll_timeout_s: int
    # A connection error, unavailable download, or unreadable reference waits this long.
    retry_delay: timedelta
    max_attempts: int


def run(telegram: Updates, ports: JobPorts, settings: LoopSettings, stop: threading.Event) -> None:
    """Runs the main event loop, alternating between polling Telegram and executing due jobs."""
    while not stop.is_set():
        try:
            poll(telegram, ports, settings)
        except (TelegramAPIError, TelegramRetryExhaustedError) as exc:
            ports.alerts.start(AlertKind.TELEGRAM_UNREACHABLE, f"{type(exc).__name__} {exc.method}")
            log.error("getUpdates failed: %s: %s", type(exc).__name__, exc)
            stop.wait(POLL_ERROR_BACKOFF_S)
        except Exception as exc:
            log.error("getUpdates failed: %s: %s", type(exc).__name__, exc)
            stop.wait(POLL_ERROR_BACKOFF_S)
        # Jobs already downloaded need only Gemini and PostgreSQL, so a Telegram outage
        # must not hold them back.
        run_due(ports, settings, stop)


def poll(telegram: Updates, ports: JobPorts, settings: LoopSettings) -> None:
    """Polls Telegram, enqueues accepted receipt jobs, and replies to refused messages."""
    updates = telegram.get_updates(
        offset=ports.queue.read_offset(),
        timeout=_poll_timeout(ports, settings),
        allowed_updates=ALLOWED_UPDATES,
    )
    ports.alerts.recover(AlertKind.TELEGRAM_UNREACHABLE)
    if not updates:
        return
    results = [accept(u, settings.allowed_user_ids) for u in updates]
    accepted = [r for r in results if isinstance(r, Accepted)]
    refused = [r for r in results if isinstance(r, NotAccepted)]
    # Filtered updates are acknowledged too, in the same transaction as the accepted ones.
    next_offset = max(int(u["update_id"]) for u in updates) + 1
    ports.queue.enqueue(accepted, next_offset, ports.clock())
    log.info("polled %d update(s), %d job(s)", len(updates), len(accepted))
    # After the commit, so a slow or failing reaction never holds back the batch.
    for item in refused:
        ports.notify.not_accepted(item.chat_id, item.message_id)


def _poll_timeout(ports: JobPorts, settings: LoopSettings) -> int:
    """Ends the long poll when the next job is due, so a waiting job is not held up by it."""
    next_due = ports.queue.next_due_at()
    if next_due is None:
        return settings.poll_timeout_s
    # Rounded up: at most a second late, and never a run of zero-timeout polls before it is due.
    until_due = math.ceil((next_due - ports.clock()).total_seconds())
    return min(max(until_due, 0), settings.poll_timeout_s)


def run_due(ports: JobPorts, settings: LoopSettings, stop: threading.Event) -> None:
    """Dispatches all background jobs that have reached their due time."""
    for job in ports.queue.due_jobs(ports.clock()):
        if stop.is_set():
            return
        try:
            jobs.run(job, ports, settings.max_attempts, settings.retry_delay)
        except Exception:
            # The boundary in jobs.py catches per-job errors; this only moves on
            # to the next job if a fault inside the boundary escapes.
            log.exception("job %s failed in error boundary", job.job_id)
