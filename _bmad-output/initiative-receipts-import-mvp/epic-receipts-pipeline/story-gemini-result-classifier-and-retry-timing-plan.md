---
title: 'Gemini result classifier and retry timing'
type: 'feature'
ticket: '5'
created: '2026-10-23'
status: 'done'
baseline_revision: '23fbd1673df09a393777511995a7af963538eef2'
route: 'full'
route_source: 'auto'
risk: 'high'
review: 'thorough'
review_source: 'pinned'
lenses_ran: ['blind-hunter', 'edge-case-hunter', 'verification-gap', 'intent-alignment']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every Gemini failure is an untyped exception. The loop retries it every `job_retry_delay_s`, whatever the cause: a 429 RetryInfo, a bad key, or a file Gemini rejects. Images reach Gemini unrotated and at any pixel count.

**Approach:** The adapter raises one typed, key-redacted error carrying the classification facts. A single pure function in `domain` maps it to `unavailable`, `blocked` or `invalid` with a delay. The pipeline turns `invalid` into its existing `Invalid` result. `unavailable` and `blocked` become a wait the loop postpones by. Images are EXIF-transposed and capped in memory before pass 1.

## Boundaries & Constraints

**Always:**
- AD-7 classes, judged on SDK status and ErrorInfo reason, not the HTTP code alone.
- The delay is RetryInfo `retryDelay`, else integer `Retry-After`, else capped exponential backoff from a passed-in wait count. Initial delay and cap come from config.
- The API key never appears in any field, message, `__context__` or `__cause__`.
- The saved file is never modified, and a PDF is passed byte-identical.
- Fixtures are recorded once, live, with the owner's approval, and have the project number scrubbed. The exceptions are the 429 with RetryInfo and the zero-quota 429: their bodies are hand-built from Google's documented error format and marked synthetic in the fixture (owner, 2026-10-23).
- The plan stays whole at about 1,820 tokens; the owner declined the split (2026-10-23).

**Never:**
- No attempt counting, wait state, in-progress reaction or `gemini_config` alert; those belong to entries 6, 12 and 13.
- No persisted wait counter: the loop passes 0 until entry 6.
- No SDK `retry_options`, and no jitter.
- No personal receipt images in tests; synthetic Pillow images only.

## I/O & Edge-Case Matrix

| Scenario | Input | Class / delay |
|---|---|---|
| 429 with RetryInfo | ClientError 429 RESOURCE_EXHAUSTED, `retryDelay "37s"` | unavailable, 37 s |
| 429 with zero quota | 429, message text `limit: 0` (owner, 2026-10-23) | blocked |
| 5xx with Retry-After | ServerError 503, header `120` | unavailable, 120 s |
| Timeout or transport | `httpx.TimeoutException`, `httpx.TransportError` | unavailable, backoff |
| Bad key | 400 INVALID_ARGUMENT, reason `API_KEY_INVALID` | blocked |
| 401 / 403 / retired model 404 | PERMISSION_DENIED, NOT_FOUND | blocked |
| Billing or configuration failure | 400 FAILED_PRECONDITION | blocked (owner, 2026-10-23) |
| 400 without a known reason | INVALID_ARGUMENT | invalid (owner, 2026-10-23) |
| Schema-invalid reply | recorded text failing the pass schema | pipeline `Invalid(no_valid_result)` |
| Unknown exception type | anything else | re-raised to the AD-16 boundary, unchanged |
| Corrupt or bomb image | `UnidentifiedImageError`, `DecompressionBombError` | `Invalid(no_valid_result)` |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/adapters/gemini/client.py`. `generate` is the only SDK call. Its redaction path (`GeminiError`, raised outside `except`) is kept for the new typed error. SDK errors are `google.genai.errors.APIError` (`ClientError` for 4xx, `ServerError` for 5xx), with `.code`, `.status`, `.details` (the error JSON with `error.details[]` holding `@type` RetryInfo, ErrorInfo and QuotaFailure) and `.response` (`httpx.Response`, which carries the headers). With `retry_options` unset the SDK makes one attempt, and httpx timeouts escape raw.
- `src/retail_receipts_import/app/pipeline.py`. `process_file` makes both `ports.generate` calls. `Result` stays as is.
- `src/retail_receipts_import/app/loop.py`. `run_due` postpones every exception by `settings.retry_delay`.
- `src/retail_receipts_import/app/jobs.py`. Its `match` has no default branch, so this story adds no `Result` variant.
- `src/retail_receipts_import/domain/intake.py`. `ACCEPTED_MIME_TYPES` is the shared accepted-type list.
- `src/retail_receipts_import/config.py`. `Settings`.
- `tests/test_gemini_client.py`. `test_other_errors_propagate_unchanged` changes for transport errors.
- `scratch/record_spar.py` is the pattern for the recording script.

## Tasks & Acceptance

**Execution:**
- [ ] `src/retail_receipts_import/domain/extraction.py` -- `ExtractionClass` enum, a `GeminiCallError` facts dataclass (code, status, reason, retry_delay, retry_after, transport flag, redacted detail), and `classify(facts, waits, initial, cap) -> Classification(kind, delay)` -- the one AD-7 function, pure and testable.
- [ ] `src/retail_receipts_import/adapters/gemini/client.py` -- fill the facts from `APIError` or httpx errors with plain values only (never `.response`, `.request` or the original exception, which reach the `x-goog-api-key` header), redact them, and raise; parse Duration strings -- adapters raise typed errors.
- [ ] `src/retail_receipts_import/adapters/gemini/images.py` -- `prepare(data, mime, max_pixels) -> bytes`: original bytes when orientation is 1 or absent and within the cap; otherwise EXIF transpose, downscale to the cap, encode in the declared mime's format; PDFs untouched; any `OSError` or `DecompressionBombError` becomes `Invalid` -- AD-2's shared list and the untrusted-input convention.
- [ ] `src/retail_receipts_import/app/pipeline.py` -- prepare once before pass 1, classify a `GeminiCallError`, return `Invalid` for invalid, raise `ExtractionWait(kind, delay)` otherwise.
- [ ] `src/retail_receipts_import/app/loop.py` -- postpone an `ExtractionWait` by its delay, logged as one line without traceback: WARNING for unavailable, ERROR for blocked, with status and reason.
- [ ] `src/retail_receipts_import/config.py` -- `gemini_backoff_initial_s=600` (today's retry interval, owner 2026-10-23), `gemini_backoff_cap_s=1800`, `image_max_pixels=16_000_000`.
- [ ] `scratch/record_gemini_errors.py` -- one-time recording into `tests/fixtures/gemini/` (status, used headers, scrubbed body), using a fake key, a 1 ms timeout, a retired model; the 404 and 403 cases may need the dev key if a fake key fails first with `API_KEY_INVALID`, checked during recording; only `Retry-After` is kept from headers; it writes the two synthetic 429s too, from the documented format.
- [ ] `tests/test_classify.py`, `tests/test_images.py`, plus updates to the existing tests -- the matrix rows from fixtures rebuilt as `ClientError(code, body, httpx.Response(...))`, plus a truncated JPEG and a non-JSON 502; a photo, an image document and a PDF reaching a fake `generate` in their prepared form; a walk of the error's `__dict__` and its `__context__`/`__cause__` chain finds no key.

**Acceptance Criteria:**
- Given the recorded 429, timeout, auth failure and schema-invalid reply, when the unit tests run offline, then each returns its matrix class and delay.
- Given an orientation-6 JPEG over the cap, when it is processed, then Gemini receives it upright, within the cap, as `image/jpeg`, and the saved file is unchanged.
- Given a Gemini wait, when the loop handles it, then the job is postponed by the classifier's delay and not by `job_retry_delay_s`.

## Design Notes

A disabled quota is a 429 that Gemini marks only in the message text `limit: 0`, which is checked. Backoff is `min(cap, initial * 2**waits)`. Until entry 6 persists the wait count, it stays at `initial`. A fractional Duration rounds up, every delay is at least 1 s, and an unparseable value falls through to the next source. A non-JSON error body, which the SDK turns into `{message, status: reason_phrase}`, is classified by code alone.

## Verification

**Commands:**
- `wsl -- bash -lc '... uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all green.

## Implementation Notes

- Owner, 2026-10-23: plan approved; code is written by Claude Opus 5.5 in a separate Claude Code CLI session (corrected from Gemini 3.8 Flash the same day); the one-time live recording of the error fixtures is approved.
- Process: by owner instruction the workflow's implementation subagent was not used; Claude Opus 5.5 implemented directly in the session. Review lenses ran as subagents. The first render of the workflow omitted the `thorough` selection named in the invocation; it was re-rendered with `workflow.review=thorough` before review.
- Wiring: `classify` and `prepare` reach the pipeline as two new `Ports` callables. `service.serve` binds them with `functools.partial`, including `waits=0`, because the config lives there; the loop itself never sees a wait count. `ExtractionWait` lives in `app/pipeline.py` and carries the `Classification` plus the plain error; the loop catches it before the generic handler.
- Adapter: `GeminiCallError` is an `eq=False` dataclass exception in `domain/extraction.py`. The adapter parses the Duration (rounded up) and the integer `Retry-After` into whole seconds, so `None` means "absent or unparseable" and `classify` only falls through. Unknown exceptions keep the old path: re-raised unchanged, or `GeminiError` when their text carries the key.
- Classes: transport errors, 5xx and any non-4xx code are `unavailable`; a 429 is `blocked` only when the message matches `limit: 0` (not `limit: 0.5`); statuses `UNAUTHENTICATED`, `PERMISSION_DENIED`, `NOT_FOUND`, `FAILED_PRECONDITION`, reason `API_KEY_INVALID`, or codes 401/403/404 (for non-JSON bodies) are `blocked`; every other 4xx is `invalid`.
- Google's zero-quota 429 also carries RetryInfo, so a blocked job would have retried every 37 s with an ERROR each time. Owner, 2026-10-23: a `blocked` wait ignores RetryInfo and `Retry-After` and takes the backoff (600 s at `waits=0`); the delay source order now applies to `unavailable` only.
- Owner, 2026-10-23: a 400 INVALID_ARGUMENT without a known reason stays `invalid`, accepting that a configuration regression fails queued receipts, until attempt counting exists. Confirmed decisions taken during the build: 408/409/499 are `unavailable`; Pillow decodes only JPEG, PNG and WebP; a Pillow `ValueError` is `Invalid`; the wait log line carries up to 500 characters of the redacted message.
- Live-run evidence: the one-time recording run above (four live Gemini error responses through the SDK, classified offline by the real adapter and `classify`).
- Images: Pillow may open only JPEG, PNG and WebP, whatever the declared type, to keep exotic decoders away from chat input; a GIF declared as PNG is `Invalid`. `load()` runs on the fast path too, so a truncated file is caught before it is sent. Re-encoding uses quality 90 and drops EXIF. Pillow's own bomb limit (about 179 MP) is kept.
- Recording (2026-10-23, one run, `scratch/record_gemini_errors.py`, gitignored like `record_spar.py`): `api_key_invalid` (fake key, 400 INVALID_ARGUMENT, reason API_KEY_INVALID) and `timeout` (fake key) live; `retired_model` (`gemini-1.0-pro`) was refused for the fake key first, then recorded with the dev key as 404 NOT_FOUND; `permission_denied` used the dev key and a Files API URI the project cannot read, 403 PERMISSION_DENIED. Both 429s are synthetic. `scratch/check_gemini_fixtures.py` found no key and no 9+ digit number in any fixture.
- Divergence: the 1 ms timeout case returned `httpx.ConnectError: [Errno 101] Network is unreachable` (IPv6 route in WSL), not a timeout class. It is still a transport error and classifies as the matrix says; the call was not repeated. Timeouts proper are covered by built `httpx.ReadTimeout`/`ConnectTimeout` cases.
- Integration tests were not run: `RRI_TEST_DATABASE_URL` is unset.
- After review: the `timeout` fixture was renamed `transport_error` (script case renamed too, so a rerun still skips it); 408, 409 and 499 are `unavailable`; Duration and `Retry-After` parse at most nine digits; a Pillow `ValueError` is `UnreadableImage`; the wait log line carries the redacted message, flattened to one line and cut at 500 characters.

## Review Triage Log

Lenses: blind-hunter (BH), edge-case-hunter (EC), verification-gap (VG), intent-alignment (IA). Repros: `scratch/repro_review.py`, run before and after the patches.

| # | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | VG: WebP path untested | low | Pre-verified gap; repro showed WebP decodes and scales. | patch: WebP added to passthrough and scale tests, plus a rotated WebP test |
| 2 | VG: `serve` wiring of the three new settings untested | low | Pre-verified gap; `serve` has no harness. | defer (deferred-work.md) |
| 3 | BH/EC: 408, 409, 499 become `invalid` and end the job | medium | Repro: `classify` returned `invalid` for 408/409/499. AD-7 makes `invalid` only a 4xx caused by the file. | patch: `_TRANSIENT_CODES` → `unavailable`; 413 stays `invalid`; tests added |
| 4 | EC: oversized `retryDelay`/`Retry-After` raise inside the adapter's `except`, chained to the key-carrying SDK error | medium | Repro: `OverflowError` (400 digits) and `ValueError` (5000 digits). | patch: parse at most nine digits; tests added; repro now returns `None` |
| 5 | EC: huge server delay overflows `now + delay` in the loop handler | low | Repro: `OverflowError` for 10^13 s built by hand; unreachable after patch 4 (max 999,999,999 s). | fixed by 4 |
| 6 | BH/EC: Pillow raises non-`OSError` on hostile input, which escapes to the endless generic retry | medium | Repro: oversized zTXt raised `ValueError`; a bad IDAT CRC did not raise. | patch: `ValueError` caught; test added. `SyntaxError`/`struct.error` not reproduced, not added |
| 7 | BH: wait log hides the message, so a zero quota looks like a rate limit | low | Read: log had code/status/reason only, and `limit: 0` is in the message. | patch: the redacted detail, whitespace collapsed to keep one line, cut at 500 characters. A first cut at 200 was confirmed by a failing test to drop `limit: 0` from Google's message; the loop test now uses that message and asserts `limit: 0` and no newline |
| 8 | BH: pass-1 wait not tested | low | Read: only `calls_before_error=1` ran. | patch: parametrized over pass 1 and pass 2 |
| 9 | BH/EC: `timeout` fixture is a `ConnectError` | low | Fixture reads `Network is unreachable`. | patch: renamed `transport_error`; divergence reported to the owner |
| 10 | EC: config comment promises doubling while `waits=0` | low | Read: `service` binds `waits=0`. | patch: comment reworded |
| 11 | BH: zero-quota `blocked` retried every 37 s with an ERROR each time | low | True, and 429s are not billed. The delay order is the owner's decision. | owner chose to change it (2026-10-23): `blocked` takes the backoff; tests updated |
| 12 | EC: 400 INVALID_ARGUMENT from a config regression fails every receipt | medium | True by reading; the matrix row "400 without a known reason → invalid" is the owner's decision. | rejected: the owner kept `invalid` (2026-10-23) |
| 13 | BH/EC: declared mime not checked against the decoded format | low | Pre-existing: before this change, bytes were always sent under the declared mime. | rejected: not caused by this change |
| 14 | EC: images between 89 and 179 MP decode fully (Pillow only warns) | low | True by reading; needs an allowlisted sender and a crafted file; a guard adds a branch. | rejected: low and unlikely |
| 15 | BH: EXIF/GPS still sent on the passthrough path | low | Pre-existing: the original bytes always went to Gemini. | rejected: not caused by this change |
| 16 | BH: `Invalid` detail prints `None` and omits the message | low | Cosmetic; the job log shows reason and status. | rejected: cosmetic |
| 17 | BH: no check that `gemini_backoff_cap_s >= gemini_backoff_initial_s` | low | True; `min` keeps it safe, and a validator adds code. | rejected: low |
| 18 | BH: recording script not in the diff; `"key"` field unused | false | `scratch/` is gitignored, as for `record_spar.py`; the field records provenance. | rejected |
| 19 | EC: adapter reads `exc.response.headers` | false | Only the header value is copied; nothing keeps the response. | rejected |
| 20 | IA: other exceptions stay untyped | false | The matrix row "Unknown exception type → re-raised unchanged" requires it. | rejected |
| 21 | IA: production delay unchanged (600 s) for a bad key | false | `waits=0` and initial 600 are owner decisions until entry 6. | rejected |
| 22 | IA: layers never tested as one chain | false | The pipeline tests use the real `classify` and `prepare`, and `test_classify` runs the real adapter into `classify`; only the loop takes a built `ExtractionWait`. | rejected |
| 23 | IA: `ExtractionWait.__str__` text not checked for the key | false | It embeds `str(error)`, whose fields are redacted and checked by `test_the_key_is_nowhere_on_the_error`. | rejected |
| 24 | IA: truncated recorded answer test is unrelated | false | It covers the matrix row "Schema-invalid reply: recorded text". | rejected |
