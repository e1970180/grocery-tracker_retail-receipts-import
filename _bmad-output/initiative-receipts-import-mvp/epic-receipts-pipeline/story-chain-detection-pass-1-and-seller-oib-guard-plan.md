---
title: 'Chain detection (pass 1) and seller-OIB guard'
type: 'feature'
ticket: '18'
created: '2026-10-23'
status: done
baseline_revision: '03d7c3a45b6d7f4ea98d2b2c8936419756e535a5'
route: 'full'
route_source: 'auto'
risk: 'high'
review: 'quick'
review_source: 'pinned'
lenses_ran: ['quick']
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The pipeline takes the chain from the caller, so a receipt from an unknown or wrong chain is extracted with the wrong plug-in, and nothing checks that the printed seller OIB belongs to the chain.

**Approach:** Add a pass 1 that picks the chain (from the active `chains_v1` chains plus `other` and `unreadable`) and the pipeline routes on it; publish `chains_v1` 1.1.0 with `seller_oibs` and reject receipts whose printed seller OIB is not among the chain's OIBs.

## Boundaries & Constraints

**Always:** Pass 1 schema and prompt are built from the reference read before each pass 1. Mismatched or missing printed OIB gives `Invalid(no_valid_result)`. A pass-1 purchase time that cannot be read is not an error. Executor is Antigravity (Gemini 3.8 Flash); owner approves the one-time live recording of four Spar pass-1 responses.

**Decisions (owner):** The dev DB is brought to 1.1.0 by recreating the table from `chains_v1.sql` 1.1.0 (OIBs in the INSERT rows, no separate upgrade script). The four Spar `pass2.json` fixtures get the printed seller OIB added by hand; the value was read from the source PDFs (all four print the same Spar seller OIB), so live recording is for pass 1 only (4 calls).

**Never:** No job persistence, retries, attempts or `unsupported_chain` repeat logic (other entries). No alerting. No production DB. No change to the Gemini client or config.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Known chain | pass 1 `spar`, OIB in chain OIBs | `Stored` | none |
| Other | pass 1 `other` | `Unsupported` with printed store name | none |
| No plug-in / inactive | pass 1 chain without plug-in or inactive | `Unsupported(chain_id)` | none |
| Unreadable | pass 1 `unreadable` | `Invalid(no_valid_result)` | none |
| Wrong OIB | printed OIB not in chain OIBs | `Invalid(no_valid_result)` | no OIB value in detail |
| Missing OIB | pass 2 has no OIB | `Invalid(no_valid_result)` | none |
| Bad reference row | OIB not 11 digits or empty | row rejected by reader | reject reason recorded |

</frozen-after-approval>

## Code Map

- `src/retail_receipts_import/app/pipeline.py` -- `process_file(path, mime, chain_id, source, ports)`; drop `chain_id`, run pass 1, add reference-read port to `Ports`; `Unsupported` gains store name.
- `src/retail_receipts_import/domain/chains/__init__.py` -- `KnownChain` gains `seller_oibs: tuple[str, ...]`; sentinels `OTHER`/`UNREADABLE` already here.
- `src/retail_receipts_import/domain/chains/registry.py` -- `ChainPlugin` protocol: add `pass1_time_hint`, `normalize_pass1_time` (returns None when unreadable, never raises), `seller_oib(response)`; `PLUGINS` stays the only supported list.
- `src/retail_receipts_import/domain/chains/spar/{__init__,schema,prompt,normalize}.py` -- add printed seller OIB to `SparPass2` and prompt; time hint and `normalize_pass1_time` reuse the `Vaša kupnja dana … u HH:MM` regexes.
- New pass-1 module (schema with chain enum, prompt with aliases and hints, supported-chain check); pass-1 field names are separate from `SparPass2` (the card-field test bans `chain` there).
- `src/retail_receipts_import/adapters/postgres/chains.py` -- `QUERY`, `_validate`, `_row_fault` for `seller_oibs`; new reject reason.
- `docs/contracts/chains_v1.{md,sql}`, `docs/api-versions.md` -- 1.1.0, column, CHECK (non-empty, 11 digits), upgrade path for existing dev DB.
- `tests/{test_pipeline,test_chains_reader,test_spar_fixtures,spar_samples}.py`, `tests/fixtures/spar/*` -- update; `FakePorts` needs a call queue; `test_chain_without_plugin_is_unsupported_without_a_call` is rewritten.
- Do not change: `adapters/gemini/client.py`, `config.py`, `outcomes.py`.

## Tasks & Acceptance

**Execution:**
- [x] contract files -- publish 1.1.0 with `seller_oibs` (from-scratch script only) -- consumers read by view name
- [x] reader and `KnownChain` -- read and validate `seller_oibs` -- guard needs the OIBs
- [x] protocol and Spar -- pass-1 hint, time normalizer, printed OIB -- plug-in owns chain specifics
- [x] pass-1 module -- dynamic schema/prompt, supported check -- chain comes from the image
- [x] pipeline -- pass 1, routing, OIB compare -- replaces caller chain
- [x] tests and fixtures -- offline cases from the matrix; four Spar fixtures through pass 1 from recorded responses

**Acceptance Criteria:**
- Given recorded pass-1 and pass-2 responses for the four Spar samples, when the pipeline runs offline, then each stores the expected receipt.
- Given the dev DB with OIBs filled in, when sample …2600 runs live, then a receipt is stored with the chain taken from pass 1.

## Implementation Notes

- `docs/contracts/chains_v1.sql` uses `array_to_string(seller_oibs, ',') ~ '^[0-9]{11}(,[0-9]{11})*$'` in CHECK constraints to validate 11-digit array elements without disallowed subqueries.
- `create_pass1_schema` creates a dynamic subclass of `Pass1Response` (`__base__=Pass1Response`) with dynamically typed `chain` Literal, preserving static type safety for header attributes (`store_name`, `purchase_date`, `purchase_time`).
- `SparPlugin.seller_oib` parses the JSON to extract the seller OIB safely without throwing on partial payloads.
- The four Spar `pass2.json` fixtures received `"seller_oib": "46108893754"`. Offline tests in `test_spar_fixtures.py` verify end-to-end pipeline execution on all four samples with synthetic pass 1 (and will pick up `pass1.json` once live-recorded).
- Real seller OIBs for the remaining chains were read from receipt samples in `doc-inbox/fixtures/` and added to `chains_v1.sql` and `chains_v1.md`: dm (`94124811986`), Kaufland (`47432874968`), Lidl (`66089976432`), and Müller (`84698789700`).
- 2026-10-23, owner-approved live stage: `scratch/record_spar_pass1.py` recorded the four `pass1.json` (one call each; a first attempt got 500 INTERNAL and wrote nothing). Each names `spar` with the store, date and time of its `pass2.json`; the fixture test now replays both passes.
- 2026-10-23: the owner recreated the dev reference with `scratch/recreate_chains_dev.sql` (psql from a `postgres:18` container, as `postgres`). `scratch/read_chains.py` as `rri_dev_writer` read five active chains, none rejected.
- 2026-10-23: `scratch/ingest_local.py` ran …2600 against dev with the live reference and replayed `pass1.json`/`pass2.json`: `Stored(01a1694e-3b72-72b9-aa5c-47fe356cbe24)`, chain `spar`, 18 lines, one card settlement of 54.25, one feed row. The source (chat 0 message 3) is the one the earlier Spar run used, so the writer returned that row as its own write; no new row was inserted.
- Integration tests (`pytest -m integration`) were not run: no throwaway `RRI_TEST_DATABASE_URL`.

## Plan Change Log

## Review Triage Log

| # | Finding | Verdict | Route | Evidence |
| --- | --- | --- | --- | --- |
| 1 | AC1: no recorded `pass1.json`; fixture test synthesizes pass 1 | false | reject | Recording is the owner-approved live step the plan leaves open; the test reads `pass1.json` once recorded. Not a code defect. |
| 2 | AC2: no live-run evidence | false | reject | Same: owner-gated live run, still pending. |
| 3 | Inactive-chain test used an impossible reference (lidl both active and inactive) and only proved "no plug-in" | medium | patch | Reader never lists an inactive id in `chains`. Rewritten: withdrawn spar is absent from enum and prompt, `other` gives `Unsupported`, naming `spar` anyway gives `Invalid` with no pass 2. |
| 4 | SQL CHECK accepts one element `'46108893754,47432874968'` | medium | patch | Joined string matches the regex. Added length = 12 × cardinality − 1, which forces one 11-digit group per element. |
| 5 | Reader `isdigit` accepts non-ASCII digits | low | patch | `'²'.isdigit()` is True; added `isascii()`. |
| 6 | `normalize_pass1_time` unused, duplicates `_purchase_time` | false | reject | Required by the Code Map and plug-in protocol; fixing means editing this plan. |
| 7 | Blank pass-1 store name becomes `""` | low | patch | `"   ".strip()` is `""`; now `None`, test added. |
| 8 | `seller_oib` re-parses JSON with broad `except Exception` | low | patch | Now reads via `SparPass2` with `except ValidationError`; unit test uses full payloads. |
| 9 | `pass1.py` docstrings say what, not why | low | patch | Rewritten to reasons. |
| 10 | (own) OIBs for dm, Kaufland, Lidl, Müller | false | reject | Verified against samples: dm 9/9 PDFs, Kaufland 208/208, Spar 21/21, Lidl and Müller images print the listed OIBs. |

## Design Notes

OIB compare lives in the pipeline: the plug-in only reports the printed OIB, the pipeline holds the reference. Mismatch reuses `no_valid_result`, so `texts/messages.toml` is unchanged.

## Verification

**Commands:**
- `wsl -- bash -lc 'UV_PROJECT_ENVIRONMENT=$HOME/.venvs/$(basename "$PWD") PYTHONPYCACHEPREFIX=$HOME/.cache/pyc uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest'` -- expected: all pass
- `uv run pytest -m integration` (same WSL wrapper, throwaway `RRI_TEST_DATABASE_URL`) -- expected: pass

**Manual checks:**
- Owner confirms dev OIB values and the live run of sample …2600.
