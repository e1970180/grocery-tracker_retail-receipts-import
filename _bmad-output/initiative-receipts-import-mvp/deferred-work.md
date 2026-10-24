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

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-telegram-receipt-to-dev-end-to-end-plan.md`
  summary: End a job whose download fails permanently (a Telegram 4xx from getFile or the download, or getFile with no `file_path`) instead of retrying it every `RRI_JOB_RETRY_DELAY_S` forever, with a failure reason and texts the sender and admin can read.
  evidence: Entry 17 keeps every download exception in `received` and retries it, as its matrix requires. A file Telegram no longer serves never ends and never reaches the sender, at one getFile call per retry. The attempt and step-count rules of entries 6 and 13 are where it ends.
  resolution: scheduled as epic entry 19; each failure consumes an attempt, retried after `job_retry_delay_s`, `failed` with `file_unavailable` at the limit, texts approved (owner, 2026-10-23).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-gemini-result-classifier-and-retry-timing-plan.md`
  summary: Test that `service.serve` binds `image_max_pixels`, `gemini_backoff_initial_s` and `gemini_backoff_cap_s` into the `prepare` and `classify` ports, for example through a small `Ports` factory built from `Settings`.
  evidence: The three keyword arguments in `serve` are covered by no test (`serve` opens PostgreSQL and Telegram and has no harness); swapping `initial_s` and `cap_s`, or binding `job_retry_delay_s`, passes mypy and every test. Found by the verification-gap lens; deferred as low, since entry 6 changes this wiring when the wait count is persisted.
  resolution: scheduled as epic entry 19, with the wait count (owner, 2026-10-23).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-job-steps-attempts-and-resume-plan.md`
  summary: Wait count fed into `classify` with doubling to the cap and reset on each transition or attempt; the pipeline ports built from `Settings` in one factory, tested with distinct non-default values; the long poll shortened to the next due job; a permanent download failure consuming an attempt per failure and ending as `failed` with `file_unavailable` and its texts.
  evidence: The entry 6 plan was about 2,400 tokens against the 1,600 limit; the owner left the split to the planner (2026-10-23). Entry 6 keeps the persisted steps, attempts and resume, and adds every queue column this needs.
  resolution: scheduled as epic entry 19, after 6 and before 7 (owner, 2026-10-23).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-gemini-result-classifier-and-retry-timing-plan.md`
  summary: Dev-bot run of the image preparation and the Gemini error path: rebuild the dev service, send a rotated phone photo of a receipt and a Spar PDF, and confirm both are stored as before, with no `ExtractionWait` in the log.
  evidence: Entry 5 (risk high) was closed on the one-time error recording as its live evidence; EXIF transpose, the pixel cap and `prepare` before pass 1 have not run through the live service. The owner postponed the run (2026-10-23).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-job-steps-attempts-and-resume-plan.md`
  summary: The build workflow runs only the quick review lens on risk-high plans, while AGENTS.md requires a thorough review for them.
  evidence: The rendered bmad-build step 4 defines only the quick lens and no _bmad/custom override pins a thorough one; 1.6 (risk high) was reviewed quick.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-full-outcome-matrix-and-effect-order-plan.md`
  summary: The README settings table does not list the required `RRI_ALLOWED_USER_IDS`.
  evidence: Found by the 1.12 quick review; the row has been missing since the setting was added, only `.env.example` documents it.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-job-steps-attempts-and-resume-plan.md`
  summary: A step that raises on every run is postponed without end, and a raise after a Gemini answer repeats a paid call each time; entry 13's three-unrecorded-starts rule must also cover a kept `pass1_json` that no longer parses after a deploy.
  evidence: Thorough retro-review of 1.6: `loop.run_due` postpones on any exception and nothing reads `step_starts`; `jobs._extract` parses `pass1_json` without the fallback `_kept_receipt` gives `receipt_json`.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-operational-alerts-and-per-job-error-boundary-plan.md`
  summary: Per-job error boundary (AD-16): PostgreSQL connection-class errors (SQLSTATE class 08, 57P01–57P03, or none) and Telegram download errors become waits that reset step starts without touching the Gemini wait count, with `postgres_unreachable` and `telegram_unreachable`; any other step exception, and a job picked with three unrecorded step starts, is alerted as `internal:<state>` and logged, and the job is not retried (owner decision 2026-10-24, superseding AD-16's retry with backoff); a kept `pass1_json` that no longer parses goes back to `chain_pending` without an attempt.
  evidence: The 1.13 plan was about 2,400 tokens against the 1,600 limit and implementation goes to Gemini 3.8 Flash; the owner chose to split (2026-10-24). Decision: a job stopped by an internal error is moved to `failed` (owner, 2026-10-24). Open: its failure reason and sender/admin texts, and the matching AD-16 amendment.
  resolution: built in `epic-receipts-pipeline/story-per-job-error-boundary-plan.md` (owner decisions 2026-10-24).

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-per-job-error-boundary-plan.md`
  summary: Rework the wording and layout of every sender and admin message, including the technical lines in alerts and recoveries (for example the bare `postgres_unreachable` key under "PostgreSQL снова доступен.").
  evidence: In the 1.13 live run the owner found the alert key line in the recovery message confusing (2026-10-24); the key, then the reason, follow the texts-file line by the alerts plan. The owner chose a separate pass over all texts instead of a one-off fix.

- source_plan: `_bmad-output/initiative-receipts-import-mvp/epic-receipts-pipeline/story-lidl-plug-in-plan.md`
  summary: A Lidl paper-receipt photo fixture for the Lidl plug-in, as AD-6 asks where a chain issues both paper and digital receipts.
  evidence: All Lidl samples are Lidl Plus app screenshots; no paper receipt is at hand, and the owner chose screenshots only for 1.8 (2026-10-24).
