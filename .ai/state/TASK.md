# Active Task

> Last updated: 2026-09-22 18:32 (+10:00)
> Updated by: qoder-cli (wave 1c, on two separate authorizations, both pending).

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
3. Open — one fresh-context pass on those two, then both records' `verdict` and the
   wave-1b record's `status: closed` in one commit. A clone cannot reach
   `.superpowers/`, so the PR body carries the red-at-base output inline.
4. Open — the 14 deferred wave-1b minors, the governing-copy drift check, the
   stale-grant rule, and the CHANGELOG entry for each release document touched.

## Explicitly not authorized

Any edit under `scripts/` or `templates/` without the release record; any tag,
Release, version bump, merge, or push to `main`; treating a wave-1b figure as this
tree's, now that `protected_paths` no longer registers the release face.

## Completion condition

Not met, and the target is stated as a command rather than a remembered number:
`python .ai/scripts/sync_verify.py` exits 0 with no FAILED line on this tree once
both records read `accepted` and the wave-1b record reads `status: closed`, with
W19's dry-run measurements reproduced on the way. The suite is green at
`516 passed, 5 skipped` (`python -m pytest tests/ -n 8 -o addopts= -q`) as of this
writing; re-run it, do not quote this line. What remains before this task can close
is review and acceptance, not more code.
