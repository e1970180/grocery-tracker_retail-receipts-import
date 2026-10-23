"""Recorded and hand-built Gemini errors, through the real adapter, into their classes.

Each error is rebuilt as the SDK builds it from an HTTP response, so the SDK's own JSON and
non-JSON handling runs. The request carries the key in its header, as the real one does.
"""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from google import genai
from google.genai import errors, types
from pydantic import SecretStr

from retail_receipts_import.adapters.gemini.client import GeminiClient
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from retail_receipts_import.domain.extraction import (
    Classification,
    ExtractionClass,
    GeminiCallError,
    classify,
)
from tests.conftest import GEMINI_KEY

FIXTURES = Path(__file__).parent / "fixtures" / "gemini"
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
INITIAL_S, CAP_S = 600, 1800

UNAVAILABLE = ExtractionClass.UNAVAILABLE
BLOCKED = ExtractionClass.BLOCKED
INVALID = ExtractionClass.INVALID


def http_error(status: int, body: str, headers: dict[str, str] | None = None) -> errors.APIError:
    request = httpx.Request("POST", URL, headers={"x-goog-api-key": GEMINI_KEY})
    response = httpx.Response(status, headers=headers, content=body.encode(), request=request)
    try:
        errors.APIError.raise_for_response(response)
    except errors.APIError as exc:
        return exc
    raise AssertionError("the SDK raised no error")


def json_body(code: int, status: str, message: str = "error", **extra: Any) -> str:
    return json.dumps({"error": {"code": code, "message": message, "status": status, **extra}})


def recorded(name: str) -> Exception:
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    if "transport" in fixture:
        transport_error: type[Exception] = getattr(httpx, fixture["transport"])
        return transport_error(fixture["message"])
    return http_error(fixture["status"], fixture["body"], fixture["headers"])


def adapter_error(sdk_error: Exception, monkeypatch: pytest.MonkeyPatch) -> GeminiCallError:
    sdk = genai.Client(api_key=GEMINI_KEY)

    def fake(**_: Any) -> types.GenerateContentResponse:
        raise sdk_error

    monkeypatch.setattr(sdk.models, "generate_content", fake)
    client = GeminiClient(
        sdk, SecretStr(GEMINI_KEY), model="gemini-test", timeout_s=120, thinking_level="minimal"
    )
    with pytest.raises(GeminiCallError) as info:
        client.generate(b"%PDF", "application/pdf", "read it", SparPass2)
    return info.value


def classified(sdk_error: Exception, monkeypatch: pytest.MonkeyPatch) -> Classification:
    return classify(adapter_error(sdk_error, monkeypatch), 0, INITIAL_S, CAP_S)


def seconds(value: int) -> timedelta:
    return timedelta(seconds=value)


@pytest.mark.parametrize(
    ("name", "kind", "delay"),
    [
        ("quota_retry_info", UNAVAILABLE, seconds(37)),
        # Blocked ignores the server's 37 s: only the admin can lift a zero quota.
        ("quota_zero", BLOCKED, seconds(INITIAL_S)),
        ("transport_error", UNAVAILABLE, seconds(INITIAL_S)),
        ("api_key_invalid", BLOCKED, seconds(INITIAL_S)),
        ("permission_denied", BLOCKED, seconds(INITIAL_S)),
        ("retired_model", BLOCKED, seconds(INITIAL_S)),
    ],
)
def test_recorded_error_gets_its_class_and_delay(
    name: str, kind: ExtractionClass, delay: timedelta, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert classified(recorded(name), monkeypatch) == Classification(kind, delay)


@pytest.mark.parametrize(
    ("sdk_error", "kind", "delay"),
    [
        (
            http_error(503, json_body(503, "UNAVAILABLE"), {"Retry-After": "120"}),
            UNAVAILABLE,
            seconds(120),
        ),
        (http_error(500, json_body(500, "INTERNAL")), UNAVAILABLE, seconds(INITIAL_S)),
        # A proxy's HTML page: the SDK keeps only the reason phrase, so the code decides.
        (http_error(502, "<html>Bad Gateway</html>"), UNAVAILABLE, seconds(INITIAL_S)),
        (http_error(403, "<html>Forbidden</html>"), BLOCKED, seconds(INITIAL_S)),
        (httpx.ReadTimeout("The read operation timed out"), UNAVAILABLE, seconds(INITIAL_S)),
        (httpx.ConnectTimeout("timed out"), UNAVAILABLE, seconds(INITIAL_S)),
        (http_error(401, json_body(401, "UNAUTHENTICATED")), BLOCKED, seconds(INITIAL_S)),
        (
            http_error(400, json_body(400, "FAILED_PRECONDITION", "Billing is not enabled")),
            BLOCKED,
            seconds(INITIAL_S),
        ),
        (
            http_error(400, json_body(400, "INVALID_ARGUMENT", "Unable to process input image")),
            INVALID,
            timedelta(0),
        ),
        (http_error(408, "<html>Request Timeout</html>"), UNAVAILABLE, seconds(INITIAL_S)),
        (http_error(409, json_body(409, "ABORTED")), UNAVAILABLE, seconds(INITIAL_S)),
        (http_error(499, json_body(499, "CANCELLED")), UNAVAILABLE, seconds(INITIAL_S)),
        (http_error(413, json_body(413, "INVALID_ARGUMENT")), INVALID, timedelta(0)),
    ],
    ids=[
        "503-retry-after",
        "500",
        "502-not-json",
        "403-not-json",
        "read-timeout",
        "connect-timeout",
        "401",
        "400-failed-precondition",
        "400-unknown-reason",
        "408",
        "409-aborted",
        "499-cancelled",
        "413",
    ],
)
def test_built_error_gets_its_class_and_delay(
    sdk_error: Exception,
    kind: ExtractionClass,
    delay: timedelta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert classified(sdk_error, monkeypatch) == Classification(kind, delay)


def retry_body(retry_delay: str) -> str:
    detail = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}
    return json_body(429, "RESOURCE_EXHAUSTED", details=[detail])


@pytest.mark.parametrize(
    ("retry_delay", "retry_after", "delay"),
    [
        ("37s", "120", seconds(37)),
        ("1.2s", None, seconds(2)),
        ("0.001s", None, seconds(1)),
        ("0s", None, seconds(1)),
        ("soon", "120", seconds(120)),
        ("soon", "Wed, 21 Oct 2026 07:28:00 GMT", seconds(INITIAL_S)),
        ("soon", "1.5", seconds(INITIAL_S)),
        # Numbers too long to convert safely fall through instead of raising.
        ("9" * 400 + "s", "9" * 5000, seconds(INITIAL_S)),
        ("9" * 10 + "s", "999999999", seconds(999_999_999)),
    ],
)
def test_delay_sources_in_order(
    retry_delay: str,
    retry_after: str | None,
    delay: timedelta,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    found = classified(http_error(429, retry_body(retry_delay), headers), monkeypatch)
    assert found == Classification(UNAVAILABLE, delay)


@pytest.mark.parametrize(("waits", "delay_s"), [(0, 600), (1, 1200), (2, 1800), (10, 1800)])
def test_backoff_doubles_up_to_the_cap(waits: int, delay_s: int) -> None:
    found = classify(GeminiCallError(transport=True), waits, INITIAL_S, CAP_S)
    assert found == Classification(UNAVAILABLE, seconds(delay_s))


def test_blocked_waits_the_backoff_whatever_the_server_says() -> None:
    error = GeminiCallError(code=403, status="PERMISSION_DENIED", retry_delay_s=5, retry_after_s=7)
    assert classify(error, 1, INITIAL_S, CAP_S) == Classification(BLOCKED, seconds(1200))


def test_zero_quota_is_read_from_the_message_only() -> None:
    def kind(message: str) -> ExtractionClass:
        return classify(GeminiCallError(code=429, detail=message), 0, INITIAL_S, CAP_S).kind

    assert kind("Quota exceeded for metric: x, limit: 0, model: m") is BLOCKED
    assert kind("Quota exceeded for metric: x, limit: 10, model: m") is UNAVAILABLE
    assert kind("Quota exceeded for metric: x, limit: 0.5, model: m") is UNAVAILABLE


def test_the_key_is_nowhere_on_the_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json_body(400, "INVALID_ARGUMENT", f"key {GEMINI_KEY} rejected")
    error = adapter_error(http_error(400, body), monkeypatch)
    assert error.detail == "key ********** rejected"
    for text in (str(error), repr(error), *map(str, error.args), *map(repr, vars(error).values())):
        assert GEMINI_KEY not in text
    assert error.__context__ is None
    assert error.__cause__ is None


def test_transport_error_keeps_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    error = adapter_error(httpx.ConnectError(f"refused for {GEMINI_KEY}"), monkeypatch)
    assert error.transport
    assert GEMINI_KEY not in repr(vars(error))
    assert error.__context__ is None
