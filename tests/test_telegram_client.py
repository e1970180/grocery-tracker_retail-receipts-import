"""Tests for TelegramClient transport, retry policy, and token redaction."""

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from retail_receipts_import.adapters.telegram.client import (
    TelegramAPIError,
    TelegramClient,
    TelegramRetryExhaustedError,
    _redact,
)

TOKEN = "123456789:AAFakeTokenForTelegramClientTests_x"
SECRET = SecretStr(TOKEN)

_UPDATES_RESULT: list[dict[str, Any]] = [
    {
        "update_id": 100,
        "message": {
            "message_id": 1,
            "date": 1727092800,
            "chat": {"id": 111, "type": "private"},
            "text": "hi",
        },
    }
]
_FILE_RESULT: dict[str, Any] = {
    "file_id": "AgADfile",
    "file_unique_id": "AAfile",
    "file_size": 4096,
    "file_path": "photos/file_1.jpg",
}


class SleepRecorder:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def test_redact_masks_token() -> None:
    assert _redact(f"Error at https://api.telegram.org/bot{TOKEN}/getUpdates", TOKEN) == (
        "Error at https://api.telegram.org/bot<redacted>/getUpdates"
    )


def test_get_updates_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/getUpdates" in str(request.url)
        return httpx.Response(200, json={"ok": True, "result": _UPDATES_RESULT})

    transport = httpx.MockTransport(handler)
    with TelegramClient(SECRET, transport=transport) as client:
        res = client.get_updates(offset=42, timeout=5)
        assert res == _UPDATES_RESULT


def test_429_uses_retry_after() -> None:
    sleep = SleepRecorder()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "description": "Too Many Requests: retry after 7",
                    "parameters": {"retry_after": 7},
                },
            )
        return httpx.Response(200, json={"ok": True, "result": _UPDATES_RESULT})

    transport = httpx.MockTransport(handler)
    with TelegramClient(SECRET, transport=transport, sleep=sleep) as client:
        res = client.get_updates(offset=None, timeout=10)
        assert res == _UPDATES_RESULT
        assert sleep.waits == [7.0, 7.0]
        assert attempts == 3


def test_5xx_uses_exponential_backoff() -> None:
    sleep = SleepRecorder()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json={"ok": True, "result": _FILE_RESULT})

    transport = httpx.MockTransport(handler)
    with TelegramClient(SECRET, transport=transport, sleep=sleep) as client:
        res = client.get_file("AgADfile")
        assert res == _FILE_RESULT
        assert sleep.waits == [1.0, 2.0]


def test_malformed_200_retried_on_backoff_path() -> None:
    """HTTP 200 without JSON or missing 'result' is retried with backoff."""
    sleep = SleepRecorder()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(200, text="<html>Cloudflare error</html>")
        if attempts == 2:
            return httpx.Response(200, json={"ok": False})  # missing "result"
        return httpx.Response(200, json={"ok": True, "result": _FILE_RESULT})

    transport = httpx.MockTransport(handler)
    with TelegramClient(SECRET, transport=transport, sleep=sleep) as client:
        res = client.get_file("AgADfile")
        assert res == _FILE_RESULT
        assert attempts == 3
        assert sleep.waits == [1.0, 2.0]


def test_4xx_fails_immediately_without_retry() -> None:
    sleep = SleepRecorder()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            400,
            json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"},
        )

    transport = httpx.MockTransport(handler)
    with TelegramClient(SECRET, transport=transport, sleep=sleep) as client:
        with pytest.raises(TelegramAPIError) as exc_info:
            client.get_file("AgADfile")
        assert exc_info.value.status_code == 400
        assert attempts == 1
        assert len(sleep.waits) == 0


def test_network_exhaustion_raises_and_redacts(caplog: pytest.LogCaptureFixture) -> None:
    sleep = SleepRecorder()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"connection refused to https://api.telegram.org/bot{TOKEN}/getFile"
        )

    transport = httpx.MockTransport(handler)
    with TelegramClient(SECRET, transport=transport, sleep=sleep) as client:
        with pytest.raises(TelegramRetryExhaustedError) as exc_info:
            client.get_file("AgADfile")
        assert exc_info.value.attempts == 5
        assert len(sleep.waits) == 4
    # The loop logs this exception with its traceback, so neither may carry the token.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__
    assert TOKEN not in str(exc_info.value)
    assert "connection refused" in caplog.text
    assert TOKEN not in caplog.text


def test_set_message_reaction_sends_correct_payload() -> None:
    called_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        nonlocal called_payload
        assert "/setMessageReaction" in str(request.url)
        called_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = httpx.MockTransport(handler)
    with TelegramClient(SECRET, transport=transport) as client:
        client.set_message_reaction(chat_id=111, message_id=42, reaction="👍")

    assert called_payload == {
        "chat_id": 111,
        "message_id": 42,
        "reaction": [{"type": "emoji", "emoji": "👍"}],
    }
