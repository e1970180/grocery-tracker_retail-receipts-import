---
review: verification (verified-current technology)
target: ../architecture-receipts-import.md
memlog: ../.memlog.md
date: 2026-10-21
verdict: needs-changes
---

# Verification review — architecture-receipts-import

## Verdict

Needs changes. Every package version in the Stack table matches PyPI today, and the base image exists. Two Gemini decisions are out of date or unfit: AD-4's temperature 0 goes against Google's current Gemini 3 guidance, and the model choice rests on a stale model check. The Gemini adapter rules also leave out three verified SDK behaviours that AD-7 and AD-14 depend on.

## Method

- PyPI JSON API (`https://pypi.org/pypi/<name>/json`), queried 2026-10-21, for latest version, `requires_python` and the 3.14 classifier. For psycopg-binary, also checked the cp314 Linux wheels.
- Docker Hub tags API for `library/python`, and the GHCR manifest for `astral-sh/uv:0.13.4`.
- Gemini docs on ai.google.dev: models, deprecations, thinking, gemini-3 developer guide, structured-output, document-processing, migrate-to-interactions.
- google-genai source at tag `v2.32.0`: `types.py`, `errors.py`, `_api_client.py`.
- Telegram Bot API page (core.telegram.org/bots/api), downloaded and searched.

## Stack verification

| Item | Spine | Checked 2026-10-21 | Status |
| --- | --- | --- | --- |
| Python | 3.14 | 3.14.8 is the current patch; `uuid.uuid7()` is stdlib in 3.14 (memlog) | OK |
| python:3.14-slim | base | Tag exists and was updated 2026-10-21; it resolves to trixie (also `-slim-bookworm`) | OK. Pin `3.14.8-slim-trixie` or a digest so builds are reproducible |
| uv | 0.13.4 | PyPI latest 0.13.4; `ghcr.io/astral-sh/uv:0.13.4` returns 200 | OK |
| httpx | 0.28.1 | Latest stable (released 2024-12-06; only 1.0.devN since). google-genai 2.32.0 requires `httpx<1.0.0,>=0.28.1` | OK; 1.0 is blocked by the SDK anyway |
| pydantic | 2.14.1 | latest, 3.14 classifier | OK |
| pydantic-settings | 2.16.1 | latest, 3.14 classifier | OK |
| psycopg / psycopg-binary | 3.3.6 | latest; cp314 manylinux x86_64/aarch64 wheels present | OK |
| google-genai | 2.32.0 | latest (uploaded 2026-10-21); deps include tenacity, requests, google-auth | OK; see G-1..G-4 |
| Pillow | 13.0.0 | latest, 3.14 classifier | OK |
| ruff / mypy / pytest | 0.17.1 / 2.4.0 / 9.1.1 | all latest | OK. `pyproject.toml` still has ruff 0.9.9, mypy 1.15.0, pytest 8.3.5 and ruff `target-version = "py313"`; the memlog already defers this to the platform-baseline story |
| SQLite | stdlib | n/a | OK |
| Gemini model | `gemini-3.6-flash` | Exists, stable, no shutdown date; marked "previous-generation". `gemini-3.8-flash` (2026-09-02) is the current stable Flash; 3.7 Flash (2026-08-13) already routes to 3.8 | Stale check, see G-2 |
| Telegram Bot API | getUpdates, setMessageReaction, sendDocument, sendMessage | Bot API 10.3 (2026-08-24). All four methods exist; see T-1 | OK |

## Findings

### G-1 — Temperature 0 contradicts current Gemini 3 guidance `[high]`

- **Where:** AD-4: "Every call uses a response schema and temperature 0."
- **Evidence:** ai.google.dev/gemini-api/docs/gemini-3: "For all Gemini 3 models, we strongly recommend keeping the temperature parameter at its default value of `1.0`." Going below 1.0 "may lead to unexpected behavior, such as looping or degraded performance." This applies to every Gemini 3.x model, including 3.6 and 3.8 Flash.
- **Risk:** Looping or truncated JSON would surface as `invalid` results. Each one burns one of the 3 attempts and costs a paid call. That pushes receipts to `failed` for reasons that have nothing to do with the receipt.
- **Fix:** In AD-4, drop "temperature 0". Leave temperature at the model default and make it a config value. Repeatability comes from the response schema plus deterministic domain code (AD-5), not from temperature. If someone later wants a lower temperature, run fixture evidence first.

### G-2 — The model choice rests on a stale check `[medium]`

- **Where:** Stack row and the memlog `(version)` entry: "gemini-3.6-flash is the stable Flash ... (Jul 2026); a 3.7 Flash is rumored."
- **Evidence:** The models page and the deprecations page (both read 2026-10-21) show:
  - 3.7 Flash shipped on 2026-08-13 and now auto-routes to 3.8.
  - `gemini-3.8-flash` shipped on 2026-09-02 and is the current stable Flash.
  - 3.6 Flash is labeled "previous-generation", with no shutdown date.
  - `gemini-3.5-flash` already auto-routes to 3.6. Google retires older Flash ids quickly and redirects them silently.
- **Risk:** The model check was asserted from a July snapshot rather than from current data. A silent redirect would change extraction behaviour without notice. This is the "live response diverges from fixture" pitfall.
- **Fix:**
  - Fix the memlog entry.
  - Keep the model id in config (already ruled).
  - Choosing between 3.6 and 3.8 affects cost and quality, so it goes to the owner as a decision card. One point bears on that choice: 3.8 Flash does not offer `minimal` thinking (see G-3).
  - Log the model version the response reports on every call, so a silent redirect is visible.

### G-3 — The spine does not settle thinking; it cannot be fully off on 3.x Flash `[medium]`

- **Where:** Nothing in the spine. The adapter and receipt-latency behaviour depend on it.
- **Evidence:**
  - Thinking docs: Gemini 3.x Flash models think by default (level medium). `gemini-3.6-flash` supports `minimal | low | medium | high`; `gemini-3.8-flash` supports `low | medium | high` only. The docs only mention `thinking_level` for Gemini 3.
  - The SDK still has `ThinkingConfig.thinking_budget` ("0 is DISABLED ... model dependent"), but that is the 2.5-era knob.
  - Thought tokens count toward `max_output_tokens` and are billed.
- **Fix:** Add to AD-4: "thinking is set with `thinking_level` from config. Use the lowest level the chosen model supports that passes the fixtures. Never use `thinking_budget=0`." Whether `thinking_budget=0` is rejected or ignored on 3.x was not tested. Treat it as unsupported.

### G-4 — The Gemini SDK's default error and timeout behaviour does not match AD-7 and AD-14 `[high]`

Verified in the google-genai v2.32.0 source:

1. **No timeout by default.** With `HttpOptions.timeout` unset, the request goes out with `timeout=None`. The unit is milliseconds. In one synchronous loop (AD-14), a hung Gemini call stalls Telegram polling and every other job indefinitely. This is the same trap as the known `httpx` timeout pitfall, inverted.
2. **Network errors and timeouts are not `APIError`.** `_request_once` sends through httpx with no wrapping, so `httpx.TimeoutException` and `httpx.TransportError` reach the caller raw. Only HTTP error responses become `errors.ClientError` (4xx) or `errors.ServerError` (5xx). Both carry `.code`, `.status`, `.message`, `.details` and the raw `.response`.
3. **No Retry-After parsing, and no retries by default.** With `retry_options` unset, the SDK makes exactly one attempt, which is what AD-7 wants. Nothing in the SDK reads `Retry-After` or `RetryInfo`. Gemini 429s usually carry the hint as a `google.rpc.RetryInfo` entry with `retryDelay` (for example "27s") inside the error details, and sometimes only in the message text. They rarely send an HTTP `Retry-After` header.

- **Fix (AD-7 and the Errors convention):**
  - Always set `HttpOptions(timeout=<ms from config>)`.
  - Never set `retry_options`. The job state machine owns retries; SDK retries would double them.
  - Classify `httpx.TimeoutException` and `httpx.TransportError` as `unavailable`. Classify `ServerError` and `ClientError` with code 429 as `unavailable`.
  - Read the delay from the `RetryInfo.retryDelay` entry in `.details`, then from the `Retry-After` header on `.response`, else use capped backoff. Change the AD-7 wording from "`retry-after`" to "the server's retry delay (RetryInfo or Retry-After)".
  - Record a 429 and a timeout as fixtures.

### G-5 — AD-7 leaves non-429 4xx errors unclassified `[medium]`

- **Where:** AD-7 lists 429, 5xx, network and timeout errors as `unavailable`, and only response or validation failures as `invalid`.
- **Problem:** 400 (for example an oversized schema; structured-output docs warn that big or deeply nested schemas fail with `400 INVALID_ARGUMENT`), 401/403 (key or billing) and 404 (retired model id) fit neither class.
  - If an implementer maps them to `invalid`, a configuration fault burns all 3 attempts and fails every receipt.
  - If they map them to `unavailable`, the fault hides as an endless wait. The fault is ours, not the receipt's.
- **Fix:** Add a rule:
  - Any other `ClientError` is `unavailable` and raises the AD-13 alert ("Gemini config/auth failure"). The receipt waits and no attempt is consumed.
  - Schema size is caught by a fixture test per chain plug-in, so 400s never reach production.

### G-6 — The Gemini API surface is unnamed; the Interactions API stores data by default `[medium]`

- **Evidence:** Google's docs now lead with `client.interactions.create`. The migration guide recommends Interactions for new work, and adds: "While `generateContent` remains fully supported." Interactions stores the request server-side by default (`store=true`); `store=false` makes it stateless. The retention period is not stated.
- **Risk:** Receipt images are personal data. Server-side storage is a privacy and data-leaving-host point that the owner has not approved, per the AGENTS.md external-service rule.
- **Fix:** Add to AD-4 that calls use `client.models.generate_content`: it is stateless, fully supported, and works with `response_json_schema` or `response_schema` plus `thinking_config`, all present in v2.32.0. If Interactions is ever used, `store=false` is mandatory. Send image and PDF bytes inline with `types.Part.from_bytes`. PDFs are within limits (50 MB or 1000 pages, 258 tokens per page). Telegram's 20 MB download cap keeps every file well under that.

### S-1 — Structured-output schema limits apply to chain schemas `[low]`

- `minLength`, `maxLength`, `uniqueItems` and similar keywords are silently stripped, not enforced. `minItems` and `maxItems` are enforced.
- Domain validation must re-check through pydantic `model_validate_json`; never trust the schema alone. AD-5 and AD-7 already imply this. Add a sentence to AD-6 that the chain schema is validated client-side.

### T-1 — Telegram reaction constraints `[low]`

- Verified in Bot API 10.3:
  - `setMessageReaction` exists.
  - A bot can set at most one reaction per message, and it cannot use paid reactions.
  - Custom emoji only work if they are already present or allowed by the chat admins.
  - `ReactionTypeEmoji` accepts only a fixed list of emoji.
  - `sendDocument` allows up to 50 MB, above the 20 MB `getFile` cap, so the admin file copy always fits.
  - `getUpdates` keeps updates for at most 24 hours. AD-2's acknowledge-after-commit is correct; a service down for more than 24 hours loses unread updates. Telegram imposes this limit and the spine cannot fix it, but the overview should mention it.
- **Fix:** When the texts file loads, check each reaction emoji against the `ReactionTypeEmoji` list and fail fast. Otherwise a wrong emoji only fails at send time and is only logged.

### P-1 — Pin the base image `[low]`

`python:3.14-slim` floats; it was rebuilt today. Pin `python:3.14.8-slim-trixie` (or a digest) and `ghcr.io/astral-sh/uv:0.13.4`. This matches the exact-version pin policy.

## Verified with no change needed

- All Python package versions, the 3.14 support of every package, the psycopg binary wheels for cp314, and the httpx/google-genai version coupling.
- `uuid.uuid7()` in the 3.14 stdlib (memlog source).
- Gemini 3.6 and 3.8 Flash accept image and PDF input and structured output. The SDK sync client exposes typed `ClientError` and `ServerError` with HTTP code and status.
- The Telegram methods the spine uses, the 20 MB download and 50 MB upload limits, and the 429 `retry_after` field.

## Not verified

- Whether `thinking_budget=0` is rejected or ignored on 3.x Flash; no live call was made.
- The exact JSON shape of a current Gemini 429. The `RetryInfo` evidence comes from community reports; record a fixture.
- How long the Interactions API retains stored data.
