"""Wires the adapters into the loop for the `run` command."""

import functools
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from retail_receipts_import.adapters.files.store import FileStore
from retail_receipts_import.adapters.gemini import images
from retail_receipts_import.adapters.gemini.client import GeminiClient
from retail_receipts_import.adapters.postgres.chains import read_chain_reference
from retail_receipts_import.adapters.postgres.receipts import write_receipt
from retail_receipts_import.adapters.queue.sqlite import Queue
from retail_receipts_import.adapters.telegram.client import TelegramClient
from retail_receipts_import.adapters.telegram.download import download_file
from retail_receipts_import.app import loop
from retail_receipts_import.app.jobs import JobPorts
from retail_receipts_import.app.pipeline import Ports, Result, process_file
from retail_receipts_import.app.texts import Texts
from retail_receipts_import.config import Settings
from retail_receipts_import.domain.extraction import classify
from retail_receipts_import.domain.intake import MAX_FILE_BYTES
from retail_receipts_import.domain.outcomes import Outcome
from retail_receipts_import.domain.receipt import ReceiptSource


def serve(settings: Settings, texts: Texts, stop: threading.Event) -> None:
    gemini = GeminiClient.from_settings(settings)
    queue = Queue(settings.data_dir / "queue.sqlite3")
    stored_emoji = texts.reactions[Outcome.STORED]
    prepare_image = functools.partial(images.prepare, max_pixels=settings.image_max_pixels)
    # No wait count is kept on the job yet, so every wait is the first one.
    classify_failure = functools.partial(
        classify,
        waits=0,
        initial_s=settings.gemini_backoff_initial_s,
        cap_s=settings.gemini_backoff_cap_s,
    )

    def process(path: Path, mime: str, source: ReceiptSource) -> Result:
        # A connection per job, so one dropped by the server never outlives the job it broke.
        conninfo = settings.conninfo(settings.db_user, settings.db_password)
        with psycopg.connect(conninfo, autocommit=True) as conn:
            ports = Ports(
                generate=gemini.generate,
                write=functools.partial(write_receipt, conn),
                read_chain_reference=functools.partial(read_chain_reference, conn),
                prepare=prepare_image,
                classify=classify_failure,
            )
            return process_file(path, mime, source, ports)

    try:
        with TelegramClient(settings.telegram_bot_token) as telegram:
            ports = JobPorts(
                queue=queue,
                files=FileStore(settings.data_dir / "files"),
                download=lambda file_id, size: download_file(
                    telegram, file_id, size, MAX_FILE_BYTES
                ),
                process=process,
                react_stored=lambda chat_id, message_id: telegram.set_message_reaction(
                    chat_id, message_id, stored_emoji
                ),
                clock=lambda: datetime.now(UTC),
            )
            loop_settings = loop.LoopSettings(
                allowed_user_ids=frozenset(settings.allowed_user_ids),
                poll_timeout_s=settings.telegram_poll_timeout_s,
                retry_delay=timedelta(seconds=settings.job_retry_delay_s),
            )
            loop.run(telegram, ports, loop_settings, stop)
    finally:
        queue.close()
