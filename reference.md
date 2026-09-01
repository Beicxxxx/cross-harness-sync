# Cross-Harness Sync — Reference

Detailed schemas, rationale, and configuration. Read this only when installing,
customizing, or debugging the protocol — not during normal operation.

## Directory layout (created by `init_sync.py`)

```
.ai/
├── SYNC_PROMPT.md            # first prompt for every newly joined agent
├── PRIME.md                  # optional: overrides `checkpoint.py --prime` output
├── sync_config.json          # budgets, secrets, project extra_checks
├── state/                    # the shared memory
│   ├── CURRENT.md            # ≤60 lines, single source of truth for progress
│   ├── TASK.md               # the ONE active task + completion condition
│   ├── BLOCKERS.md           # active blocker + binding disclosures
│   ├── ROLE_POLICY.md        # T1/T2/T3 review tiers, hard rules R1–R7
│   ├── DECISIONS.md          # ≤20 active entries, ≤15 lines each
│   ├── DECISIONS_INDEX.md    # ≤110 lines, one line per decision
│   └── archive/              # L2: retrieval-only history
├── handoff/
│   ├── LATEST.md             # ≤80 lines, fixed 6 sections
│   ├── NEXT_PROMPT.md        # ≤100 lines, next executor's starting prompt
│   └── archive/              # timestamped past handoffs
├── templates/
│   └── AUTHORIZATION.md      # one stage = one authorization file
├── protocol/VERSION          # protocol semver
├── runtime/                  # machine-local, gitignored EXCEPT the lock
│   ├── STATUS.json           # written only by checkpoint.py
│   └── WRITER_LOCK.json      # advisory lock; tracked so it travels via git
└── scripts/
    ├── checkpoint.py
    └── sync_verify.py
```

## File schemas

**CURRENT.md** — header (timestamp + updater), at-a-glance table, one-sentence
objective, active authorization pointer (path + SHA-256), workstream table,
stage-history pointer, standing-rule pointers. Link, never restate. Update only
at semantic boundaries.

**TASK.md** — standing invariants ("do not rewrite"), the one active task, role
ownership (executor / reviewer / user-only decisions), required work,
**explicitly-not-authorized list** (this is what stops scope creep across a
handoff), completion condition verifiable by a stranger.

**BLOCKERS.md** — the one active blocker + who unblocks it; "not blockers"
list; **binding disclosures** (caveats that must survive compaction and land in
any final write-up); standing constraints.

**LATEST.md (handoff)** — exactly six sections: Done / Not done / Evidence
pointers / Warnings / Next step / Must-read list. Background lives in
CURRENT.md; the handoff links to it. If the next step's precondition is a user
decision, say so and stop.

**DECISIONS.md + DECISIONS_INDEX.md** — index-first: new decision = one index
line (date | title | location) + ≤15 lines in the active pages. Old entries
move to `state/archive/DECISIONS_<yyyymm>_full.md` and their index rows flip to
`archive`. Before reversing a past decision: locate via the index, read ONLY
that single archived entry.

**AUTHORIZATION.md (per stage)** — issued by the user; scope, editable-file
list, pinned baselines (SHA-256), roles (executor + cross-family reviewer),
completion condition, absolute stop boundary. One stage = ONE file. Never pin
CURRENT/TASK/BLOCKERS/LATEST — frequently-changing state files are not pinning
targets (pinning them once caused a stall over a routine state edit).

## Token budgets (defaults in sync_config.json)

| File | Cap | Why |
|---|---|---|
| `AGENTS.md` | 65 lines | canonical instructions, auto-read by every harness |
| `.ai/state/CURRENT.md` | 60 | L0 must stay cheap |
| `.ai/handoff/LATEST.md` | 80 | handoff is skimmed every session |
| `.ai/handoff/NEXT_PROMPT.md` | 100 | executor prompt |
| `.ai/state/DECISIONS_INDEX.md` | 110 | one line per decision |
| `DECISIONS.md` | 20 active `##` entries | archive the rest |

Budgets are enforced by `sync_verify.py`, not by discipline. A file over
budget must be slimmed before commit.

## Advisory writer lock

- Acquire: `checkpoint.py --lock --agent <name> [--ttl 14400] [--reason <id>]`.
  Refuses (exit 1) if another agent holds an unexpired lock; `--force`
  overrides but the reason must be recorded in the handoff.
- Release: `--unlock` marks `released_at` — the lock file is **never deleted**,
  so git history is the audit trail (pattern borrowed from mcp_agent_mail's
  persisted lease artifacts).
- `WRITER_LOCK.json` is the ONE tracked file under `runtime/` (`.gitignore`
  excepts it) so the lock travels across machines with `git pull`. All other
  runtime files are machine-local.
- The lock is advisory: it coordinates honest agents; it does not prevent a
  misbehaving one from writing. That is deliberate — hard enforcement needs a
  server, which this protocol refuses to require.

## Session-start injection and compaction survival

`checkpoint.py --prime` prints lock status + the exact L0 read list in
~20 lines. If `.ai/PRIME.md` exists, its content replaces the generated
output entirely (curated override; pattern from Beads' `.beads/PRIME.md`).

Context compaction is the enemy of protocol discipline. Two defenses:

1. **PreCompact reminder** — before compaction, flush state to files.
2. **Post-compaction re-injection** — re-run `--prime` after compaction;
   startup-only injection is insufficient (a session that compacts over its
   first turn loses the bootstrap).

Claude Code hook sketch (`.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command",
      "command": "python .ai/scripts/checkpoint.py --prime"}]}],
    "PreCompact": [{"hooks": [{"type": "command",
      "command": "echo 'Update .ai/state and .ai/handoff/LATEST.md before compaction if task state changed.'"}]}]
  }
}
```

Hook safety contract (borrowed from agent-handoff-skill): hooks always exit 0,
never block, never write state files — hooks remind, the agent writes.

## sync_config.json reference

```json
{
  "budgets": { "<repo-relative path>": <max lines> },
  "decisions_max_active_entries": 20,
  "decisions_file": ".ai/state/DECISIONS.md",
  "secret_files": [".env"],
  "secret_mirrors": [[".env", ".claude/.env"]],
  "extra_checks": [{ "name": "freeze X", "cmd": ["python", "scripts/freeze_x.py", "--verify"] }]
}
```

- `secret_files`: each must be git-ignored (`git check-ignore` must succeed).
- `secret_mirrors`: pairs of env files whose KEY NAMES must be identical sets
  (e.g. a canonical `.env` and a harness-specific mirror).
- `extra_checks`: project-specific verifiers (freeze manifests, drift checks).
  PASS iff exit code 0. This is where a project's scientific freezes plug in.

## Role policy (summary — full text in templates/ROLE_POLICY.md)

- **T1 ordinary**: no LLM review. **T2 protected** (freeze/hash/authorization/
  fail-closed paths): one cross-family reviewer, diff + hashes + targeted
  regressions only. **T3 irreversible gate**: independent reviewer + explicit
  user authorization. Ambiguous → higher tier.
- Hard rules: R1 single active writer; R2 reviewer ≠ author; R3 cross-family
  review; R4 red-before-green (regression test must FAIL on unfixed code first);
  R5 record harness+model+effort, unknown = `NOT_REPORTED`, never a re-gate;
  R6 metered spend is a user decision; R7 one model, one function per task.
- Reviewer read scope is hard: the authorization, the diff, the verify output.
  Reading full history "for safety" is out of scope.
- Match model class to failure mode, not task size: silent failure modes
  (a wrong answer looks right) → frontier model at top effort; loud failure
  modes (tests/hashes catch it) → any competent cheap model.

## Language and timestamps

State files may be written in whatever language the team reads fastest, but
pick ONE per repo and record the choice in AGENTS.md. Timestamps: human-readable
with explicit timezone and UTC offset, e.g. `2026-08-31 21:21:22
(Australia/Sydney, UTC+10:00)` — harnesses get timezones wrong often enough
that the offset must be written out.

## Provenance of borrowed mechanisms

| Mechanism | Source |
|---|---|
| `--prime` session injector + `PRIME.md` override | Beads (`bd prime`, `.beads/PRIME.md`) |
| Advisory lease with TTL, `reason` field, persisted-after-release audit artifact | mcp_agent_mail file reservations |
| Advisory-only hook contract (remind, never block/write), PreCompact flush reminder | agent-handoff-skill (WeirdSky924) |
| Re-injection after compaction; startup-only injection is insufficient | superpowers bootstrap skill |
| Marker-delimited managed block in AGENTS.md for idempotent re-runs | Beads (`BEGIN/END … INTEGRATION`) |
| Explicit update-trigger rules ("update state when X happens") | Cline Memory Bank trigger rules |
| "Forbid the rival pattern" (one canonical state location; agents must not invent parallel TODO/MEMORY files) | Beads AGENTS.md snippet |

## Known failure modes this protocol has already survived

- Pinning a fast-changing state file as an authorization baseline → stall over
  a routine state edit. Rule: state files are never pinning targets.
- A one-line fail-open guard classified as "ordinary fix" → shipped defect.
  Rule: the T1/T2 boundary is a list, not a judgement call.
- Reviewer re-running the executor's full suite → wasted spend. Rule: reviewer
  checks diff + hashes + targeted regressions only.
- A reviewer-of-the-reviewer layer that only ever confirmed prior verdicts →
  removed. The mitigation for an uncalibrated reviewer is calibration, not
  another LLM pass.
