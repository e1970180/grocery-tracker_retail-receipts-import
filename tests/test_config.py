import pytest
from pydantic import ValidationError

from retail_receipts_import.config import Settings
from tests.conftest import DB_PASSWORD, GEMINI_KEY, TOKEN


def test_valid_dev_config(rri_env: dict[str, str]) -> None:
    settings = Settings()  # type: ignore[call-arg]
    assert settings.env == "dev"
    assert settings.db_port == 5432


def test_prod_with_dev_database_is_refused(
    rri_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RRI_ENV", "prod")
    with pytest.raises(ValidationError, match="environment mismatch") as info:
        Settings()  # type: ignore[call-arg]
    assert "grocery-tracker-dev" in str(info.value)


def test_dev_with_non_dev_database_is_refused(
    rri_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RRI_DB_NAME", "grocery-tracker")
    with pytest.raises(ValidationError, match="environment mismatch"):
        Settings()  # type: ignore[call-arg]


def test_secrets_never_appear_in_repr_or_dsn(rri_env: dict[str, str]) -> None:
    settings = Settings()  # type: ignore[call-arg]
    shown = repr(settings) + str(settings) + settings.redacted_dsn(settings.db_user)
    for secret in (TOKEN, GEMINI_KEY, DB_PASSWORD):
        assert secret not in shown
    assert (
        settings.redacted_dsn("writer") == "postgresql://writer@db.example:5432/grocery-tracker-dev"
    )


def test_conninfo_carries_password_and_timeout(rri_env: dict[str, str]) -> None:
    settings = Settings()  # type: ignore[call-arg]
    conninfo = settings.conninfo("owner", settings.db_password)
    assert "user=owner" in conninfo
    assert DB_PASSWORD in conninfo
    assert "connect_timeout=10" in conninfo


def test_statement_timeout_reaches_conninfo(
    rri_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RRI_DB_STATEMENT_TIMEOUT_MS", "45000")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.db_statement_timeout_ms == 45000
    assert "statement_timeout=45000" in settings.conninfo("owner", settings.db_password)


def test_gemini_defaults(rri_env: dict[str, str]) -> None:
    settings = Settings()  # type: ignore[call-arg]
    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.gemini_timeout_s == 120
    assert settings.gemini_thinking_level == "low"


def test_gemini_timeout_must_be_positive(
    rri_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RRI_GEMINI_TIMEOUT_S", "0")
    with pytest.raises(ValidationError, match="gemini_timeout_s"):
        Settings()  # type: ignore[call-arg]


def test_statement_timeout_defaults_to_30_seconds(rri_env: dict[str, str]) -> None:
    settings = Settings()  # type: ignore[call-arg]
    assert "statement_timeout=30000" in settings.conninfo("owner", settings.db_password)
