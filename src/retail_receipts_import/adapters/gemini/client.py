"""One stateless Gemini call per file: the file, a prompt, and the JSON schema to answer in."""

import logging
import math
import re

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, SecretStr

from retail_receipts_import.config import Settings
from retail_receipts_import.domain.extraction import GeminiCallError

log = logging.getLogger(__name__)


class GeminiError(Exception):
    """An SDK error whose message carried the API key, re-raised with the key removed."""


class GeminiClient:
    """Wraps Google GenAI client to generate structured JSON extractions with sanitized errors."""

    def __init__(
        self,
        client: genai.Client,
        api_key: SecretStr,
        model: str,
        timeout_s: int,
        thinking_level: str,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model
        # Per request, so the timeout cannot be lost to a client built elsewhere.
        self._http_options = types.HttpOptions(timeout=timeout_s * 1000)
        self._thinking = types.ThinkingConfig(
            thinking_level=types.ThinkingLevel(thinking_level.upper())
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> GeminiClient:
        """Instantiates a configured GeminiClient using application settings."""
        return cls(
            genai.Client(api_key=settings.gemini_api_key.get_secret_value()),
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_s=settings.gemini_timeout_s,
            thinking_level=settings.gemini_thinking_level,
        )

    def generate(self, data: bytes, mime: str, prompt: str, schema: type[BaseModel]) -> str:
        """The response text, or "" for an empty or blocked answer, which then fails the schema.

        Temperature, `thinking_budget` and the SDK's `retry_options` are left unset on purpose:
        the model default temperature is the recommended one, and retries belong to the caller.
        """
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            thinking_config=self._thinking,
            http_options=self._http_options,
        )
        contents = types.Content(
            role="user",
            parts=[types.Part.from_bytes(data=data, mime_type=mime), types.Part(text=prompt)],
        )
        key = self._api_key.get_secret_value()
        failure: GeminiCallError | None = None
        redacted: str | None = None
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except errors.APIError as exc:
            failure = _api_failure(exc, key)
        except httpx.TransportError as exc:
            detail = _redact(f"{type(exc).__name__}: {exc}", key)
            failure = GeminiCallError(transport=True, detail=detail)
        except Exception as exc:
            if not key or key not in str(exc):
                raise
            redacted = f"{type(exc).__name__}: {_redact(str(exc), key)}"
        # Raised outside the except block: inside it, even `from None` keeps the original,
        # key-carrying exception reachable as __context__.
        if failure is not None:
            raise failure
        if redacted is not None:
            raise GeminiError(redacted)
        log.info("gemini answered: model_version=%s", response.model_version)
        return response.text or ""


def _api_failure(exc: errors.APIError, key: str) -> GeminiCallError:
    # Only values are copied out: `exc.response` leads to the request and its key header.
    body = exc.details
    error = body.get("error", body) if isinstance(body, dict) else {}
    details = error.get("details") if isinstance(error, dict) else None
    reason: str | None = None
    retry_delay: str | None = None
    for item in details if isinstance(details, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("@type", ""))
        if kind.endswith("google.rpc.ErrorInfo"):
            reason = _text(item.get("reason"))
        elif kind.endswith("google.rpc.RetryInfo"):
            retry_delay = _text(item.get("retryDelay"))
    retry_after = exc.response.headers.get("retry-after") if exc.response is not None else None
    status = _text(exc.status)
    return GeminiCallError(
        code=exc.code if isinstance(exc.code, int) else None,
        status=status and _redact(status, key),
        reason=reason and _redact(reason, key),
        retry_delay_s=_duration_s(retry_delay),
        retry_after_s=_seconds(retry_after),
        detail=_redact(_text(exc.message) or "", key),
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _redact(text: str, key: str) -> str:
    return text.replace(key, "**********") if key else text


# At most nine digits of seconds, about 30 years: a longer number cannot be converted safely
# and would raise inside the except block, next to the key-carrying SDK error.
_DURATION = re.compile(r"([0-9]{1,9}(?:\.[0-9]{1,9})?)s")


def _duration_s(value: str | None) -> int | None:
    """Whole seconds of a protobuf Duration such as "37s" or "0.5s", rounded up."""
    match = _DURATION.fullmatch(value) if value is not None else None
    return math.ceil(float(match.group(1))) if match else None


def _seconds(value: str | None) -> int | None:
    # Retry-After may also be an HTTP date; only the delay-seconds form is used.
    return int(value) if value is not None and re.fullmatch(r"[0-9]{1,9}", value) else None
