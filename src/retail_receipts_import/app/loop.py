"""The service's single loop: long-poll Telegram, persist new jobs, run every due job, repeat."""

import logging
import threading
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from retail_receipts_import.app.jobs import JobPorts, advance
from retail_receipts_import.domain.intake import accept

log = logging.getLogger(__name__)

# Only new messages: an edit would arrive as a second copy of a receipt already taken.
ALLOWED_UPDATES = ("message",)
# The client has already retried; this only keeps an outage from spinning the loop.
POLL_ERROR_BACKOFF_S = 5.0


class Updates(Protocol):
    def get_updates(
        self, *, offset: int | None, timeout: int, allowed_updates: Sequence[str] | None = None
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class LoopSettings:
    allowed_user_ids: Collection[int]
    poll_timeout_s: int
    # Until job waits and attempts exist, a failed step simply waits this long and runs again.
    retry_delay: timedelta


def run(telegram: Updates, ports: JobPorts, settings: LoopSettings, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            poll(telegram, ports, settings)
        except Exception as exc:
            log.error("getUpdates failed: %s: %s", type(exc).__name__, exc)
            stop.wait(POLL_ERROR_BACKOFF_S)
        # Jobs already downloaded need only Gemini and PostgreSQL, so a Telegram outage
        # must not hold them back.
        run_due(ports, settings, stop)


def poll(telegram: Updates, ports: JobPorts, settings: LoopSettings) -> None:
    updates = telegram.get_updates(
        offset=ports.queue.read_offset(),
        timeout=settings.poll_timeout_s,
        allowed_updates=ALLOWED_UPDATES,
    )
    if not updates:
        return
    accepted = [a for u in updates if (a := accept(u, settings.allowed_user_ids)) is not None]
    # Filtered updates are acknowledged too, in the same transaction as the accepted ones.
    next_offset = max(int(u["update_id"]) for u in updates) + 1
    ports.queue.enqueue(accepted, next_offset, ports.clock())
    log.info("polled %d update(s), %d job(s)", len(updates), len(accepted))


def run_due(ports: JobPorts, settings: LoopSettings, stop: threading.Event) -> None:
    for job in ports.queue.due_jobs(ports.clock()):
        if stop.is_set():
            return
        try:
            advance(job, ports)
        except Exception:
            # Adapters redact their secrets, so the traceback is safe to log.
            log.exception("job %s failed in its step; retrying later", job.job_id)
            now = ports.clock()
            ports.queue.postpone(job.job_id, now + settings.retry_delay, now)
