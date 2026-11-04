---
epic: epic-shared-chains-contract
date: 2026-11-04
verdict: accepted
criteria: declared
headless: false
---

# Retrospective: epic-shared-chains-contract

## Epic summary

- **Initiative:** `initiative-multi-country-import`
- **Epic:** `epic-shared-chains-contract` ("Shared chains contract and optional tax identifier")
- **Tickets and Statuses:**
  - `1.1`: `Consumer contract chains_v1 update and common ownership` — `built` (state: `review`)
  - `1.2`: `PostgreSQL chain reference adapter for optional tax numbers and country code` — `built` (state: `review`)
  - `1.3`: `Pipeline seller guard relaxation for chains without tax numbers` — `built` (state: `review`)
  - `1.4`: `Test fixtures and integration suite for shared chains reference` — `done` (state: `done`)
  - `1.5`: `Refactor sweep and documentation parity` — `done` (state: `done`)
- **Tickets at `built` (awaiting final acceptance to `done`):** `1.1`, `1.2`, `1.3`.
- **Unfinished tickets (`pending_tickets`):** None (0 pending).
- **Plan ranges and commits:**
  - `1.1`: `39f305c..6999c1d` (1 commit: `6999c1d`)
  - `1.2`: `6999c1d..11349c7` (1 commit: `11349c7`)
  - `1.3`: `11349c7..fba03a2` (1 commit: `fba03a2`)
  - `1.4`: `fba03a2..da443fb` (1 commit: `da443fb`, covered by 1.2 and 1.3)
  - `1.5`: `da443fb..HEAD` (2 commits: `25a08e5`, `0587dab`)
  - **Full Epic Range:** `39f305c..HEAD` (`0587dab`), 6 commits, 0 merges.
- **Evidence inventory:**
  - Available:
    - Epic file: `_bmad-output/initiative-multi-country-import/epic-shared-chains-contract/epic-shared-chains-contract.md`
    - Initiative file: `_bmad-output/initiative-multi-country-import/initiative-multi-country-import.md`
    - Story file: `story-consumer-contract-chains-v1-update-and-common-ownership.md` (1.1)
    - Plan files for all 5 tickets
    - Git commit log and unified diffs across `39f305c..HEAD`
    - Local verification suites: `ruff check`, `ruff format --check`, `mypy` strict, `pytest` unit/mock suite
  - Missing:
    - Session conversation logs for past tickets (not recorded in repository; process-lesson analysis narrowed to plan triage notes and git commit metadata).
    - `RRI_TEST_DATABASE_URL` environment variable is not configured in local development environment; integration tests against a live throwaway PostgreSQL database could not be executed locally.

## Findings

### Aggregate views

- **Architecture delta (clean):**
  - Dependency changes are minimal and strictly conform to layering:
    - Domain: `KnownChain` (`src/retail_receipts_import/domain/chains/__init__.py:25-30`) gained `country_code: str` and `tax_numbers: tuple[str, ...]`.
    - Adapter: `src/retail_receipts_import/adapters/postgres/chains.py:12-155` updated query, row parsing, and validation using standard library `re`.
    - Pipeline: `src/retail_receipts_import/app/pipeline.py:235-242` wraps the seller guard in `if known_chain.tax_numbers:`.
  - No new external dependencies, no circular imports, no cross-layering violations.
  - Disposition: *Accept as-is*.
- **Duplication map (clean):**
  - Validation rules for `country_code` (`^[A-Z]{2}$`) and `tax_numbers` (non-empty strings, no commas, 11-digit ASCII numeric for `HR`) are defined in DDL (`docs/contracts/chains_v1.sql:20-48`) and mirrored deterministically in adapter validation (`chains.py:132-154`).
  - No duplicate logic or re-implemented helpers were created across tickets.
  - Disposition: *Accept as-is*.
- **Size and god-class growth (clean):**
  - Source code changes across the entire epic are exceptionally compact:
    - `chains.py`: +32 / -16 lines (net +16 lines, total size 155 lines).
    - `pipeline.py`: +9 / -5 lines (net +4 lines, total size 304 lines).
    - `domain/chains/__init__.py`: +3 / -1 lines (net +2 lines, total size 30 lines).
    - `test_chains_reader.py`: +113 / -26 lines (net +87 lines, total size 307 lines).
    - `test_pipeline.py`: +19 / -6 lines (net +13 lines, total size 407 lines).
  - No files exceed healthy thresholds.
  - Disposition: *Accept as-is*.
- **Pattern divergence (clean):**
  - All new code adheres to repository idioms: dataclass domain models, typed `StrEnum` for failure reasons, explicit regex fullmatch validation, strict type annotations, and English docstrings describing design intent ("why").
  - Disposition: *Accept as-is*.
- **Spec-to-implementation reconciliation (clean):**
  - All 5 "Done when" criteria from `epic-shared-chains-contract.md` and requirements E1–E7 / R1–R4 from the initiative are fully satisfied in the code, contracts, and tests.
  - In-place versioning of `chains_v1` (version 1.2.0) is clearly documented with ownership transferred to `grocery-tracker/common` (`docs/contracts/chains_v1.md:5-9, 53-64`).
  - Guide `docs/adding-a-chain.md:75-77, 263, 288` was kept strictly synchronized with code and contract changes.
  - Disposition: *Accept as-is*.

### Diff-scope review lenses

- **Verification gap (medium — non-blocking):**
  - *Location:* `tests/test_chains_reader.py` (integration tests)
  - *Observation:* While in-memory connection unit tests (`_RowsConnection`) cover the complete input matrix (valid HR, valid DE, NULL/empty tax numbers, malformed country codes, malformed tax numbers), live integration tests against a real PostgreSQL instance require `RRI_TEST_DATABASE_URL`, which was unset in this development session. Plan 1.2 triage log already explicitly noted this limitation.
  - *Consequence:* Constraint verification against live PostgreSQL DDL (`chains_v1.sql`) relies on CI or a test environment with `RRI_TEST_DATABASE_URL` configured.
  - *Disposition:* *Defer* to CI pipeline execution with throwaway PostgreSQL database.
- **Intent alignment / Boundary scope (low — informational):**
  - *Location:* `src/retail_receipts_import/app/pipeline.py:236`
  - *Observation:* In `_extract`, the call remains `plugin.seller_oib(pass2_text)` and the error string reads `"seller OIB does not match chain reference"`. When non-Croatian chains without strict OIBs are introduced in `epic-multi-country-pipeline`, this naming and error reporting may be generalized to tax identifiers.
  - *Consequence:* Fully acceptable within this epic's explicit scope boundary ("Keep app/pipeline.py behavior; relaxing seller guard only; multi-country plugins belong to epic-multi-country-pipeline").
  - *Disposition:* *Defer* to `epic-multi-country-pipeline`.

## Behavior verification

- **Static analysis and linting (WSL, Linux):**
  - `uv run ruff check`: Clean, all checks passed.
  - `uv run ruff format --check`: Clean, 101 files formatted.
  - `uv run mypy` (strict mode): Clean, no issues found in 98 source files.
- **Automated test suite (WSL, Linux):**
  - `uv run pytest`: 643 passed, 51 deselected (integration marker), 0 failures.
  - Tested flows include:
    - In-memory parsing of `public.chains_v1` rows (`test_chains_reader.py`): valid HR with OIBs, valid non-HR (DE), NULL tax numbers, empty array tax numbers, rejected invalid rows (bad OIB length/chars, bad country code regex, malformed array elements).
    - Pipeline seller guard logic (`test_pipeline.py`): receipts for chains with `tax_numbers = ()` skip OIB check completely and succeed; chains with configured tax numbers enforce match.
    - All existing chain fixtures (Spar, DM, Kaufland, Lidl, Müller) pass with updated `KnownChain` domain signatures.
- **Live database integration tests:**
  - `uv run pytest -m integration`: 51 integration tests require `RRI_TEST_DATABASE_URL` (intentionally failed at fixture setup when unset).

## Previous-retro follow-through

No previous retrospective document exists in `_bmad-output/` (this is the inaugural epic of `initiative-multi-country-import`). There were no outstanding action items to verify.

## Action items

1. **Verify integration tests on throwaway PostgreSQL in CI / staging**
   - *Owner:* Dev / CI workflow
   - *Action:* Ensure `RRI_TEST_DATABASE_URL` is configured in CI to execute `pytest -m integration tests/test_chains_reader.py` against PostgreSQL 18 with `docs/contracts/chains_v1.sql`.
2. **Mark tickets 1.1, 1.2, 1.3 as done**
   - *Owner:* Project Owner / Tech Lead
   - *Action:* Confirm human acceptance of tickets 1.1, 1.2, 1.3 currently in status `built` (`state: review`) using `bmad-ticket`.
3. **Generalize plugin method names in epic-multi-country-pipeline**
   - *Owner:* Developer implementing Epic 2
   - *Action:* In `epic-multi-country-pipeline`, evaluate renaming `plugin.seller_oib` to `plugin.seller_tax_number` or adapting per country plugin.

## Decision records

- **Proposed ADR: `adr-in-place-update-chains-v1-to-1-2-0.md`**
  - *Context:* Transitioning chain reference ownership to `grocery-tracker/common` and adding `country_code` and optional `tax_numbers`.
  - *Decision:* Update `chains_v1` in-place to version 1.2.0 rather than creating a new `chains_v2` view.
  - *Why:* Avoids maintaining dual views and temporary synchronization layers across projects; coordinated deploy with `common` provider. (Recorded in `docs/contracts/chains_v1.md` and commit `6999c1d`).
  - *Status:* Proposed for owner sign-off.

## Acceptance verdict

- **Verdict:** **accepted**
- **Criteria:** declared (governed by Done when criteria 1–5 in `epic-shared-chains-contract.md`)
- **Evidence:**
  - Done When 1: `docs/contracts/chains_v1.md` reflects 1.2.0 in-place contract, optional `tax_numbers`, `country_code`, and `grocery-tracker/common` ownership (commit `6999c1d`).
  - Done When 2: `KnownChain` and PostgreSQL adapter load active chains, support `country_code` and optional/null `tax_numbers`, and reject invalid rows per contract matrix (`chains.py`, `test_chains_reader.py`, commit `11349c7`).
  - Done When 3: Pipeline seller guard allows receipts without tax numbers to process cleanly, while continuing to guard chains with tax numbers (`pipeline.py`, `test_pipeline.py`, commit `fba03a2`).
  - Done When 4: All existing chain tests (Spar, DM, Kaufland, Lidl, Müller) pass cleanly (643 passed).
  - Done When 5: Strict check suite (`ruff check`, `ruff format --check`, `mypy` strict, `pytest`) passes with 0 errors.
  - Incomplete work: 0 unfinished tickets (`pending_tickets` is empty).

## Open questions

1. Would the owner like to formalize the in-place contract decision as a standalone ADR document under `docs/decisions/adr-0001-in-place-chains-v1-update.md`, or is the existing contract versioning section in `docs/contracts/chains_v1.md` sufficient?
2. Are you ready to close tickets 1.1, 1.2, 1.3 (`mark done`) in `bmad-ticket` and proceed to `epic-multi-country-pipeline`?
