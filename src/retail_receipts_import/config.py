"""Service configuration from `RRI_*` environment variables, validated once at startup."""

from pathlib import Path
from typing import Literal, Self

from psycopg.conninfo import make_conninfo
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DATABASE_SUFFIX = "-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RRI_", env_file=".env", extra="ignore")

    env: Literal["dev", "prod"]
    telegram_bot_token: SecretStr
    gemini_api_key: SecretStr

    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_password: SecretStr
    db_connect_timeout_s: int = 10
    # Bounds a runaway statement; the writer's transaction is short, so 30 s is far above it.
    db_statement_timeout_ms: int = Field(default=30000, gt=0)
    # Schema owner credentials; only the migrate command needs them.
    migrate_db_user: str | None = None
    migrate_db_password: SecretStr | None = None

    texts_path: Path = Path("texts/messages.toml")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # One bot serves both environments, so the database name is the only thing that tells
    # a dev run from production. A mismatch would write test receipts to the real data.
    @model_validator(mode="after")
    def _environment_matches_database(self) -> Self:
        is_dev_db = self.db_name.endswith(DEV_DATABASE_SUFFIX)
        if (self.env == "dev") != is_dev_db:
            expected = "ends" if self.env == "dev" else "does not end"
            raise ValueError(
                f"environment mismatch: RRI_ENV={self.env} needs a database name that "
                f"{expected} with {DEV_DATABASE_SUFFIX!r}, got {self.db_name!r}"
            )
        return self

    def conninfo(self, user: str, password: SecretStr) -> str:
        return make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=user,
            password=password.get_secret_value(),
            connect_timeout=self.db_connect_timeout_s,
            options=f"-c statement_timeout={self.db_statement_timeout_ms}",
            application_name="retail-receipts-import",
        )

    def redacted_dsn(self, user: str) -> str:
        return f"postgresql://{user}@{self.db_host}:{self.db_port}/{self.db_name}"
