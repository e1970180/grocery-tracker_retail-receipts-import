"""Wires the adapters into the loop for the `run` command."""

import contextlib
import functools
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from retail_receipts_import.adapters.files.store import FileStore
from retail_receipts_import.adapters.gemini import images
from retail_receipts_import.adapters.gemini.client import GeminiClient
from retail_receipts_import.adapters.postgres.chains import read_chain_reference
from retail_receipts_import.adapters.postgres.receipts import find_other_source, write_receipt
from retail_receipts_import.adapters.queue.sqlite import Queue
from retail_receipts_import.adapters.telegram.client import TelegramClient
from retail_receipts_import.adapters.telegram.download import download_file
from retail_receipts_import.app import jobs, loop
from retail_receipts_import.app.jobs import JobPorts
from retail_receipts_import.app.notify import Notifier
from retail_receipts_import.app.pipeline import Generate, Ports
from retail_receipts_import.app.texts import Texts
from retail_receipts_import.config import Settings
from retail_receipts_import.domain.extraction import classify
from retail_receipts_import.domain.intake import MAX_FILE_BYTES


def pipeline_ports(
    settings: Settings, conn: psycopg.Connection[tuple[Any, ...]], generate: Generate
) -> Ports:
    """The pipeline's ports over one connection; separate from `serve` so a test can check them."""
    return Ports(
        generate=generate,
        write=functools.partial(write_receipt, conn),
        find_other_source=functools.partial(find_other_source, conn),
        read_chain_reference=functools.partial(read_chain_reference, conn),
        prepare=functools.partial(images.prepare, max_pixels=settings.image_max_pixels),
        classify=functools.partial(
            classify,
            initial_s=settings.gemini_backoff_initial_s,
            cap_s=settings.gemini_backoff_cap_s,
        ),
    )


def loop_settings(settings: Settings) -> loop.LoopSettings:
    return loop.LoopSettings(
        allowed_user_ids=frozenset(settings.allowed_user_ids),
        poll_timeout_s=settings.telegram_poll_timeout_s,
        retry_delay=timedelta(seconds=settings.job_retry_delay_s),
        max_attempts=settings.job_max_attempts,
    )


def serve(settings: Settings, texts: Texts, stop: threading.Event) -> None:
    gemini = GeminiClient.from_settings(settings)
    queue = Queue(settings.data_dir / "queue.sqlite3")

    @contextlib.contextmanager
    def open_pipeline() -> Iterator[Ports]:
        # A connection per job, so one dropped by the server never outlives the job it broke.
        conninfo = settings.conninfo(settings.db_user, settings.db_password)
        with psycopg.connect(conninfo, autocommit=True) as conn:
            yield pipeline_ports(settings, conn, gemini.generate)

    try:
        with TelegramClient(settings.telegram_bot_token) as telegram:
            ports = JobPorts(
                queue=queue,
                files=FileStore(settings.data_dir / "files"),
                download=lambda file_id, size: download_file(
                    telegram, file_id, size, MAX_FILE_BYTES
                ),
                open_pipeline=open_pipeline,
                notify=Notifier(telegram, texts, settings.admin_chat_id),
                clock=lambda: datetime.now(UTC),
            )
            jobs.sweep_files(ports)
            loop.run(telegram, ports, loop_settings(settings), stop)
    finally:
        queue.close()
