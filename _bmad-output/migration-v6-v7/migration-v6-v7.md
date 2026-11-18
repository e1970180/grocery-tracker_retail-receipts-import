---
type: migration
title: Fold the pre-release spec and move breakdowns into tickets/ folders
status: draft
created: 2026-11-18
---

# Migration plan

Project already on v7 (initiative folders, `tickets.toml`, `active_initiative` set). Two `bmod-method` migrations apply, run in order on branch `worktree-bmad-agent-po-rule`.

## Answers

| Question | Answer | Reason |
|---|---|---|
| Run the migrations? | Both, in order (migration-1, then migration-2) | Owner, 2026-11-18: `bmad-agent-po` refuses the current tree layout. |
| Planning/implementation content elsewhere? | None | All content is under `_bmad-output/`. |
| Workspace (separate store repository)? | No | Store stays in the project repository. |

## Backups

- `.v6-v7-migration-backup-20261118-1218/` (`_bmad/` and `_bmad-output/`), never committed.
- `.tickets-folder-migration-backup-20261118-1218/` (`_bmad-output/` and `_bmad/custom/`), never committed.

Both verified byte-for-byte against the source (89 output files).

## Migration 1 (6 to 7): pre-release spec fold only

- `initiative-receipts-import-mvp/spec-receipts-import/` folds into `initiative-receipts-import-mvp/initiative-receipts-import-mvp.md` via `migrate_v6.py --fold-specs`:
  - 11 `CAP-<n>` become Requirements lines `R<n>` (the initiative has no Requirements yet), also mapped in its `tickets.toml` and children;
  - constraints to Constraints, non-goals to Boundaries, assumptions and open questions to Notes;
  - `.memlog.md` entries appended to the initiative's `.memlog.md`;
  - companion `receipt-outcomes.md` moves beside the initiative file as a References line;
  - store references to the folder are rewritten; the folder is removed.
- No other v6 signal: no `epics.md`, `sprint-status.yaml`, v6 story files or dated folders.
- Config: `active_initiative` already set (`_bmad/custom/config.toml`: `initiative-receipts-import-mvp`; personal `config.user.toml`: `initiative-multi-country-import`). No change.

## Migration 2 (7 preview to 7): breakdowns into tickets/

| Folder | Moves into its `tickets/` |
|---|---|
| `initiative-multi-country-import/` | `tickets.toml`, `epic-multi-country-pipeline/`, `epic-shared-chains-contract/` |
| `initiative-receipts-import-mvp/` | `tickets.toml`, `epic-receipts-pipeline/` |
| `epic-shared-chains-contract/` | `tickets.toml`, 1 leaf file, 5 plans |
| `epic-receipts-pipeline/` | `tickets.toml`, 4 leaf files (2 bugs, 2 stories), 26 plans |
| `epic-multi-country-pipeline/` | nothing besides its epic file (gets an empty `tickets/` only if needed) |

Stay in place: initiative and epic files, `.memlog.md`, `deferred-work.md`, retrospectives, run folders (`architecture-*`, `brief-*`, `research-*`), `backlog/`, `party-mode/`.

Path rewrites: live references to moved paths in 17 store files (54 occurrences, mostly `deferred-work.md`, leaf files, the initiative and epic files). Archived and historical text inside `.memlog.md` is left as written. No `_bmad/custom/` override names a moved path. No reference outside the store and `_bmad/`.

Commits: one per step, on the branch; backups never staged; no push of the migration commits until the owner reviews.

## Checklist results

_Filled in after the run._
