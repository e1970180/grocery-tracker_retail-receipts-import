---
type: migration
title: Fold the pre-release spec and move breakdowns into tickets/ folders
status: done
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

Approved by the owner 2026-11-18 (both steps).

Migration 1 (fold and live-path items):

- Pass: no `spec-<slug>/` folder holding `spec-<slug>.md` remains. The initiative holds R1 to R11 (CAP-1 to CAP-11), the Constraints and Boundaries, `receipt-outcomes.md` beside it as a References line, and one `.memlog.md` with the spec's entries. `CAP-` appears only inside Requirements parentheses, `.memlog.md` and this plan.
- Pass: `migrate_v6.py --fold-specs` reported no unresolved companion and no problems, and rewrote 16 store files.
- Pass: `_bmad/custom/config.toml` names `active_initiative`, and `core.output_folder` resolves to `_bmad-output`.
- Pass: the backup holds every pre-migration file and is ignored by git.

Migration 2:

- Pass: no initiative or epic folder holds `tickets.toml`, an epic folder, a leaf file or a plan directly.
- Pass: every file in the backup is in the store at its old or new path. The only exception is the folded `spec-receipts-import.md`, removed by migration 1.
- Pass: `tickets.py status` exits 0 for both initiatives: `initiative-receipts-import-mvp` has 25 entries (24 done, 1 dropped), `initiative-multi-country-import` has 5 entries (all done) and epic 2 with no entries.
- Pass: the rewritten `_bmad-output/...` paths resolve. Dead before the migration, left unchanged: `_bmad-output/.../architecture-receipts-import/...` (a prose ellipsis) and `../../../docs/contracts/resolver_v1.md` in `epic-receipts-pipeline/tickets/tickets.toml` (the contract is now `receipt_feed_v1.md`).
- Pass: moved files keep their history (`git log --follow` reaches the pre-move commits). No commit includes a backup.
- Pass: `.tickets-folder-migration-backup-20261118-1218/` holds the output folder and `_bmad/custom/` as they were.
- Deviation: the path rewrites and the moves went into one commit rather than two. History still follows each file.

No references to the old paths exist outside the store and `_bmad/`.
