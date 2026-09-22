# Active Task

> Last updated: 2026-09-22 19:55 (+10:00)
> Updated by: qoder-cli (wave 1c, both authorizations accepted).

## Standing state — do not rewrite

> Published text may only claim what was measured on the tree being read.
> No tag, no GitHub Release, no version bump without the user.
> `.superpowers/` is private reasoning; it is never force-added to git.
> Commits here carry the owner's GitHub identity from this repository's local
> git config, not their global school address.

## The one active task

Wave 1c, on branch `v2.1-wave1c-release-gate` (stacked on
`v2.1-wave1c-governance-defects`): retire the defects the dogfood
found, each under its own authority. `scripts/` and `templates/` are the release
face and answer to
`docs/release-authorizations/2026-09-22-wave1c-product-changes.md`; this
repository's own state answers to
`.ai/state/authorizations/2026-09-22-wave1c.md`. A runtime record does not certify
a shipped file — that separation is itself one of this stage's products.

## Role ownership

- **Executor:** qoder-cli controller (inline fixes, red-first per R4).
- **Reviewer:** fresh-context subagents with no shared history; findings and
  dispositions are in `docs/evidence/wave1c-facts.md` (W13, W15, W17, W18), and
  their model families were not readable from this host's logs (W14). Cross-family
  where a second family is reachable, otherwise same-family with no shared context,
  recorded in those words (R3 as amended 2026-09-22; R5 records, it does not gate).
- **User:** merge, any push to `main`, tag, Release, the global git config.

## Required work

1. Done — R3/R5 reconciliation across the policy and the four documents that
   restated it; `git add -A` removed from the shipped instructions; installer-owned
   slots filled by `init_sync.py` and residue reported by `sync_verify.py`;
   `tests/test_lane_1c_governance.py` shown red against `0bc4d7f` first.
2. Done — `release authorization` gates the shipped surface on a record in
   `docs/release-authorizations/`, and `status` is now separate from `verdict` so a
   finished stage stops being able to un-authorize its own commits (W19).
3. Done — three fresh-context passes on those two (W17, W22, W24), then both
   records' `verdict` and the wave-1b record's `status: closed` in one commit. A
   clone cannot reach `.superpowers/`, so the PR bodies carry red-at-base output.
4. Open — wave 1d, on branch `v2.1-wave1d-deferred-queue`: the queue in
   `docs/evidence/wave1d-queue.md` (Q1-Q13), whose rows Q1-Q5 and Q7 are this
   stage. The "14 wave-1b minors" this file used to name were unresolvable ids;
   the queue says so and what remains of them.

## Explicitly not authorized

Any edit under `scripts/` or `templates/` without the release record; any tag,
Release, version bump, merge, or push to `main`; treating a wave-1b figure as this
tree's, now that `protected_paths` no longer registers the release face.

## Completion condition

Met, and stated as a command rather than a remembered number: with both records
`accepted` and the wave-1b record `status: closed`, `python .ai/scripts/sync_verify.py`
exits 0 with no FAILED line and no `[SKIP]`, and `pytest tests/ -n 8 -o addopts= -q`
is green. Re-run them; a total copied out of this file describes its own tree. The suite is green at
`516 passed, 5 skipped` (`python -m pytest tests/ -n 8 -o addopts= -q`) as of this
writing; re-run it, do not quote this line. What remains before this task can close
is review and acceptance, not more code.
