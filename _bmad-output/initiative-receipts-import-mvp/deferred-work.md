# Deferred work

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-toolchain-pins-and-ci-plan.md`
  summary: Add `uv sync --locked`, `uv run pytest -m integration` and the `RRI_TEST_DATABASE_URL` test DSN to the AGENTS.md standard check suite so it matches CI.
  evidence: AGENTS.md requires local commands and CI to stay in sync, but its list has only the four checks; editing AGENTS.md is an owner decision.
  resolution: done on owner approval, 2026-10-21.
