from typing import Any

import pytest
from google import genai
from google.genai import types
from pydantic import SecretStr

from retail_receipts_import.adapters.gemini.client import GeminiClient, GeminiError
from retail_receipts_import.config import Settings
from retail_receipts_import.domain.chains.spar.schema import SparPass2
from tests.conftest import GEMINI_KEY


def answer(text: str | None) -> types.GenerateContentResponse:
    parts = [] if text is None else [types.Part(text=text)]
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=parts))],
        model_version="gemini-test-001",
    )


@pytest.fixture
def sdk() -> genai.Client:
    # Building the client makes no request; every call below goes to a patched method.
    return genai.Client(api_key=GEMINI_KEY)


def client(sdk: genai.Client) -> GeminiClient:
    return GeminiClient(
        sdk, SecretStr(GEMINI_KEY), model="gemini-test", timeout_s=120, thinking_level="minimal"
    )


def test_one_stateless_call_with_schema_timeout_and_lowest_thinking(
    sdk: genai.Client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> types.GenerateContentResponse:
        seen.update(kwargs)
        return answer('{"ok": true}')

    monkeypatch.setattr(sdk.models, "generate_content", fake)
    caplog.set_level("INFO")
    text = client(sdk).generate(b"%PDF", "application/pdf", "read it", SparPass2)

    assert text == '{"ok": true}'
    assert seen["model"] == "gemini-test"
    contents: types.Content = seen["contents"]
    assert contents.parts is not None
    part, prompt = contents.parts
    assert part.inline_data is not None
    assert (part.inline_data.data, part.inline_data.mime_type) == (b"%PDF", "application/pdf")
    assert prompt.text == "read it"
    config: types.GenerateContentConfig = seen["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SparPass2.model_json_schema()
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level is types.ThinkingLevel.MINIMAL
    assert config.thinking_config.thinking_budget is None
    assert config.http_options is not None
    assert config.http_options.timeout == 120_000
    assert config.http_options.retry_options is None
    assert config.temperature is None
    assert "model_version=gemini-test-001" in caplog.text


def test_empty_answer_is_empty_text(sdk: genai.Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sdk.models, "generate_content", lambda **_: answer(None))
    assert client(sdk).generate(b"%PDF", "application/pdf", "read it", SparPass2) == ""


def test_error_carrying_the_key_is_redacted(
    sdk: genai.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(**_: Any) -> types.GenerateContentResponse:
        raise RuntimeError(f"rejected key={GEMINI_KEY}")

    monkeypatch.setattr(sdk.models, "generate_content", fake)
    with pytest.raises(GeminiError) as info:
        client(sdk).generate(b"%PDF", "application/pdf", "read it", SparPass2)
    assert GEMINI_KEY not in str(info.value)
    assert "rejected" in str(info.value)
    # The original exception carries the key, so it must not stay reachable from the new one.
    assert info.value.__context__ is None
    assert info.value.__cause__ is None


def test_other_errors_propagate_unchanged(
    sdk: genai.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(**_: Any) -> types.GenerateContentResponse:
        raise TimeoutError("read timed out")

    monkeypatch.setattr(sdk.models, "generate_content", fake)
    with pytest.raises(TimeoutError, match="read timed out"):
        client(sdk).generate(b"%PDF", "application/pdf", "read it", SparPass2)


def test_from_settings_uses_the_config(rri_env: dict[str, str]) -> None:
    built = GeminiClient.from_settings(Settings())  # type: ignore[call-arg]
    assert built._model == "gemini-3.8-flash"
    assert built._http_options.timeout == 120_000
    assert built._thinking.thinking_level is types.ThinkingLevel.LOW
