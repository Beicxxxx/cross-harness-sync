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
├── protocol/VERSION          # PROTOCOL version (a semver stamp), not the skill's release version
├── runtime/                  # machine-local, gitignored EXCEPT the lock
│   ├── STATUS.json           # written only by checkpoint.py
│   └── WRITER_LOCK.json      # advisory lock; tracked so it travels via git
└── scripts/
    ├── ai_common.py          # shared primitives; both entry scripts hard-exit 2 without it
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

## Line budgets (defaults in sync_config.json)

A line is a weak proxy for tokens in CJK state files, which this protocol
permits; real token accounting is a wave-2 measurement, not a wave-1 claim.

| File | Cap | Why |
|---|---|---|
| `AGENTS.md` | 65 lines — 81 after `init_sync.py` appends its 16-line managed block; the installer edits `.ai/sync_config.json` to pay for the block it added, and `--no-agents-block` deletes the row instead | canonical instructions, auto-read by every harness |
| `.ai/state/CURRENT.md` | 60 | L0 must stay cheap |
| `.ai/handoff/LATEST.md` | 80 | handoff is skimmed every session |
| `.ai/handoff/NEXT_PROMPT.md` | 100 | executor prompt |
| `.ai/state/DECISIONS_INDEX.md` | 110 | one line per decision |
| `DECISIONS.md` | 20 active `##` entries | archive the rest |

Budgets are enforced by `sync_verify.py`, not by discipline: an over-budget or
uncapped file goes red on every run, and a file over budget must be slimmed
before commit. That is enforcement of the mechanically decidable — omission. It
cannot detect fabrication: nothing here binds a name to an event that did not
happen.

The cap has to be capable of failing, so a value no file can reach is refused as
a config error rather than accepted: a `budgets` value above 10,000 lines, a
`decisions_max_active_entries` above 2,000, or a timeout above 86,400 seconds
aborts the **whole run at exit 2 with no verdict**, and it is not one `[SKIP]`
line. `null` is the only documented deliberate decline — it prints
`[SKIP] cap opt-out <file>` and keeps the rest of the run answering. A project
that legitimately wants a budget no human would read is expected to name the
decline with `null`, not to write a huge number.

## Protocol version

`.ai/protocol/VERSION` is the **protocol** version, not the skill's release
version, and wave 1a does not treat the two as the same number. `init_sync.py`
compares the stamp with its own `PROTOCOL_VERSION` before writing anything: a
newer or unparseable stamp is refused with `VERSION MISMATCH: …` and exit 1,
including under `--force`/`--clobber`; an older one is reported as an upgrade.
`sync_verify.py` prints `protocol version readable` for the file it finds, and
that PASS now carries a second witness: when the stamp and the protocol the
installed `.ai/scripts/` implement disagree, it prints the FAIL
`protocol version matches installed scripts` instead, naming which side is ahead
and what to re-run.
Wave 1b's `--migrate` is meant to read that stamp rather than assume it.

## Advisory writer lock

- Acquire: `checkpoint.py --lock --agent <name> [--ttl 14400] [--reason <id>]`.
  Refuses (exit 1) if another agent holds an unexpired lock, if the checkout is a
  linked worktree, a symlinked/junctioned `.ai`, not at the repository root, or a
  layout git cannot describe, and if the tracked record cannot be parsed — an
  unreadable record is HELD, never free. `--force` overrides, and always requires
  `--reason "<why>"`: `--force` without it is a usage error, exit 2. `--force`
  takes a lock OVER; only `--force --discard-lock` abandons an unparseable
  record, and neither resolves a git conflict. Both the reason and any
  `forced_layout` kind are written into the record so the next machine can see
  the takeover.
- Release: `--unlock --agent <name>` marks `released_at` — the name is required
  against a live or expired record (exit 2 without it, exit 1 if it is not
  yours) — and the lock file is **never deleted**, so git history is the audit
  trail (pattern borrowed from mcp_agent_mail's persisted lease artifacts).
  Wave 1a put the same layout gate on the release that `--lock` already had: a
  linked worktree, a relocated `.ai`, an install below the repository root, or a
  layout git cannot describe is refused at exit 1. Without it, releasing inside a
  worktree exited 0 and wrote `released_at` into THAT copy's tracked record while
  the checkout that took the pen kept holding its own, so the next machine pulled
  a "released" that was never released. `--force --reason` still overrides, and
  says plainly that the release lands in this worktree's record only — the other
  machine cannot see it.
- What the lock does not do: `--handoff`, the bare checkpoint, `--status` and
  `--prime` do not stop for another holder. The state-writing commands print a
  named `WARN <command>: the writer lock is held by <name> …` and continue at
  exit 0 (`--force` over a refused layout adds a second WARN, and says plainly
  that nothing records the split there). Concurrent many-agent writers are out of
  scope, not rejected.
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

- `budgets`: `{"<repo-relative path>": <max lines>}`, and a key that escapes the
  checkout is refused (`malformed: config key 'budgets' keys must be
  repo-relative paths inside the checkout`). Values must be line-count integers
  or `null`; above the 10,000-line ceiling the run aborts at exit 2 (see **Line
  budgets**). The same shape layer rejects a non-repo-relative `decisions_file`,
  an out-of-range `decisions_max_active_entries` / `check_timeout` /
  `git_check_timeout`, and a non-integer budgets value: four `malformed:`
  message families, all of them exit-2 "the verifier cannot answer at all", none
  of them a per-line SKIP.
- `secret_files`: each must be git-ignored (`git check-ignore` must succeed).
- `secret_mirrors`: pairs of env files whose KEY NAMES must be identical sets
  (e.g. a canonical `.env` and a harness-specific mirror). Presence is checked
  too, and it is three-valued: both sides absent is a named
  `SKIP(no mirrored secrets on this machine)` (mirrored secrets are git-ignored,
  so a second machine legitimately has none); exactly one side present is a
  `FAIL` naming the missing side, because a one-sided mirror is local drift or a
  wrong path in the config, not a per-machine difference; both present must
  agree on key names.
- `extra_checks`: project-specific verifiers (freeze manifests, drift checks).
  PASS iff the command exits 0 AND wrote something: an exit 0 with zero bytes on
  both streams is a named `SKIP`, and a timeout or an unlaunchable command is a
  FAIL. `rc == 0` is never sufficient. Both timeouts are configurable
  (`check_timeout`, `git_check_timeout`). This is where a project's scientific
  freezes plug in.

## Role policy (summary — full text in templates/ROLE_POLICY.md)

**Recorded, not enforced.** The policy is installed as a required file, so the
verifier can prove it is *missing*; nothing in wave 1a can prove a review
happened, who performed it, or which model family they belonged to. The
`protected_paths` coverage walk that would name uncovered commits is wave 1b.

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
that the offset must be written out. The **offset is the authority**; the zone
name is opportunistic. `checkpoint.py` prints a zone name only when it is ASCII,
because on a localized Windows host `tzname()` returns the OS's translated name
(in a zh locale, a string that mojibakes a legacy console) and an abbreviation
like `CST` is ambiguous anyway; there the line reads `(UTC+10:00)` and nothing
is lost.

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
