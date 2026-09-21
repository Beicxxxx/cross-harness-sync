# Sync Prompt — give to every agent newly joining this project

Before any work, in order:

1. `git pull --ff-only` (remote: <REMOTE URL>). If pull reports diverged
   history: back up uncommitted changes, STOP, and report — never force-push,
   never rewrite history.
2. Read the root `AGENTS.md` — the single canonical instruction file for all
   harnesses (`CLAUDE.md` is only a pointer to it). Follow its L0/L1/L2 layered
   reading rules and line budgets.
3. Startup reads are exactly three files: `.ai/state/CURRENT.md`, `TASK.md`,
   `BLOCKERS.md`. Do NOT read DECISIONS / handoff archives in full;
   retrieve single entries via `DECISIONS_INDEX.md` or grep.
   Shortcut: `python .ai/scripts/checkpoint.py --prime` shows lock status and
   the read list.
4. Before writing any state file, acquire the writer lock:
   `python .ai/scripts/checkpoint.py --lock --agent <your-harness-name>`.
   If another agent holds an unexpired lock, STOP and report.
5. At close-out: run `python .ai/scripts/sync_verify.py` (no `FAILED:` line; a
   named `[SKIP]` is fine, silence is not), update CURRENT.md / LATEST.md,
   release the lock
   (`--unlock --agent <your-harness-name>`), then commit and push as
   `<NAME> <<EMAIL>>`. Never commit secrets.

Standing red lines: <one line, e.g. "Gate X = DO NOT ADVANCE; only the user
lifts it."> The single active task is in `TASK.md`.
