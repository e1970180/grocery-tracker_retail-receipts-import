import threading
from pathlib import Path

import psycopg
import pytest

from retail_receipts_import import __main__ as cli
from tests.conftest import DB_PASSWORD, GEMINI_KEY, REPO, TOKEN


def _stopped() -> threading.Event:
    stop = threading.Event()
    stop.set()
    return stop


def _assert_no_secrets(text: str) -> None:
    for secret in (TOKEN, GEMINI_KEY, DB_PASSWORD):
        assert secret not in text


def test_run_logs_readiness(rri_env: dict[str, str], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    assert cli.main(["run"], stop=_stopped()) == 0
    assert "ready: env=dev database=postgresql://writer@db.example:5432/grocery-tracker-dev" in (
        caplog.text
    )
    _assert_no_secrets(caplog.text)


def test_run_refuses_environment_mismatch_without_leaking_secrets(
    rri_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("RRI_ENV", "prod")
    assert cli.main(["run"], stop=_stopped()) == 2
    assert "environment mismatch" in caplog.text
    assert "ready" not in caplog.text
    captured = capsys.readouterr()
    _assert_no_secrets(caplog.text + captured.out + captured.err)


def test_run_refuses_texts_file_missing_a_key(
    rri_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    texts = (REPO / "texts" / "messages.toml").read_text(encoding="utf-8")
    broken = tmp_path / "broken.toml"
    broken.write_text(texts.replace('stored = "👍"\n', ""), encoding="utf-8")
    monkeypatch.setenv("RRI_TEXTS_PATH", str(broken))
    assert cli.main(["run"], stop=_stopped()) == 2
    assert "reactions.stored" in caplog.text
    assert "ready" not in caplog.text


def test_run_refuses_disallowed_reaction_emoji(
    rri_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    texts = (REPO / "texts" / "messages.toml").read_text(encoding="utf-8")
    broken = tmp_path / "broken.toml"
    broken.write_text(texts.replace('duplicate = "🤝"', 'duplicate = "✅"'), encoding="utf-8")
    monkeypatch.setenv("RRI_TEXTS_PATH", str(broken))
    assert cli.main(["run"], stop=_stopped()) == 2
    assert "reactions.duplicate" in caplog.text


def test_migrate_needs_owner_credentials(
    rri_env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    assert cli.main(["migrate"]) == 2
    assert "RRI_MIGRATE_DB_USER" in caplog.text


def test_migrate_refuses_empty_owner_password(
    rri_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RRI_MIGRATE_DB_USER", "owner")
    monkeypatch.setenv("RRI_MIGRATE_DB_PASSWORD", "")
    assert cli.main(["migrate"]) == 2
    assert "RRI_MIGRATE_DB_PASSWORD" in caplog.text


def test_migrate_failure_redacts_password(
    rri_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RRI_MIGRATE_DB_USER", "owner")
    monkeypatch.setenv("RRI_MIGRATE_DB_PASSWORD", DB_PASSWORD)

    def refuse(conninfo: str, **kwargs: object) -> None:
        raise psycopg.OperationalError(f"connection failed for {conninfo}")

    monkeypatch.setattr(psycopg, "connect", refuse)
    assert cli.main(["migrate"]) == 1
    assert "postgresql://owner@db.example:5432/grocery-tracker-dev" in caplog.text
    _assert_no_secrets(caplog.text)
