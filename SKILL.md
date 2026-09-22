---
name: cross-harness-sync
description: Install and operate a file+git-based shared-state protocol so multiple AI coding harnesses (Claude Code, Codex, Kimi, GLM, Cursor, …) and multiple machines can pick up one repo's work mid-task. Uses an .ai/ directory (CURRENT/TASK/BLOCKERS startup reads, handoff templates, decision log + index, layered line budgets, advisory writer lock, verify script). Use when the user wants cross-harness sync, agent handoff, session continuity across machines, multi-agent shared memory without a server, or mentions .ai/state, AGENTS.md canonical instructions, or "agent A stops, agent B resumes".
---

# Cross-Harness Sync

A zero-infrastructure protocol for sharing narrative work state across AI coding
harnesses and machines: plain markdown in `.ai/`, git as the transport, one
verify script that mechanically checks the things that can be checked from
bytes in the repo. No server, no database, no daemon.

Design stance: **dumb files + git + one verify script beat a runtime service**
when the goals are auditability (everything is a diffable markdown file in the
repo) and harness-agnosticism (every tool can read files and run git).

## What this proves, and what it does not

`sync_verify.py` detects **omission, not fabrication**. It can prove a required
state file, a line budget, a secret-ignore rule, or a tracked placeholder is
**missing** — those are facts about files, and they go red on every run until
fixed. It cannot prove a review happened, that a recorded agent identity is
honest, or that a handoff describes what actually occurred: nothing in this
protocol binds a recorded name to an event that did or did not happen.

So the two registers are different on purpose:

- **Enforced (mechanically checked every run):** line budgets, required files
  and the required-file floor, secrets git-ignored, secret-mirror key sets, the
  protocol-version stamp, and the project's own `extra_checks`.
- **Recorded, not enforced:** the role policy, the T1/T2/T3 review tiers, the
  writer lock, and writer discipline generally. `WRITER_LOCK.json` is a tracked
  advisory record. `--lock` refuses (exit 1) while another agent holds an
  unexpired lock; the state-writing commands (`--handoff`, bare `checkpoint.py`)
  **WARN by name and continue at exit 0**. That asymmetry is the design, not a
  gap: hard enforcement needs a server, which this protocol refuses to require.
- **Counted locally, and last-writer-wins:** `--status` prints
  `Checkpoints : N` from machine-local, untracked `runtime/STATUS.json`, and two
  concurrent checkpoints race one read-modify-write with no arbitration. Measured
  on one host: 8 concurrent checkpoint writers left `checkpoint_count` at 1 or 2
  every time, each exiting 0, so 6-7 of the 8 updates were lost. Read the number
  as a per-machine heartbeat, never as a ledger of how many checkpoints happened.

The honest differentiator is **path-scoped independent review in settings where
CODEOWNERS and Gerrit structurally cannot exist**: no forge admin rights (forked
patches, self-hosted forges, private repos whose branch protection you do not
own), and authors that are LLM agents with no forge identity to be a code owner
of. The coverage walk that acts on that — `protected_paths` in config, the
`git log` pass over it, an accepted authorization's `## Editable files` list as
the covering record — ships in wave 1b as the `path coverage` check. It makes
omission **verifiable**: a skipped or forgotten review stays in history for
anyone who re-runs the verifier. It cannot detect a fabricated record, because
nothing binds a recorded name to an actual model invocation, and it halts with
a named FAIL rather than a certificate when history is shallow or git cannot
answer. See `CHANGELOG.md`.

## When to use

- Setting up a repo so Claude Code / Codex / Kimi / any future harness can
  resume each other's work, on one machine or across machines.
- Mid-task handoffs between agents, or session continuity across context
  compaction.
- Multi-agent work where exactly one writer should hold the pen at a time.

Not for: concurrent many-agent swarms all writing at once — this is a sequential
handoff protocol, and on overlap it warns by name rather than arbitrating; nor
for semantic/vector memory retrieval (this is narrative state, not a knowledge
base).

## Install into a repo

The target must be a git repository (`git init` first): git is the transport, and
outside a repo the secret checks cannot answer and report `[FAIL]`.

```bash
python scripts/init_sync.py /path/to/repo
```

Then fill in the `<placeholder>`s that describe the project's work (its red lines
and the state skeletons). `init_sync.py` resolves the slots only it can know —
project name, remote URL and commit identity in `AGENTS.md`, the Adopted line in
`ROLE_POLICY.md` — and the `unfilled template slots` check reports any it could
not. Declare project-specific checks in `.ai/sync_config.json`, run
`python .ai/scripts/sync_verify.py` until `FAILED:` is absent and every line
reads `[PASS]` or a named `[SKIP]`, then commit and push. A default install
registers no project checks and declares no protected paths, so it ends
`== 21/26 checks passed, 5 skipped ==` at exit 0 (measured on the tree this file
ships in). The
five skips are `registered project checks`, `path coverage`
(`SKIP(no-protected-paths)`), `release authorization`
(`SKIP(no-release-paths)`), `pin violation` (`SKIP(no-authorizations)`) and
`role policy integrity` (`SKIP(no-sha-pinned)`), and each names which reason it
took. The same install after `python scripts/init_sync.py <repo> --migrate`
reads `== 22/26 checks passed, 4 skipped ==`. Neither figure is a failure to fix
and neither is green — nothing in this protocol can be green, only named.
`rc == 0` is never sufficient; read the lines.

`init_sync.py` is idempotent: existing files it did not write are kept
(`KEEP (edited)`), `--force` refreshes those still untouched since their
template, `--clobber` overwrites those too, and an existing `AGENTS.md` gets a
marker-delimited managed block (`BEGIN/END CROSS-HARNESS-SYNC`) replaced in
place on re-runs.

**Upgrading from a v2.0 install.** Wave 1a alone **broke both entry scripts on
every existing v2.0 install**: `checkpoint.py` and `sync_verify.py` hard-exit
`2` unless `.ai/scripts/ai_common.py` is present, and v2.0 never installed that
file. Wave 1b's `--migrate` is the upgrade:

```bash
python scripts/init_sync.py /path/to/repo --migrate
```

It sets the governance config keys, pins the SHA-256 of `ROLE_POLICY.md`,
records the window-start commit, installs the authorization index and template,
writes `.ai/protocol/MIGRATION.json` plus a `MIGRATION.md` journal naming what a
revert cannot undo, and commits the result. It refuses at exit 2 writing nothing
when git cannot be asked what HEAD is, or while another agent holds the writer
lock, and it takes its own `init-sync-migrate` lock while it runs; a second run
verifies the recorded state and writes nothing. Where `.ai/scripts/` is not in
HEAD, the migration preserves the installed scripts and emits `.new` sidecars
with a `WARN` rather than clobbering them. `--scripts-only` stays available as
the refresh-only path — no `MIGRATION.json`, no window-start commit, no
reconciliation of customized files — so prefer `--migrate`.

**Install boundaries (refused, on purpose).** The scripts locate `.ai/` from
their own path and refuse to work where that answer is not
`<repo root>/.ai/scripts/`: a linked git worktree, a `.ai` reached through a
symlink or a Windows junction, an install below the repository root, or a layout
git cannot describe. Each refusal prints the `--force --reason` escape and the
split it costs you. This matters for the "multiple machines" promise: the lock is
a tracked file, so it only coordinates writers who share one checkout's history —
two worktrees of one repo are not two machines.

## Daily protocol (what to tell every agent)

**Session start** — read exactly three files, nothing else:

1. `git pull --ff-only` (the remote is shared memory; never force-push)
2. `.ai/state/CURRENT.md` → `TASK.md` → `BLOCKERS.md`
3. Shortcut: `python .ai/scripts/checkpoint.py --prime` prints lock status +
   the read list. If `.ai/PRIME.md` exists its content **replaces** that output
   wholesale, so a curated file can turn the session-start lock signal into
   silence; keep it in sync with this protocol by hand.

**Before writing state** — one active writer at a time:

```bash
python .ai/scripts/checkpoint.py --lock --agent <harness-name> --reason <task-id>
```

A conflicting unexpired lock means STOP and report (advisory lock). `--force`
takes the pen over and requires `--reason "<why>"`: `--force` without `--reason`
is a usage error and exits 2 whatever the checkout layout turns out to be. The
reason is recorded in the tracked `WRITER_LOCK.json` as well as the handoff,
because the handoff is only as durable as the next commit. And note what the lock
does *not* do: `--handoff` and the bare checkpoint warn by name and continue at
exit 0 while someone else holds it.

**Writing state** — the rules that keep it working:

- `CURRENT.md` updates only at semantic boundaries, ≤ 60 lines.
- New decision = ONE line in `DECISIONS_INDEX.md` + ≤ 15 lines in `DECISIONS.md`.
- Handoff = `.ai/handoff/LATEST.md`, fixed 6 sections (Done / Not done /
  Evidence pointers / Warnings / Next step / Must-read list), ≤ 80 lines.
- One stage = ONE authorization `.md` in `.ai/state/authorizations/` (scope +
  editable files + pinned hashes + stop boundary), plus a fenced governance
  block carrying `tier`, `executor`, `reviewer` and `verdict`; `verdict:
  accepted` is what makes the record live, and two live records are a FAIL. That
  directory is the home the coverage walk reads. Template:
  `.ai/templates/AUTHORIZATION.md`.
- Never pin frequently-changing state files as authorization baselines.
- Layered reading: L0 (the three files) at startup; L1 (the task's
  authorization + named docs) when executing; L2 archives are retrieval-only
  via `DECISIONS_INDEX.md` or grep — never read in full.
- Budgets are **line** budgets. A line is a weak proxy for tokens in CJK state
  files, which this protocol permits; real token accounting is a wave-2
  measurement, not a wave-1 claim.
- Review tiers T1/T2/T3 and hard rules (reviewer ≠ author, cross-family review,
  red-before-green): `.ai/state/ROLE_POLICY.md`. Recorded, not enforced — the
  verifier proves the file is present and that it digests to the
  `role_policy_sha256` pinned in `.ai/sync_config.json`, so editing the
  governance document means a config diff a human reads; it never gates on model
  family (rule R5).

**Close out** — always, in order:

1. `python .ai/scripts/sync_verify.py` → no `FAILED:` line; a named `[SKIP]` is
   acceptable, silence is not
2. Update `CURRENT.md` + `LATEST.md` (and `--handoff` to archive the old one)
3. `python .ai/scripts/checkpoint.py --unlock --agent <name>` (the name is
   required; bare `--unlock` is a usage error at exit 2)
4. `git add <the paths this stage owns> && git commit && git push` with the project's human identity

## Scripts

Three scripts are installed into `.ai/scripts/`; a fourth drives the install
from the skill repo.

- `scripts/ai_common.py` — shared primitives: bytes-safe subprocess plumbing,
  `.ai/` root resolution, checkout-layout classification, stdio guard, the
  shared required-file list and floor, version parse/compare. Installed next to
  the other two. `checkpoint.py` and `sync_verify.py` both hard-exit 2 with
  `[FAIL] install layout: ai_common.py is missing from .ai/scripts/` if it is
  absent, so copying "just the two scripts" is a broken install, not a leaner one.
- `scripts/checkpoint.py` — `--status`, `--prime`, `--validate`, `--handoff`,
  `--lock` / `--unlock` (TTL advisory lock), `--review-prompt`, `--agent`,
  `--ttl`, `--reason`.
  Overrides: `--force` takes a conflicting lock over (always with `--reason`,
  exit 2 without it) and is the only escape from a refused checkout layout;
  `--discard-lock`, with `--force`, abandons a lock record that cannot be parsed
  (an unreadable record is HELD, never free). `--review-prompt` prints exactly
  the active authorization, the diff and the verify output — the reviewer's read
  scope in one command, under the banners `== REVIEW PROMPT: AUTHORIZATION ==`,
  `== REVIEW PROMPT: DIFF ==`, `== REVIEW PROMPT: VERIFY ==`. Mechanical only;
  never writes semantic content. `--validate` answers from the same required-file list the
  verifier uses, plus the floor.
- `scripts/sync_verify.py` — config-driven health check, in this order:
  `install layout`, `git usable` / `git repository`, `config readable`,
  `registered project checks`, `required <file>` (+ `required-file floor`),
  `protocol version readable` (a stamp that disagrees with the installed scripts
  prints the FAIL `protocol version matches installed scripts` **instead of** that
  PASS, so a healthy run and a skewed run each show one protocol-version line),
  `budget <file>` (+ `cap opt-out <file>`),
  `budget DECISIONS active entries`, `secret ignored: <file>`,
  `secret mirror <a> vs <b>`, then the governance checks — `path coverage`,
  `pin violation`, `role policy integrity`, `swarm boundary` — and then
  `extra_checks`. Check 0 is booked as a PASS,
  not left silent: a report that never mentions `install layout` did not run the
  gate, and a report that mentions it did.
- `scripts/init_sync.py` — scaffold the `.ai/` tree into a repo, from the skill
  checkout. `--force` refreshes files still untouched since their template and
  prints `KEEP (edited)` for those the caller wrote in; `--clobber` overwrites
  those too; `--scripts-only` is the upgrade path (see above) and implies
  `--force` because it can only reach the installer's own files;
  `--no-agents-block` leaves `AGENTS.md` alone and drops its budget line;
  `--migrate` is the governance upgrade described under "Upgrading from a v2.0
  install", and exits 2 with nothing written when it cannot ask git what HEAD
  is.

All scripts locate `.ai/` from their own path and refuse the layouts named under
**Install boundaries** above.

## Exit codes

The same integer does not mean the same thing across commands, so here is the
table once. `rc == 0` is never a certificate: it means "everything that ran
passed", not "nothing was skipped".

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `sync_verify.py` | every check that ran passed (named `[SKIP]`s allowed) | any `[FAIL]`, or a run in which not one check produced a `[PASS]` | no verdict: `ai_common.py` missing, install root unresolvable, or config unusable — an unreadable file, a non-object, or any `malformed:` refusal (wrong-typed key, a path that escapes the checkout, a `budgets` value over 10000 lines, `decisions_max_active_entries` over 2000 entries, a timeout over 86400 s). An out-of-range cap therefore stops the whole run; it does not degrade to one `[SKIP]` |
| `checkpoint.py --validate` | every listed file present and non-empty | a file missing or empty, or an empty declared list | no verdict: an unreadable required file or config |
| `checkpoint.py --lock` / `--unlock` | acquired / released | conflict with another holder, refused checkout layout, a record that cannot be parsed, or a lock that is not yours to release | usage error: `--force` without `--reason`, `--unlock` without `--agent` |
| `checkpoint.py --handoff` / bare / `--status` / `--prime` | done (a held lock owned by someone else is a `WARN`, still exit 0) | refused checkout layout; or the tracked lock record is unparseable (treated as HELD) | no verdict: `ai_common.py` missing or root unresolvable |
| `init_sync.py` | install/refresh completed as described | a step reported `ERROR`, or a newer/unparseable `protocol/VERSION` refused the run (`VERSION MISMATCH`) | usage error, e.g. a target that is not a directory |

## New-agent onboarding

Give every newly connected agent the contents of `.ai/SYNC_PROMPT.md` as their
first prompt. It encodes the whole protocol in six numbered steps.

## Additional resources

- Detailed schemas, budgets, lock semantics, hook snippets (SessionStart /
  PreCompact), sync_config.json reference, and the provenance of each borrowed
  mechanism: [reference.md](reference.md)
- What changed in this release, what is deferred, and the measured numbers:
  [CHANGELOG.md](CHANGELOG.md)
- File templates copied by `init_sync.py`: [templates/](templates/)
