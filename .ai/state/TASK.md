# Active Task

> Last updated: 2026-09-23 01:09 (+10:00)
> Updated by: qoder-cli (wave 1d accepted; nothing merged).

## Standing state — do not rewrite

> Published text may only claim what was measured on the tree being read.
> No tag, no GitHub Release, no version bump without the user.
> `.superpowers/` is private reasoning; it is never force-added to git.
> Commits here carry the owner's GitHub identity from this repository's local
> git config, not their global school address.

## The one active task

Wave 1d, on branch `v2.1-wave1d-deferred-queue`: work the queue
`docs/evidence/wave1d-queue.md` — the deferred items wave 1c named and did not
fund — and publish the ones that cannot be resolved as unresolvable rather than as
rows. Two authorities, unchanged from wave 1c: `scripts/`, `templates/`, `tests/`,
`README.md`, `SKILL.md` and `reference.md` are the release face and answer to
`docs/release-authorizations/2026-09-22-wave1d-product-changes.md`; this
repository's own state answers to
`.ai/state/authorizations/2026-09-22-wave1d.md`. A runtime record does not certify
a shipped file, and `path coverage` no longer catches it when one tries.

## Role ownership

- **Executor:** qoder-cli controller (inline fixes, red-first per R4).
- **Reviewer:** two fresh-context subagent passes, the second pointed at the first
  one's closures. Findings and dispositions are rows W1-W9 and X1-X8 of
  `docs/evidence/wave1d-facts.md`; their model families are not readable from this
  host's logs, so the value recorded is `NOT_REPORTED` (R5 records, it does not
  gate; no sentence here says cross-family, and one of the dispatched passes died
  in the service and was not repeated).
- **User:** merge, any push to `main`, tag, Release, the global git config.

## Required work

1. Done — Q1: check 10, `governing copy`, comparing every `.ai/scripts/*.py` to its
   `scripts/` twin, with the name-collision case (D-7) and the undecidable tree
   (X1) split into two named SKIPs.
2. Done — Q2/Q3: the runtime window is guarded by the same `_base_conflicts` the
   release face uses, reading the records before it walks, and one predicate
   (`ai_common.is_full_sha`) answers "is this a commit id" for both commands.
3. Done — Q4/Q5/Q7: the two arms no test reached now have cases; the published
   verifier figures were re-measured; and the release-document entries wave 1c owed
   are in `CHANGELOG.md`, for wave 1c as well as wave 1d.
4. Done — acceptance: both wave-1d records carry `verdict: accepted`, wave 1c moved
   to `status: closed` in the same commit, and the verifier plus the full suite were
   re-run on that tree (V13 of `docs/evidence/wave1d-facts.md`).
5. The only work left on this branch is outward: push it and open its PR on top of
   #3/#4. Merge, tag and Release stay the user's, so after that push this file has
   no task in it.

## Explicitly not authorized

Any edit under `scripts/` or `templates/` without the release record; any tag,
Release, version bump, merge, or push to `main`; treating a wave-1b or wave-1c
figure as this tree's; editing an accepted record to satisfy a check it now
refuses — the answer to that is `status`, or a new stage.

## Completion condition

Stated as commands, not as numbers remembered here. With both wave-1d records
`accepted`, wave 1c `status: closed`: `python .ai/scripts/sync_verify.py` reports no
FAILED line, `path coverage` and `release authorization` each report every protected
touch covered, and `python -m pytest tests/ -n 8 -o addopts= -q` is green on the tree
you ran it on. The figures live in `docs/evidence/wave1d-facts.md` with the commit
each was measured at; if your tree is not that commit, re-run rather than quote.
