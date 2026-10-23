"""One stateless Gemini call per file: the file, a prompt, and the JSON schema to answer in."""

import logging

from google import genai
from google.genai import types
from pydantic import BaseModel, SecretStr

from retail_receipts_import.config import Settings

log = logging.getLogger(__name__)


class GeminiError(Exception):
    """An SDK error whose message carried the API key, re-raised with the key removed."""


class GeminiClient:
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
        redacted: str | None = None
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            key = self._api_key.get_secret_value()
            if not key or key not in str(exc):
                raise
            redacted = f"{type(exc).__name__}: {str(exc).replace(key, '**********')}"
        # Raised outside the except block: inside it, even `from None` keeps the original,
        # key-carrying exception reachable as __context__.
        if redacted is not None:
            raise GeminiError(redacted)
        log.info("gemini answered: model_version=%s", response.model_version)
        return response.text or ""
