"""Telegram Bot API transport with retry, backoff, and token redaction.

Vendored from the telegram_core reference pack and owned here; it is the only Telegram client.

Wraps synchronous httpx.Client and exposes getUpdates, getFile, downloadFile,
setMessageReaction, sendMessage and sendDocument through a shared retry helper.

Key guarantees:
1. Never calls httpx.Response.raise_for_status() because it embeds the full URL
   (including the secret bot token) in exceptions and tracebacks.
2. Every error path redacts the token before logging or raising.
3. Distinguishes retryable errors (429, 5xx, network, and malformed 200) from non-retryable 4xx.
4. HTTP 200 without a valid JSON result is retried with backoff instead of crashing.
5. getUpdates read_timeout is timeout + 10s to prevent premature socket close.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, cast

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_MAX_ATTEMPTS = 5
_BACKOFF_BASE_SECONDS = 1.0
_DEFAULT_RETRY_AFTER_SECONDS = 1.0

# Connect/write/pool share a fixed budget; read timeout varies per call.
_CONNECT_TIMEOUT_SECONDS = 10.0
# getFile and setMessageReaction: small JSON responses.
_DEFAULT_TIMEOUT_SECONDS = 30.0
# download_file: payloads up to 20MB limit need more read budget.
_DOWNLOAD_TIMEOUT_SECONDS = 60.0
_REDACTED = "<redacted>"
# The Bot API rejects a longer document caption.
_MAX_CAPTION_CHARS = 1024


class TelegramAPIError(Exception):
    """A non-retryable 4xx response: raised on the first attempt, never retried."""

    def __init__(self, method: str, status_code: int, description: str) -> None:
        super().__init__(f"{method}: HTTP {status_code}: {description}")
        self.method = method
        self.status_code = status_code
        self.description = description


class TelegramRetryExhaustedError(Exception):
    """A 429/5xx/network/malformed-200 error persisted through every attempt."""

    def __init__(self, method: str, attempts: int) -> None:
        super().__init__(f"{method}: gave up after {attempts} attempt(s)")
        self.method = method
        self.attempts = attempts


def _redact(text: str, token: str) -> str:
    """Replace every occurrence of the bot token with a placeholder."""
    if not token:
        return text
    return text.replace(token, _REDACTED)


def _extract_description(response: httpx.Response) -> str:
    """The Bot API `description` field, or the raw body when it is not JSON."""
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict):
        description = body.get("description")
        if isinstance(description, str):
            return description
    return response.text


def _parse_retry_after(response: httpx.Response) -> float:
    """The `429` body's `parameters.retry_after`, falling back to 1.0s."""
    try:
        body = response.json()
    except ValueError:
        return _DEFAULT_RETRY_AFTER_SECONDS
    if isinstance(body, dict):
        parameters = body.get("parameters")
        if isinstance(parameters, dict):
            retry_after = parameters.get("retry_after")
            if isinstance(retry_after, int | float):
                return max(0.0, float(retry_after))
    return _DEFAULT_RETRY_AFTER_SECONDS


class TelegramClient:
    """Synchronous Telegram Bot API transport: retry, backoff, and redaction."""

    def __init__(
        self,
        bot_token: SecretStr,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = bot_token.get_secret_value()
        self._sleep = sleep
        self._client = httpx.Client(transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TelegramClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def get_updates(
        self,
        *,
        offset: int | None,
        timeout: int,
        allowed_updates: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Poll updates from Telegram.

        Note: read_timeout is set to float(timeout + 10) so the HTTP client
        never aborts the connection while Telegram's long-poll is waiting.
        """
        body: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            body["offset"] = offset
        if allowed_updates is not None:
            body["allowed_updates"] = list(allowed_updates)
        result = self._call("getUpdates", body=body, read_timeout=float(timeout + 10))
        return cast(list[dict[str, Any]], result)

    def get_file(self, file_id: str) -> dict[str, Any]:
        """Fetch file metadata from Telegram (returns file_id, file_size, file_path)."""
        result = self._call(
            "getFile",
            body={"file_id": file_id},
            read_timeout=_DEFAULT_TIMEOUT_SECONDS,
        )
        return cast(dict[str, Any], result)

    def download_file(self, file_path: str) -> bytes:
        """Download raw file bytes from https://api.telegram.org/file/bot<token>/<file_path>."""
        url = f"{_API_BASE}/file/bot{self._token}/{file_path}"
        result = self._call(
            "downloadFile",
            url=url,
            read_timeout=_DOWNLOAD_TIMEOUT_SECONDS,
            raw=True,
        )
        return cast(bytes, result)

    def set_message_reaction(self, chat_id: int, message_id: int, reaction: str | None) -> None:
        """Send an emoji reaction to a message; None clears the bot's reaction."""
        body = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [] if reaction is None else [{"type": "emoji", "emoji": reaction}],
        }
        self._call(
            "setMessageReaction",
            body=body,
            read_timeout=_DEFAULT_TIMEOUT_SECONDS,
        )

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None) -> None:
        """Send plain text; no parse_mode, so untrusted text is never read as markup."""
        body: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to is not None:
            # The sender may have deleted the receipt message meanwhile; the text still matters.
            body["reply_parameters"] = {
                "message_id": reply_to,
                "allow_sending_without_reply": True,
            }
        self._call("sendMessage", body=body, read_timeout=_DEFAULT_TIMEOUT_SECONDS)

    def send_document(self, chat_id: int, path: Path, caption: str) -> None:
        """Upload a local file with a plain-text caption."""
        # Read once, so every retry sends the same bytes.
        files = {"document": (path.name, path.read_bytes())}
        data = {"chat_id": str(chat_id), "caption": caption[:_MAX_CAPTION_CHARS]}
        self._call(
            "sendDocument",
            data=data,
            files=files,
            read_timeout=_DOWNLOAD_TIMEOUT_SECONDS,
        )

    def _call(
        self,
        method: str,
        *,
        read_timeout: float,
        body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes]] | None = None,
        url: str | None = None,
        raw: bool = False,
    ) -> Any:
        """Shared retry helper: sleeps and retries on 429/5xx/network error/malformed 200.

        Raises TelegramAPIError on any other 4xx (first attempt, no retry) and
        TelegramRetryExhaustedError once _MAX_ATTEMPTS is exhausted. Returns the
        raw `result` value (or raw bytes when raw=True) on a 200.
        """
        request_url = url if url is not None else f"{_API_BASE}/bot{self._token}/{method}"
        timeout = httpx.Timeout(
            connect=_CONNECT_TIMEOUT_SECONDS,
            read=read_timeout,
            write=_CONNECT_TIMEOUT_SECONDS,
            pool=_CONNECT_TIMEOUT_SECONDS,
        )
        backoff_attempt = 0

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                if files is not None:
                    response = self._client.post(
                        request_url, data=data, files=files, timeout=timeout
                    )
                elif body is not None:
                    response = self._client.post(request_url, json=body, timeout=timeout)
                else:
                    response = self._client.get(request_url, timeout=timeout)
            except (httpx.RequestError, httpx.InvalidURL) as exc:
                backoff_attempt += 1
                safe_error = _redact(str(exc), self._token)
                if attempt == _MAX_ATTEMPTS:
                    logger.error(
                        "%s: giving up after %d attempt(s): network error: %s",
                        method,
                        attempt,
                        safe_error,
                    )
                    raise TelegramRetryExhaustedError(method, attempt) from None
                wait = _BACKOFF_BASE_SECONDS * 2 ** (backoff_attempt - 1)
                logger.warning(
                    "%s: network error (%s), retrying in %.1fs (attempt %d/%d)",
                    method,
                    safe_error,
                    wait,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                self._sleep(wait)
                continue

            if response.status_code == 429:
                if attempt == _MAX_ATTEMPTS:
                    logger.error(
                        "%s: giving up after %d attempt(s): HTTP 429",
                        method,
                        attempt,
                    )
                    raise TelegramRetryExhaustedError(method, attempt)
                wait = _parse_retry_after(response)
                logger.warning(
                    "%s: rate limited, retrying in %.1fs (attempt %d/%d)",
                    method,
                    wait,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                self._sleep(wait)
                continue

            if response.status_code == 200:
                if raw:
                    return response.content
                try:
                    body_json = response.json()
                except ValueError:
                    body_json = None
                if isinstance(body_json, dict) and "result" in body_json:
                    return body_json["result"]
                failure = "HTTP 200 without a JSON result"
            elif 500 <= response.status_code < 600:
                failure = f"HTTP {response.status_code}"
            else:
                failure = None

            if failure is not None:
                backoff_attempt += 1
                if attempt == _MAX_ATTEMPTS:
                    logger.error(
                        "%s: giving up after %d attempt(s): %s",
                        method,
                        attempt,
                        failure,
                    )
                    raise TelegramRetryExhaustedError(method, attempt)
                wait = _BACKOFF_BASE_SECONDS * 2 ** (backoff_attempt - 1)
                logger.warning(
                    "%s: %s, retrying in %.1fs (attempt %d/%d)",
                    method,
                    failure,
                    wait,
                    attempt,
                    _MAX_ATTEMPTS,
                )
                self._sleep(wait)
                continue

            description = _redact(_extract_description(response), self._token)
            logger.error("%s: HTTP %d: %s", method, response.status_code, description)
            raise TelegramAPIError(method, response.status_code, description)

        raise AssertionError("unreachable: the loop always returns or raises")
