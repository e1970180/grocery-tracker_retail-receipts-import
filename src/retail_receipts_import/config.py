"""Service configuration from `RRI_*` environment variables, validated once at startup."""

from pathlib import Path
from typing import Annotated, Literal, Self

from psycopg.conninfo import make_conninfo
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEV_DATABASE_SUFFIX = "-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RRI_", env_file=".env", extra="ignore")

    env: Literal["dev", "prod"]
    telegram_bot_token: SecretStr
    gemini_api_key: SecretStr
    gemini_model: str = "gemini-3.8-flash"
    # The SDK sets no timeout of its own; a PDF read takes tens of seconds, so 120 s is ample.
    gemini_timeout_s: int = Field(default=120, gt=0)
    # The lowest level gemini-3.8-flash accepts: thinking costs money and the model only copies.
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] = "low"
    # Wait after an unavailable or misconfigured Gemini that names no delay of its own. The first
    # equals the generic job retry; each further wait in a row doubles, up to the cap.
    gemini_backoff_initial_s: int = Field(default=600, gt=0)
    gemini_backoff_cap_s: int = Field(default=1800, gt=0)
    # Larger images are scaled down before sending; above this, extra pixels add cost, not text.
    image_max_pixels: int = Field(default=16_000_000, gt=0)

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

    # Telegram user ids whose private messages are taken as receipts, e.g. "111,222".
    allowed_user_ids: Annotated[list[int], NoDecode] = Field(min_length=1)
    telegram_poll_timeout_s: int = Field(default=30, gt=0)
    # A job whose step raised, or whose download Telegram refused, waits this long before it
    # runs again; each run may be a paid call.
    job_retry_delay_s: int = Field(default=600, gt=0)
    # Refused downloads of one file, then results Gemini gets wrong for it across both passes,
    # before the job fails; the count starts again once the file is downloaded.
    job_max_attempts: int = Field(default=3, gt=0)
    # The compose volume: the SQLite queue and the downloaded receipt files.
    data_dir: Path = Path("/data")

    texts_path: Path = Path("texts/messages.toml")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # pydantic-settings would read a list as JSON; the environment holds plain comma lists.
    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _split_user_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

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
