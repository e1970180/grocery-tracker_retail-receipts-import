# Deferred work

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-toolchain-pins-and-ci-plan.md`
  summary: Add `uv sync --locked`, `uv run pytest -m integration` and the `RRI_TEST_DATABASE_URL` test DSN to the AGENTS.md standard check suite so it matches CI.
  evidence: AGENTS.md requires local commands and CI to stay in sync, but its list has only the four checks; editing AGENTS.md is an owner decision.
  resolution: done on owner approval, 2026-10-21.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-runtime-baseline-and-first-deployment-plan.md`
  summary: Create the production database and roles, deploy to the home server by sparse-checkout `git clone + compose build`, and run `migrate` against production.
  evidence: The owner decided there is no production until the whole project is developed (2026-10-22); story 2 now stops at the dev database.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-spar-receipt-from-pdf-to-dev-plan.md`
  summary: Telegram half of the tracer: vendored Telegram client with the gate for photos, image documents and PDFs, the SQLite job queue with the offset committed with the jobs, the job states and the single loop, the download, the success reaction, and the `allowed_user_ids` setting (parsed from a comma-separated string); it carries the dropped entry 4's dev-bot verify (owner sends a Spar PDF, sees 👍, the stored receipt matches).
  evidence: The tracer plan was about 3,000 tokens against the 1,600 limit; the owner chose to split (2026-10-22). Entry 4 was then split into 4a (model, schema, writer) and 4b (Spar plug-in, Gemini, pipeline), proven on a local Spar PDF. The allowlist `RRI_ALLOWED_USER_IDS=358177329` is already in `.env`.
