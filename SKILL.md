---
name: cross-harness-sync
description: Install and operate a file+git-based shared-state protocol so multiple AI coding harnesses (Claude Code, Codex, Kimi, GLM, Cursor, …) and multiple machines can pick up one repo's work mid-task. Uses an .ai/ directory (CURRENT/TASK/BLOCKERS startup reads, handoff templates, decision log + index, layered token budgets, advisory writer lock, verify script). Use when the user wants cross-harness sync, agent handoff, session continuity across machines, multi-agent shared memory without a server, or mentions .ai/state, AGENTS.md canonical instructions, or "agent A stops, agent B resumes".
---

# Cross-Harness Sync

A zero-infrastructure protocol for sharing narrative work state across AI coding
harnesses and machines: plain markdown in `.ai/`, git as the transport, one
verify script as enforcement. No server, no database, no daemon.

Design stance: **dumb files + git + one verify script beat a runtime service**
when the goals are auditability (everything is a diffable markdown file in the
repo) and harness-agnosticism (every tool can read files and run git).

## When to use

- Setting up a repo so Claude Code / Codex / Kimi / any future harness can
  resume each other's work, on one machine or across machines.
- Mid-task handoffs between agents, or session continuity across context
  compaction.
- Multi-agent work where exactly one writer should hold the pen at a time.

Not for: concurrent many-agent swarms writing simultaneously (the single-writer
rule is the point), or semantic/vector memory retrieval (this is narrative
state, not a knowledge base).

## Install into a repo

```bash
python scripts/init_sync.py /path/to/repo
```

Then fill in every `<placeholder>` (remote URL, commit identity, project red
lines), declare project-specific checks in `.ai/sync_config.json`, run
`python .ai/scripts/sync_verify.py` until green, commit, push.

`init_sync.py` is idempotent: existing files are skipped (use `--force` to
overwrite), and an existing `AGENTS.md` gets a marker-delimited managed block
(`BEGIN/END CROSS-HARNESS-SYNC`) replaced in place on re-runs.

## Daily protocol (what to tell every agent)

**Session start** — read exactly three files, nothing else:

1. `git pull --ff-only` (the remote is shared memory; never force-push)
2. `.ai/state/CURRENT.md` → `TASK.md` → `BLOCKERS.md`
3. Shortcut: `python .ai/scripts/checkpoint.py --prime` prints lock status +
   the read list (project-overridable via `.ai/PRIME.md`)

**Before writing state** — one active writer at a time:

```bash
python .ai/scripts/checkpoint.py --lock --agent <harness-name> --reason <task-id>
```

A conflicting unexpired lock means STOP and report (advisory lock; `--force`
exists but the reason must be recorded in the handoff).

**Writing state** — the rules that keep it working:

- `CURRENT.md` updates only at semantic boundaries, ≤ 60 lines.
- New decision = ONE line in `DECISIONS_INDEX.md` + ≤ 15 lines in `DECISIONS.md`.
- Handoff = `.ai/handoff/LATEST.md`, fixed 6 sections (Done / Not done /
  Evidence pointers / Warnings / Next step / Must-read list), ≤ 80 lines.
- One stage = ONE authorization `.md` (scope + editable files + pinned hashes +
  stop boundary). Template: `.ai/templates/AUTHORIZATION.md`.
- Never pin frequently-changing state files as authorization baselines.
- Layered reading: L0 (the three files) at startup; L1 (the task's
  authorization + named docs) when executing; L2 archives are retrieval-only
  via `DECISIONS_INDEX.md` or grep — never read in full.
- Review tiers T1/T2/T3 and hard rules (reviewer ≠ author, cross-family review,
  red-before-green): `.ai/state/ROLE_POLICY.md`.

**Close out** — always, in order:

1. `python .ai/scripts/sync_verify.py` → must be all green
2. Update `CURRENT.md` + `LATEST.md` (and `--handoff` to archive the old one)
3. `python .ai/scripts/checkpoint.py --unlock --agent <name>`
4. `git add -A && git commit && git push` with the project's human identity

## Scripts

- `scripts/checkpoint.py` — `--status`, `--prime`, `--lock/--unlock` (TTL
  advisory lock), `--handoff`, `--validate`, bare run = bump checkpoint counter.
  Mechanical only; never writes semantic content.
- `scripts/sync_verify.py` — config-driven health check: required files, token
  budgets, decision-log cap, secrets git-ignored, secret-mirror key sets,
  project `extra_checks`. Exit 1 on any FAIL.
- `scripts/init_sync.py` — scaffold the whole `.ai/` tree into a repo.

All scripts locate `.ai/` relative to themselves; no parameters to get wrong.

## New-agent onboarding

Give every newly connected agent the contents of `.ai/SYNC_PROMPT.md` as their
first prompt. It encodes the whole protocol in six numbered steps.

## Additional resources

- Detailed schemas, budgets, lock semantics, hook snippets (SessionStart /
  PreCompact), sync_config.json reference, and the provenance of each borrowed
  mechanism: [reference.md](reference.md)
- File templates copied by `init_sync.py`: [templates/](templates/)
