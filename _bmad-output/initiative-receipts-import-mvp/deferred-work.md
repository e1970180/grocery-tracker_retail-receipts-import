# Deferred work

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-toolchain-pins-and-ci-plan.md`
  summary: Add `uv sync --locked`, `uv run pytest -m integration` and the `RRI_TEST_DATABASE_URL` test DSN to the AGENTS.md standard check suite so it matches CI.
  evidence: AGENTS.md requires local commands and CI to stay in sync, but its list has only the four checks; editing AGENTS.md is an owner decision.
  resolution: done on owner approval, 2026-10-21.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-runtime-baseline-and-first-deployment-plan.md`
  summary: Create the production database and roles, deploy to the home server by sparse-checkout `git clone + compose build`, and run `migrate` against production.
  evidence: The owner decided there is no production until the whole project is developed (2026-10-22); story 2 now stops at the dev database.
  resolution: scheduled as epic entry 16, first production deployment and acceptance demo (owner, 2026-10-22).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-spar-receipt-from-pdf-to-dev-plan.md`
  summary: Telegram half of the tracer: vendored Telegram client with the gate for photos, image documents and PDFs, the SQLite job queue with the offset committed with the jobs, the job states and the single loop, the download, the success reaction, and the `allowed_user_ids` setting (parsed from a comma-separated string); it carries the dropped entry 4's dev-bot verify (owner sends a Spar PDF, sees 👍, the stored receipt matches).
  evidence: The tracer plan was about 3,000 tokens against the 1,600 limit; the owner chose to split (2026-10-22). Entry 4 was then split into 4a (model, schema, writer) and 4b (Spar plug-in, Gemini, pipeline), proven on a local Spar PDF. The allowlist `RRI_ALLOWED_USER_IDS=358177329` is already in `.env`.
  resolution: scheduled as epic entry 17, the tracer bullet (owner, 2026-10-22).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-receipt-model-and-storage-plan.md`
  summary: Dev live check of the receipt writer: run `migrate` on `grocery-tracker-dev` as `rri_dev_owner` to apply `0002`, then `scratch/write_synthetic.py` as `rri_dev_writer` writes a synthetic `spar` receipt dated 2001-01-01 12:00 Zagreb from chat 0 message 1, reruns it, then writes it from chat 0 message 2; expected output stored, own write, duplicate, with one receipt and one feed row. The receipt stays in dev and `resolver_v1` will see it; a privilege error is reported, never patched in a migration.
  evidence: The plan was about 2,400 tokens against the 1,600 limit; the owner chose to split and run this check right after the 4a build (2026-10-23). CI runs as superuser, so this is the only proof of the writer role privileges, and live-run evidence for the high-risk 4a.
  resolution: done on owner approval, 2026-10-23: `0002` applied; stored, own_write, duplicate as expected, one receipt and one feed row, no privilege error.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-receipt-model-and-storage-plan.md`
  summary: Admin command to delete a wrongly stored receipt so it can be resent: in one transaction it deletes the receipt (lines and settlements cascade) and inserts a `deleted` feed event, which `resolver_v1` exposes.
  evidence: Owner chose to support deletion (2026-10-23), because a receipt stored with a correct time but a wrong detail turns its resend into a duplicate. 4a adds the cascades and the `deleted` event to the schema; the command waits for the Resolver contract (entry 14).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-receipt-model-and-storage-plan.md`
  summary: Document for family members (Russian user guide plus the sender message in the texts file) that a receipt is not stored when a storno cancels more than was sold, or when nothing purchased remains after storno and returns, such as a return-only receipt; and that storno lines and returns are counted in the balance check but never appear in the stored receipt.
  evidence: Owner called this non-trivial behavior and required it to be documented for the user (2026-10-23). 4a rejects such receipts in the model; which outcome and message the sender gets is decided with the first plug-in that reads storno or returns.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-receipt-model-and-storage-plan.md`
  summary: Wrong-chain guard. Publish `chains_v1` 1.1.0 (minor: a new column of seller OIBs, `text[]`, non-empty, 11 digits each) with its `docs/api-versions.md` entry; the admin fills the OIBs in dev. Each plug-in reads the printed seller OIB and returns `invalid` when it is not among its chain's OIBs. The first plug-in (4b, Spar) adds the check to the protocol; plug-ins 8 to 11 inherit it. The rejection is added to the user guide entry above.
  evidence: OCR or pass-1 classification can file a receipt under a valid but wrong `chain_id`, which the Resolver keys on and cannot detect; every Croatian fiscal receipt prints the seller OIB. Owner chose the check and to keep OIBs in the reference rather than in code (2026-10-23).
  resolution: moved from 4b to the chain detection story below, together with pass 1 (owner, 2026-10-23).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-spar-receipt-from-pdf-to-dev-plan.md`
  summary: Chain detection (pass 1) with the seller-OIB guard: the pass-1 schema and prompt from the active `chains_v1` chains with aliases, the two sentinels and per-plug-in time hints; the reference read before each pass 1; `supported(reference)`; the plug-in protocol's pass-1 time hint and `normalize_pass1_time`; `other`, a chain without a plug-in or inactive gives `Unsupported`, `unreadable` gives `Invalid(no_valid_result)`; the pipeline takes the chain from pass 1 instead of the caller; pass-1 responses recorded for the four Spar fixtures; `chains_v1` 1.1.0 with seller OIBs, its `docs/api-versions.md` entry, the reader column, the protocol check and the Spar check, with the admin filling OIBs in dev.
  evidence: The 4b plan was about 2,200 tokens against the 1,600 limit; the owner split along the named seam "pass 1 as its own story" and moved the OIB guard there, since both identify the chain (2026-10-23).
  resolution: scheduled as epic entry 18, before entry 17 (owner, 2026-10-23).
