"""Command line: `run` starts the service, `migrate` applies pending migrations."""

import argparse
import logging
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

import psycopg
from pydantic import ValidationError

from retail_receipts_import.adapters.queue.sqlite import QueueError
from retail_receipts_import.app.service import serve
from retail_receipts_import.app.texts import TextsError, load_texts
from retail_receipts_import.config import Settings
from retail_receipts_import.migrate import MigrationError, apply_migrations

MIGRATIONS_DIR = Path("migrations")

log = logging.getLogger("retail_receipts_import")


def main(argv: Sequence[str] | None = None, stop: threading.Event | None = None) -> int:
    """Parses CLI command, validates configuration, and runs migration or the ingestion service."""
    parser = argparse.ArgumentParser(prog="retail_receipts_import")
    parser.add_argument("command", choices=["run", "migrate"])
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    try:
        settings = Settings()  # type: ignore[call-arg]  # fields come from the environment
    except ValidationError as exc:
        # include_input=False: the rejected input would carry the tokens.
        for error in exc.errors(include_input=False, include_url=False):
            field = ".".join(str(part) for part in error["loc"]) or "config"
            log.error("invalid config: %s: %s", field, error["msg"])
        return 2
    logging.getLogger().setLevel(settings.log_level)
    # httpx logs every request URL at INFO, and a Telegram URL carries the bot token.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.command == "migrate":
        return _migrate(settings)
    return _run(settings, stop or threading.Event())


def _run(settings: Settings, stop: threading.Event) -> int:
    try:
        texts = load_texts(settings.texts_path)
    except TextsError as exc:
        log.error("%s", exc)
        return 2
    # Python as PID 1 in a container ignores SIGTERM unless it installs a handler.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    log.info("ready: env=%s database=%s", settings.env, settings.redacted_dsn(settings.db_user))
    try:
        serve(settings, texts, stop)
    except QueueError as exc:
        log.error("%s", exc)
        return 2
    log.info("stopped")
    return 0


def _migrate(settings: Settings) -> int:
    user, password = settings.migrate_db_user, settings.migrate_db_password
    if not user or password is None or not password.get_secret_value():
        log.error("migrate needs RRI_MIGRATE_DB_USER and RRI_MIGRATE_DB_PASSWORD")
        return 2
    target = settings.redacted_dsn(user)
    try:
        with psycopg.connect(settings.conninfo(user, password), autocommit=True) as conn:
            applied = apply_migrations(conn, MIGRATIONS_DIR)
    except (psycopg.Error, MigrationError) as exc:
        # Server messages do not normally echo the password; scrub it anyway.
        message = str(exc).replace(password.get_secret_value(), "**********")
        log.error("migrate against %s failed: %s", target, message)
        return 1
    log.info("migrate against %s: applied %d migration(s)", target, len(applied))
    return 0


def entrypoint() -> None:
    """Console script entrypoint exiting with the process status code from main()."""
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
