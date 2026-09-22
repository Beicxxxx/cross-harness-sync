# Release authorization — wave 1c product changes

> Issued 2026-09-22 by the user, who approved starting wave 1c and then ruled on
> the R3/R5 conflict when it was raised. Recorded by qoder-cli (controller).
> Base commit: `0bc4d7f` (main, after PR #2).
>
> **This file is the release face of the change.** `.ai/state/authorizations/`
> is the repository's own runtime record of how *it* works, written by the
> protocol as a user of itself; it has no standing over what ships. The two are
> kept apart on purpose: a stage that installs and runs the protocol cannot also
> be the authority that publishes it.

## What ships

Six files under `scripts/` and `templates/` — the surface a downstream project
installs. Each line is why it is wrong today, not what the diff does.

| File | Defect in the shipped product |
|---|---|
| `templates/ROLE_POLICY.md` | R3 makes a different model family a requirement at T2/T3 while R5 says family is recorded and never gates. A harness that can load one family is told on three sides it cannot do protected work at all. |
| `templates/TASK.md`, `templates/CURRENT.md`, `templates/handoff/NEXT_PROMPT.md` | The same unconditional requirement is restated in the files agents fill in, so every install inherits the contradiction. |
| `templates/AGENTS.md` | Orders `git add -A && git commit && git push` two lines above its own rule against committing secrets — an instruction that ships the bug it warns about. |
| `scripts/ai_common.py`, `scripts/sync_verify.py` | `required <file>` asks whether a state file exists and `budget <file>` asks how long it is, so a verbatim template copy answers both and prints PASSes. Nothing detected a ROLE_POLICY whose authorship line still read `by <who>` — and that file is digest-pinned. |
| `scripts/init_sync.py` | Copied `<NAME> <<EMAIL>>`, `<PROJECT NAME>`, `<REMOTE URL>` and the Adopted line verbatim, then told the user to fill in "every placeholder" — including the ones only the installer could know. |

## The ruling behind R3

Cross-family stays the preference; a same-family reviewer with no shared context
is accepted where a second family is unreachable, and the record must say
`same-family`. What the protocol can enforce is the description, not the
availability: writing the word without the split is exactly the failure this
clause exists to make impossible.

## What is deliberately not in here

Section 7 of `templates/ROLE_POLICY.md` asks the author for project boundaries the
installer cannot know. `init_sync.py` now drops that section and says it did,
rather than shipping an instruction as if it were an answer — it does not invent
boundaries for someone else's repository.

## Evidence

- `tests/test_lane_1c_governance.py` — one test per defect, red against the base
  tree first. Red output: `.superpowers/sdd/2026-09-22-wave1c/evidence/lane-1c-red-at-base.log`
  (`8 failed, 1 passed`; the one pass is the CONTROL case, which can only be green
  at base because the check it guards did not exist yet — its base-green proves
  nothing, and it earns its place by staying green afterwards). Private to this machine, so
  the PR body carries the same output inline.
- The suite's own totals, re-measured on the tree this table describes and
  reported in the PR rather than here.

## Editable files

Enumerated one path per bullet, no wildcards. The bullet parser reads each entry as
an `fnmatch` pattern and `*` crosses `/`, so one `*` here would authorise every
future commit to the release face for good, by the union rule that keeps an accepted
record in force after its stage closes. A comma-separated bullet is not two patterns:
this list is read one entry per line, so a packed line silently covers nothing.

- `scripts/ai_common.py`
- `scripts/sync_verify.py`
- `scripts/init_sync.py`
- `templates/AGENTS.md`
- `templates/CURRENT.md`
- `templates/ROLE_POLICY.md`
- `templates/TASK.md`
- `templates/handoff/NEXT_PROMPT.md`
- `README.md`
- `SKILL.md`
- `reference.md`
- `templates/sync_config.json`

## Governance

```governance
tier: T2
executor: qoder-cli/controller
reviewer: qoder-cli general-purpose subagent, separate context
verdict: pending
red_before_green: true
user_authorized: true
```

The reviewer's model family and tier could not be read from this host's logs (one
segment, every model field `qfmodel`, no per-agent attribution), so no cross-family
attestation is made here — R5 records `NOT_REPORTED` rather than guessing. `verdict`
stays `pending` while the gate's own findings are open; see W17.

## Boundary

No tag, no Release, no version bump. `SKILL.md` and `reference.md` document two
of these behaviours (the placeholder instruction and the review tier), so they
are part of this change, not a later one.

## Amended after the review (W8, W13)

`fill_installer_slots()` first read `git config user.name`, which resolves local ->
global. A repository created by `git init` carries no `[user]` block, so on a
machine whose global identity is an institutional address the installer wrote that
address into a stranger's `AGENTS.md` and reported the slot as resolved — the very
thing this project exists to prevent, reintroduced by the fix for it. It now reads
`--local` only, and treats a missing local value as missing. The hermetic test HOME
could not see this, which is why the first cut passed its own suite;
`test_c3_a_global_identity_is_not_written_into_a_strangers_repo` injects
`GIT_CONFIG_GLOBAL` so the fallback cannot return unreported.
