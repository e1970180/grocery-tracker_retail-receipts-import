---
reviewed: architecture-receipts-import.md (status draft, updated 2026-10-21)
inputs: spec-receipts-import.md, receipt-outcomes.md, addendum.md, .memlog.md, AGENTS.md
reviewer: rubric + reconciliation pass
date: 2026-10-21
---

# Review: architecture spine receipts-import

## Verdict

Solid, well-scoped spine that honors the memlog and almost every input. It needs a few rule additions before inception: Gemini non-transient errors (401/403/400/blocked responses) are unclassified; download/oversize handling relative to the offset commit is ambiguous; the domain receipt model that five chain plug-ins share is deferred; and environment separation (a dev bot that steals production updates) is missing.

Note on scope: `tickets.toml` holds only the epic and no stories yet, so the divergence check runs against the epic's Done-when and the story split the epic implies (platform baseline, intake, extraction per chain, storage, outcomes and alerts, Resolver contract, deployment).

## 1. Reconciliation

### Capabilities

| Item | Landed in | Status |
| --- | --- | --- |
| CAP-1 intake, allowlist, private chat, photo / image doc / PDF | AD-2, AD-3, AD-15 | OK. The gate is inherited from telegram_core. |
| CAP-2 extraction, chain traps | AD-4, AD-5, AD-6 | OK |
| CAP-3 regular/effective price | AD-5 | OK in principle. The rule for checking against printed fields, not price × qty, is not stated (see below). |
| CAP-4 settlement incl. negative | Money convention (signed) | Partial. The settlement-kind vocabulary (card, cash, bonus points, coupon, deposit refund) is deferred to the storage story (finding F3). |
| CAP-5 ±0.01 EUR | AD-5, AD-7 | OK. Per the owner decision in the memlog, a mismatch is `invalid` and is re-extracted before the failure path. |
| CAP-6 dedup + duplicate message | AD-8, AD-9 | OK |
| CAP-7 atomic | AD-10 | OK |
| CAP-8 outcome feedback | AD-3, AD-11, Config convention | OK, with gaps listed under the matrix |
| CAP-9 durable waiting, bounded attempts | AD-1, AD-3, AD-7, AD-14 | OK, except non-transient Gemini errors (F1) |
| CAP-10 alerts | AD-13 | OK. Internal-exception handling for a job is not stated (F4). |
| CAP-11 Resolver contract | AD-12, Deferred field list | OK |

### Constraints

| Constraint | Status |
| --- | --- |
| Gemini Flash only; retry follows service signals (retry-after) | OK (AD-4, AD-7). Risk: the google-genai SDK has its own retry options. The spine does not say whether SDK retries are disabled, so the app backoff and the SDK backoff could stack. Low. |
| Telegram reference "requirements only" | Overridden by the owner (memlog). AD-15 reflects the override. Intended. The memlog says "Spec source should be updated", and that has not been done yet. AD-15 does not cite the override, so a reader of the spec alone sees a contradiction. Low. |
| Telegram retry rules (429 retry_after, max 5), failed send never rolls back | AD-11 step 3 | OK |
| No durable notification queue | AD-11 ("not retried after a crash") | OK |
| Local file kept until final outcome; for failed, until after the admin copy | AD-11 step 4 | Mostly OK. Crash after step 2 and before step 4 leaves an orphaned file of a final job, and nothing sweeps it. Low: add a startup sweep that deletes files of final-state jobs. |
| Supported chains: 5 named | AD-6 registry, naming convention | OK |
| EUR only, LAN PG, ~2/day | Money convention, AD-14 | OK |
| User-facing texts outside code | Config convention, `texts/messages.toml` | OK. The duplicate text "Данный чек уже внесен в систему" must be a texts-file entry. That is implied, not stated. |
| Fresh data model, legacy meaning only | Naming convention | OK |
| Recovery = resend only | No manual path anywhere | OK (respected) |

### Outcome matrix rows

| Row | Status |
| --- | --- |
| Valid, consistent, new | `stored` + success reaction. OK. |
| Same purchase already stored | `duplicate`, AD-8/AD-9. OK. |
| Chain not supported (sender message + admin message) | `unsupported_chain` state. The sender and admin effects are not spelled out but follow AD-11 + texts. OK. |
| Items/settlement disagree | Folded into `invalid` → after 3 attempts `failed` with the last reason, as the owner decided. OK. |
| No valid result after bounded attempts | AD-7, limit 3. OK. |
| Extraction unavailable → in-progress reaction | AD-7, set once. OK. |
| Internal service error → admin alert, never partial write | AD-10 covers the partial-write part. What happens to the *job* on an unexpected exception in a step is undefined (F4). |
| Unsupported content → "not accepted" reaction only | AD-2/AD-3: no job, offset advances. **Gap:** the spine does not say whether an oversize (>20 MB) or unconfirmed-size file counts as unsupported content, or what reaction it gets (F2). The telegram_core 🤔 "unknown forward type" reaction is not in the matrix, and the spine does not say whether it is kept. Low. |
| Not allowlisted / non-private → nothing | AD-3. OK. |

### Addendum lessons

| Lesson | Status |
| --- | --- |
| Chain traps (Kaufland PJ/branch match, fiscal URL date, bank-terminal date, ignored lines, Kaufland Card vs Štedite; Lidl POPUST footer, leading zeros; DM STORNO, branch segment; Müller bodovi, deposits as items) | AD-5 names the main traps; the rest belong to chain plug-ins (AD-6). OK. The Kaufland branch/receipt-number cross-check is a validation rule. AD-7's `invalid` list does not mention it, so whether a mismatch is `invalid` is up to each plug-in. Low. |
| Pricing: two discount modes | AD-5 | OK |
| Compare against printed fields, not price × qty | **Not stated.** It matters to every chain plug-in and to the consistency check. Low: add one line to AD-5. |
| Cash: record total, ignore change | Not stated. Low: same line in AD-5 or the settlement vocabulary (F3). |
| Dedup lesson | AD-8 | OK |
| Telegram: token safety, poll timeout +10 s, retries, gate, reactions never break processing, precedence, 20 MB both sides | AD-15 keeps them | OK |
| Offset atomic file | Replaced by AD-2 (memlog decision) | OK |
| EXIF, pixel cap | Untrusted-input convention | OK. What happens over the cap (downscale or reject, and the outcome) is not stated. Low. |
| Long-receipt slicing | Deferred | OK |
| Schema + temp 0 + **no thinking budget** | AD-4 has the schema and temp 0. **No thinking budget is dropped.** Gemini 3.x Flash thinks by default, which costs money and adds nondeterminism. Low: add to AD-4 or note as a config value. |
| Decimal money | Money convention | OK |
| PG roles: owner, no-login bundles, login per service | Deployment section: three roles | Partial. The permission-bundle roles are simplified away, which is acceptable at this scale. |
| Trigger grants (enum USAGE, sequences, DELETE on children) | "writer gets the grants the addendum's trigger lesson lists" | OK |

### Non-goals respected

No raw JSON input, categorization, analytics, multi-currency, legacy migration, manual correction, accuracy measurement or re-extraction appears. The "Backups not needed" item is consistent with the non-goals. OK.

### Memlog consistency

- All decisions and overrides in the memlog appear as ADs. No contradiction found.
- Memlog line 30 says "purchase local time also exposed with Europe/Zagreb offset" in the contract. The spine's Time convention only says contract timestamps are UTC `Z`. Low: either add the local-time field to the convention or drop it from the memlog assumption, so that the CAP-11 story does not have to guess.
- Memlog line 27 lists the states without `write_pending`. Line 35 adds it, and the spine has the final set. OK.

### AGENTS.md rules

- External services (Gemini, Telegram): the spec gives data-leaving-host, cost and downtime. OK.
- "Never read, import, or rely on another project's code": telegram_core is another project's code. The owner override covers it. AD-15 should cite the override, so that a later agent does not treat it as a rule breach. (Merged into the Low item above.)
- Exact pins: Stack lists versions. The stale pins in pyproject (pytest 8.3.5, ruff target py313) are flagged in the memlog for the baseline story. OK.
- Tests never touch production, and the `live` marker is required: the Tests convention covers fakes. PostgreSQL integration tests on "a disposable local instance" have no marker and no CI provisioning (F5).
- Process references are kept out of code: not applicable to the spine.

## 2. Rubric

### Divergence points fixed: well covered

Job store, offset ack, state ownership, pass split, transcribe-vs-compute, chain plug-in boundary, error classification, dedup key, own-write recognition, atomic write, effect order, Resolver feed shape, alert dedupe, concurrency model and single Telegram client are all fixed with enforceable rules. Each AD's Rule prevents its stated divergence. Most ADs can be checked mechanically: import-direction tests for the hexagon, a grep for chain names outside `domain/chains/`, unique constraints, a single-transaction write.

### Divergence points missed

**F1 — Gemini non-transient errors are unclassified (High).**
AD-7's `unavailable` class covers 429, 5xx, network and timeout. Its `invalid` class covers schema, unreadable fields and mismatch. It does not cover 400 (bad request, unsupported or too-large input), 401/403 (bad key, billing), a safety-blocked or empty response, or a 429 daily-quota exhaustion. Yet AD-13 names "Gemini auth failure" as an alert kind. One unit will treat 401 as `invalid`, which burns 3 attempts and fails every receipt during a key misconfiguration: lost receipts and false failure messages. Another will treat it as `unavailable`.
*Fix:* extend AD-7 with "401/403 and quota exhaustion → `unavailable` plus an AD-13 alert, and the job waits. 400 caused by the request content, a blocked response, or an empty candidate → `invalid`." State that SDK-level retries are disabled, or bounded so that AD-7's backoff is the only one.

**F2 — Where download happens relative to the offset commit; oversize files (Medium).**
The state diagram enters `received` on "file downloaded and saved", and AD-2 commits the offset with the job insert. So the `getFile` and download must complete inside the intake step, before the offset can advance. The spine does not say what a transient download failure does. It could block the batch, so the loop stalls and re-fetches the update, or skip the update, which loses the receipt. It also does not say what a >20 MB or size-unconfirmed file does. The matrix has no row for it.
*Fix:* either (a) insert the job with the Telegram `file_id` and make download the first job step, with transient errors as a wait and a permanent 4xx or oversize as a final outcome; or (b) keep download in intake, add a rule that a transient download failure leaves the offset unacknowledged and retries next loop, and map oversize or unconfirmed size explicitly to the unsupported-content outcome ("not accepted" reaction). (a) is simpler to reason about. Either way, state where the oversize file lands in the matrix.

**F3 — The shared domain receipt model is deferred (Medium).**
Deferred item "Column-level data model" leaves the *shape* to the storage story. That shape covers the line representation (printed, regular and effective amounts, quantity, unit), the discount-line handling and the settlement-kind vocabulary (card, cash, bonus points, coupon, deposit refund, signed). Five chain plug-ins (AD-6) all produce this model, and the consistency check consumes it. If chain stories run before or in parallel with storage, each plug-in invents its own fields and kinds.
*Fix:* move the domain receipt model (field names, settlement-kind enum, sign convention, "check against printed fields, not price × qty", "cash = total, ignore change") into the spine as a convention, or make it the explicit output of an early story that every chain story is `after`. Keep only the PostgreSQL column details deferred.

**F4 — Internal error inside a job step has no rule (Medium).**
The matrix row "Internal service error" says only that the admin gets an alert and that nothing is ever partially written. A bug (an unexpected exception in domain or adapter code) on one job is not defined. It could crash the loop and restart into the same job (a crash loop), be retried every loop (alert spam is prevented by AD-13, but the job is stuck and blocks others in the sequential loop), or consume an attempt.
*Fix:* add to AD-3 or AD-7: "An unexpected exception in a job step is caught at the job boundary, raises the `internal` alert kind (AD-13), leaves the job in its persisted state with backoff, and does not consume an attempt. The loop continues to the next due job." This is ~10 lines, in scale.

**F5 — Operational envelope: environment separation and the test DB (Medium).**
Deployment, roles, a single volume and CI are covered. Missing items:
- **Dev vs production bot.** Telegram allows one `getUpdates` consumer per token. A dev run with the production token takes updates from production. With AD-2 it acknowledges them into the dev SQLite file, so they are lost to production. Fix: require a separate dev bot token, dev DB or schema and dev SQLite volume, and have config refuse to start when the token or DB does not match the declared environment. This also enforces the AGENTS.md "live runs against production need owner approval" rule.
- **PostgreSQL integration tests.** "Disposable local instance" has no marker and no CI provisioning (service container), and AGENTS.md says unmarked tests do not touch the network. Fix: give them an `integration` marker, run them in CI against a service container, and keep CI and the local commands in sync.
- **Migrate on deploy.** Say how `migrate` runs on the server (`compose run --rm … migrate` with owner credentials supplied only to that run, never in the service env).
- Container restart policy and the container time zone are unstated. Low.

### Deferred items: divergence risk

| Item | Risk |
| --- | --- |
| Column-level data model | **Can diverge** (F3) |
| Backoff cap, poll timeout | None; config |
| Long-receipt slicing | None |
| resolver_v1 field list | None; single story, AD-12 fixes the shape. Resolve the local-time field (memlog line 30) there. |
| Prompt wording per chain | None; plug-in-local |
| PostgreSQL version | None. Identity columns need PG ≥ 10, which is realistic. |
| SQLite backups | None. The originals stay in Telegram, but only if the sender resends. Acceptable under "recovery = resend". |

### Overengineering check (~2 receipts/day)

Acceptable. Hexagonal with fakes is the minimum for "tests never touch network", the state machine is what CAP-9 requires, and AD-9 closes a real crash window cheaply. The versioned schema in AD-12 is the lightest form of an owned contract. Nothing should be removed. Watch two things in stories: the import-boundary enforcement for the hexagon (a single test, not a framework), and AD-14's shortened long-poll (a min() of two numbers, not a scheduler).

## Summary of findings

| # | Severity | Finding | Fix |
| --- | --- | --- | --- |
| F1 | High | Gemini 400/401/403/quota/blocked responses unclassified in AD-7 | Extend AD-7 classes; auth/quota → unavailable + alert; disable SDK retries |
| F2 | Medium | Download vs offset commit undefined; oversize file outcome missing | Download as first job step from `file_id`, or explicit stall rule; map oversize to "not accepted" |
| F3 | Medium | Domain receipt model / settlement vocabulary deferred but shared by 5 plug-ins | Fix the domain model as a convention, or as an early story the chain stories wait on |
| F4 | Medium | Unexpected exception in a job step has no rule | Catch at job boundary, alert, keep state, no attempt consumed, continue loop |
| F5 | Medium | No dev/prod separation (shared bot token loses updates); PG integration tests unmarked and unprovisioned in CI; migrate invocation | Separate dev bot/DB/volume enforced by config; `integration` marker + CI service; document `compose run migrate` |
| L | Low | No thinking budget dropped; printed-fields-not-price×qty and cash rule unstated; orphan-file sweep; AD-15 should cite owner override and spec update pending; local-time contract field; pixel-cap behavior; 🤔 reaction | One line each in the relevant AD or convention |
