# cross-harness-sync

A zero-infrastructure protocol that lets multiple AI coding harnesses
(Claude Code, Codex, Kimi, GLM, Cursor, …) and multiple machines pick up one
repo's work mid-task — plain markdown in `.ai/`, git as the transport, one
verify script as enforcement. No server, no database, no daemon.

**Design stance:** dumb files + git + one verify script beat a runtime service
when the goals are auditability (everything is a diffable markdown file in the
repo) and harness-agnosticism (every tool can read files and run git).

## Install

```bash
python scripts/init_sync.py /path/to/your/repo
```

Then fill in every `<placeholder>` (remote URL, commit identity, project red
lines), declare project-specific checks in `.ai/sync_config.json`, and:

```bash
python .ai/scripts/sync_verify.py   # must be all green
git add -A && git commit && git push
```

`init_sync.py` is idempotent: existing files are skipped (`--force` to
overwrite); a pre-existing `AGENTS.md` gets a marker-delimited managed block
instead of being replaced.

## What you get

```
.ai/
├── SYNC_PROMPT.md        # first prompt for every newly joined agent
├── sync_config.json      # budgets, secrets, project-specific extra_checks
├── state/                # CURRENT.md / TASK.md / BLOCKERS.md  (L0 startup reads)
│                         # ROLE_POLICY.md · DECISIONS.md + DECISIONS_INDEX.md
├── handoff/              # LATEST.md (6-section template) · NEXT_PROMPT.md
├── protocol/VERSION
├── runtime/              # machine-local; WRITER_LOCK.json is tracked (travels via git)
└── scripts/              # checkpoint.py · sync_verify.py
```

## Daily protocol

- **Session start**: `git pull --ff-only`, read `.ai/state/CURRENT.md`,
  `TASK.md`, `BLOCKERS.md` — nothing else. Shortcut:
  `python .ai/scripts/checkpoint.py --prime` (project-overridable via
  `.ai/PRIME.md`).
- **Before writing state**: one active writer at a time —
  `checkpoint.py --lock --agent <harness-name>` (advisory TTL lock; conflicts
  are reported, never silently overridden).
- **Writing state**: CURRENT.md ≤ 60 lines, handoff ≤ 80 lines (fixed 6
  sections), one decision = one index line + ≤ 15 lines, one stage = one
  authorization file. Budgets are enforced by `sync_verify.py`, not discipline.
- **Close out**: `sync_verify.py` green → update state → `--unlock` →
  commit + push.

Review tiers (T1 ordinary / T2 protected / T3 irreversible gate), cross-family
review, red-before-green, and the single-writer rule live in
`.ai/state/ROLE_POLICY.md`. Details, hook snippets, and configuration:
[reference.md](reference.md).

## Why not Beads / Memory Bank / agent-mail?

- **Cline Memory Bank** reads ALL memory files every session; this uses layered
  L0/L1/L2 budgets with a retrieval-only archive layer.
- **Beads** is a task/issue graph with a versioned DB; this tracks *narrative
  session state* (where the work stands and why) with zero dependencies.
- **mcp_agent_mail** coordinates concurrent agents via a running MCP server;
  this is for sequential handoff where the audit trail must live in git.

Mechanisms gratefully borrowed from all three (and from superpowers and
agent-handoff-skill) are documented in [reference.md](reference.md#provenance-of-borrowed-mechanisms).

## License

MIT — see [LICENSE](LICENSE).
