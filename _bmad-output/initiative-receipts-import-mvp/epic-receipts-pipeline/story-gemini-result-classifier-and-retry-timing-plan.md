---
title: 'Gemini result classifier and retry timing'
type: 'feature'
ticket: '5'
created: '2026-10-23'
status: 'ready-for-dev'
baseline_revision: '23fbd1673df09a393777511995a7af963538eef2'
route: 'full'
route_source: 'auto'
risk: 'high'
review: 'thorough'
review_source: 'risk'
lenses_ran: []
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
