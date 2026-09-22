# Active Task

> Last updated: 2026-09-23 02:31 (+10:00)
> Updated by: cursor (PR stack #3/#4/#5 merged; no new code funded).

## Standing state — do not rewrite

> Published text may only claim what was measured on the tree being read.
> No tag, no GitHub Release, no version bump without the user.
> `.superpowers/` is private reasoning; it is never force-added to git.
> Commits here carry the owner's GitHub identity from this repository's local
> git config, not their global school address.

## The one active task

None. Wave 1d on `v2.1-wave1d-deferred-queue` is merged to `main` as PR #5
(after #3 and #4). The owner-authorized merge stack is done. Until the user funds
a void row or asks for tag/Release, do not open a new implementation stage.

## Role ownership

- **Executor:** none active for product code.
- **Reviewer:** n/a for this merge close-out (T1 docs/state only).
- **User:** tag, Release, version bump, and which void rows (if any) to fund.

## Required work

1. Done — merge PR #3 (`v2.1-wave1c-governance-defects` → `main`).
2. Done — retarget and merge PR #4 (`v2.1-wave1c-release-gate` → `main`).
3. Done — retarget and merge PR #5 (`v2.1-wave1d-deferred-queue` → `main`).
4. Done — pull `main` tip `22f460d` and re-run verify + suite on that tree.
5. Stop — no void row, tag, or Release without a fresh user ask in terms.

## Explicitly not authorized

Any edit under `scripts/` or `templates/` without a release record; any tag,
Release, version bump; treating a pre-merge figure as this tree's; editing an
accepted record to satisfy a check it now refuses — the answer is `status`, or
a new stage; coding Q6/Q8–Q12/Q14/Q15 without funding.

## Completion condition

Stated as commands. On `main` at the tip you claim: `python .ai/scripts/sync_verify.py`
reports no FAILED line; quote coverage and suite figures only from that run (or
from `docs/evidence/` rows that name the same commit). Pre-merge totals in
`wave1d-facts.md` are not this tip's.
