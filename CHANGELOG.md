# Changelog

## v2.1.0 — wave 1a (defect fixes), 2026-09-21

Wave 1a is a correctness release: it fixes defects in the v2.0 scripts rather
than adding governance. **27 defects were found, 26 were fixed in wave 1a, and
D14 is the only deferral, to wave 1b, because the glob-matching code it applies
to does not exist yet** (quoted from the spec's §5 table — `docs/superpowers/specs/
2026-09-21-cross-harness-sync-v2.1-design.md` — which is the only authority for
that number; no count in a commit message on this branch is quotable, and two of
them are known to be wrong: `664bd67` states 21 where 18 was measured, and
`ec505e3` carries inferred per-file counts).

Every number below was regenerated in one final run at one pinned revision, and
says so next to it.

| Figure | Value | Measured at |
|---|---|---|
| Test suite, `python -m pytest tests/ -n 8 -o addopts=""` | `324 passed, 3 skipped`, no warnings block — no elapsed time is quoted here, because the one that was (`24.92s`) reproduced on no second run: re-runs measured 20.4-21.7 s at that revision and 22-28 s since, so a single figure is host load, not evidence | `d5aee6e` (counts); lane Y re-measured `340 passed, 3 skipped in 28.25s` at `ef749b9` |
| Fresh install into an empty git repo, then `sync_verify.py` | `== 18/19 checks passed, 1 skipped ==`, rc 0 | `d5aee6e` |
| Same install cloned to a second absolute path | `== 18/19 checks passed, 1 skipped ==`, rc 0 | `d5aee6e` |
| Tracked text still claiming the caps count tokens | 0 files — the two template hits were swept after this row was measured | `c288a52` |

The one-line shape a reviewer sees on a default install never changes to
"everything passed": a default install registers no `extra_checks` and no
`secret_mirrors`, so it prints exactly one named `[SKIP]` forever. `rc == 0` is
not a verdict you can stop reading at.

### Breaking change — read before upgrading an existing install

Adopting wave 1a **without wave 1b's `--migrate` breaks both entry scripts on
every existing v2.0 install**: `checkpoint.py` and `sync_verify.py` now
hard-exit `2` with `[FAIL] install layout: ai_common.py is missing from
.ai/scripts/` unless `.ai/scripts/ai_common.py` is present, and v2.0 never
installed that file. The blast radius is wider than the plan originally said —
`checkpoint.py` too, not only `sync_verify.py` — and it includes private repos
the owner never re-runs the installer on.

The workaround that exists today is one command per install:

```bash
python scripts/init_sync.py <repo> --scripts-only
```

It refreshes `.ai/scripts/` and `.ai/protocol/VERSION`, creates the tracked
`.gitkeep` placeholders for the empty protocol directories, appends the
`.gitignore` exception that makes them addable, names every script it replaces
with a `NOTE replaced:` line, and touches no state file, no `sync_config.json`,
no template, no `AGENTS.md` and no `CLAUDE.md`. It needs no `--force` and leaves
`.gitignore` consistent — but it is a refresh, **not** a migration: no
`MIGRATION.json`, no window-start commit, no reconciliation of hand-customized
scripts, no authorization-directory discovery. Those are wave 1b's `--migrate`.

### What changed (user-visible)

**The install and its upgrade path.** `--scripts-only` now does what its `--help`
always claimed. `--force` on `init_sync.py` refreshes only files still untouched
since their template and prints `KEEP (edited)` for files the caller wrote in;
`--clobber` overwrites those too; `--no-agents-block` drops the `AGENTS.md`
budget row instead of leaving the run permanently red; `--force` is refused with
`VERSION MISMATCH: …` (exit 1) when the installed `protocol/VERSION` is newer or
unparseable, so a stale skill checkout can no longer downgrade an install.
`.gitignore` is updated append-only, never re-blocked, and on the
`--scripts-only` path as well as the full one.

**Versions are compared, not assumed.** `.ai/protocol/VERSION` is stamped with
the installer's own `PROTOCOL_VERSION` (now `2.1.0`, previously a v2.0 stamp on
a v2.1 tree), the two are compared as parsed tuples, and the verifier reports
`protocol version readable`. The stamp is the *protocol* version, not the
skill's release version, and the two are not conflated anywhere in this release.

**Budgets are line budgets.** The check was `check_token_budgets` and the code
counts `splitlines()`; it is now `check_line_budgets` and the docs say line
budgets. Every printed check name (`budget <path>`, `FAILED:` lines) stayed
byte-identical — the rename is display and documentation only. A line is a weak
proxy for tokens in CJK state files, which this protocol permits; real token
accounting is a wave-2 measurement, not a wave-1 claim.

**Installs that cannot work are refused, loudly.** A linked git worktree, a
`.ai` reached through a symlink or a Windows junction, an install below the
repository root, and a layout git cannot describe are refused at exit 1 with a
message naming the `--force --reason` escape and the split it costs. The refusal
covers the state writers, not just `--lock`: `--handoff` and the bare
checkpoint classify the checkout before writing a byte. This is a documented
boundary, not support — and it bounds the multi-machine promise, because the
lock is a tracked file that only coordinates writers sharing one checkout's
history.

**The lock stopped being a suggestion in the places it claimed to be one.**
`--unlock` requires `--agent` (exit 2 without it, exit 1 if the lock is not
yours); `--force` requires `--reason` (exit 2 without it) and records the
takeover in the tracked `WRITER_LOCK.json`; `--force` without `--reason` no
longer depends on which branch the layout check happens to take. An
unparseable or conflict-marked lock record is HELD, never free, and is never
rewritten — `--force --discard-lock` is the only way to abandon one. What did
**not** change: the state-writing commands (`--handoff`, bare `checkpoint.py`)
still print a named `WARN …` and continue at exit 0 when another agent holds the
lock. They accept a concurrent writer; they do not reject one, and no copy of
this documentation claims otherwise.

**The verifier's silence is now distinguishable from its verdicts.** A config
that cannot be read is a FAIL, not a shrug and a default. `extra_checks` that
exit 0 having written nothing are a named `SKIP`, not a PASS. A secret mirror
present on one side only is a FAIL naming the missing side; both absent is the
named `SKIP` it should have been. `install layout` is booked as a `[PASS]` line
when it passes, so a report that never mentions the gate did not run it.
`checkpoint.py --validate` answers from the same required-file list and the same
floor the verifier uses, instead of a private seven-entry copy that omitted
`ROLE_POLICY.md`.

**Output that survives a Windows console.** Shipped output is ASCII-safe:
`checkpoint.py` emits a localized timezone name only when it is ASCII and the
UTC offset otherwise; subprocess plumbing captures bytes and decodes with
`surrogateescape` instead of trusting the console code page; `os.replace` and a
per-writer temp name replaced the two Windows-specific file races.

**Two promises were removed rather than fixed.** A milestone log named in four
shipped places and created by none (defect D25) — a file nothing writes invites
exactly the parallel-MEMORY-file failure this protocol forbids — is gone from
the shipped texts, and `DECISIONS` + `DECISIONS_INDEX` remain the L2 layer.
And the unmettable gate — the instruction to run `sync_verify.py` until the
report read clean, in the quickstart, in the managed block installed into every
`AGENTS.md`, in `--prime`, and in `.ai/SYNC_PROMPT.md` — is replaced everywhere
with the gate that can actually be met: no `FAILED:` line, a named `[SKIP]`
acceptable, silence not.

### What is deliberately deferred to wave 1b

- **`--migrate`** (§8): the migration record, the window-start commit,
  customized-script reconciliation, authorization-directory discovery. Until
  then the breaking change above stands.
- **D14** — `fnmatch` case/separator normalisation. Deferred because the
  glob-matching code it applies to (`protected_paths`) does not exist yet;
  fixing a matcher nobody calls would be a number, not a fix.
- **The `protected_paths` coverage walk** (§6.2) and `checkpoint.py
  --review-prompt`. This is the headline scope of the project — path-scoped
  independent review where CODEOWNERS and Gerrit structurally cannot exist — and
  it is *not in this release*. Do not read the release notes as if it were.
- **Cross-machine verification.** The two-clone acceptance in
  `tests/test_second_machine.py` varies git author identity, HOME, and a
  registered `secret_mirrors` pair across a push/pull on one host; it is not
  cross-machine verification. Cross-machine handoff (a second host, a second
  locale and code page, real credentials, non-default `core.autocrlf`) has not
  been measured in wave 1a. Committer identity, note, is pinned to one fixture
  identity by the harness, so even the author-side half is author-only.
- **The symlink half of D15** cannot be exercised on this host without symlink
  privilege: the refusal is read from code and exercised for `linked-worktree`
  only. Stated as a coverage hole, not as a pass.
- **Real token measurement**, npm packaging, CI, and the `.agents/skills/`
  layout (spec §3 non-goals).

### What this release does not claim

`sync_verify.py` detects **omission, not fabrication**. It proves a required
state file, a line budget, a secret-ignore rule or a tracked placeholder is
missing; those go red on every run until fixed, and that part is enforced. It
cannot prove a review happened, that a recorded agent identity is honest, or that
a handoff describes work that occurred. The role policy, the T1/T2/T3 review
tiers and writer discipline are **recorded** — installed, existence-checked, and
nothing more. A future coverage walk over declared paths would still be bounded
by repository history availability, and would still be unable to bind a recorded
name to a model invocation without a server; that limit is the design stance,
not a missing feature.
