# Active Task

> Last updated: 2026-09-22 12:18 (+10:00)
> Updated by: qoder-cli (wave 1c started, under two separate authorizations).

## Standing state — do not rewrite

> Published text may only claim what was measured on the tree being read.
> No tag, no GitHub Release, no version bump without the user.
> `.superpowers/` is private reasoning; it is never force-added to git.
> Commits here carry the owner's GitHub identity from this repository's local
> git config, not their global school address.

## The one active task

Wave 1c, on branch `v2.1-wave1c-governance-defects`: retire the defects the dogfood
found, each under its own authority. `scripts/` and `templates/` are the release
face and answer to
`docs/release-authorizations/2026-09-22-wave1c-product-changes.md`; this
repository's own state answers to
`.ai/state/authorizations/2026-09-22-wave1c.md`. A runtime record does not certify
a shipped file — that separation is itself one of this stage's products.

## Role ownership

- **Executor:** qoder-cli controller (inline fixes, red-first per R4).
- **Reviewer:** none has run on this increment yet. Cross-family where a second
  family is reachable, otherwise same-family with no shared context, recorded in
  those words (R3 as amended 2026-09-22; R5 records, it does not gate).
- **User:** merge, any push to `main`, tag, Release, the global git config.

## Required work

1. Done — R3/R5 reconciliation across the policy and the four documents that
   restated it; `git add -A` removed from the shipped instructions; installer-owned
   slots filled by `init_sync.py` and residue reported by `sync_verify.py`;
   `tests/test_lane_1c_governance.py` (9 cases) shown red against `0bc4d7f` first.
2. Open — push, open PR #3 with the red-at-base output inline (a clone cannot reach
   `.superpowers/`), then the review, then the record's `verdict`.
3. Open — the 14 deferred wave-1b minors, the governing-copy drift check, the
   stale-grant rule, and the CHANGELOG entry for each release document touched.

## Explicitly not authorized

Any edit under `scripts/` or `templates/` without the release record; any tag,
Release, version bump, merge, or push to `main`; treating a wave-1b figure as this
tree's, now that `protected_paths` no longer registers the release face and
`path coverage` reads 8 rather than 33.

## Completion condition

Not met. `python .ai/scripts/sync_verify.py` reads `== 26/26 checks passed ==`,
rc 0, no `[SKIP]` on this tree, and the suite reports `489 passed, 5 skipped` —
both re-measured, recorded in `docs/evidence/wave1c-facts.md`. What remains before
this task can close is publication and one review, not more code.
