# Next Prompt — wave 1c: close the deferred governance minors, starting with the shipped template defects

You are the single active implementation executor. The user already authorized
this scope; do not request authorization again. Read, in order:

1. `.ai/state/ROLE_POLICY.md` (review tiers);
2. the wave-1c stage authorization you create first — nothing under `scripts/`
   or `templates/` may be edited before it exists, and `path coverage` will say
   so if you skip it;
3. `docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` §2
   (publishing red lines) and §6 (the governance layer you are tightening).

## Task

Land the wave-1c list: the deferred minors from wave 1b's reviews plus the three
findings recorded in `docs/evidence/wave1b-facts.md` §7. Begin with the two
agent-facing template defects, because they are the ones this repository's own
agents read first: `templates/AGENTS.md` tells every harness to run
`git add -A && git commit && git push` two lines above "never commit secrets",
and `templates/handoff/NEXT_PROMPT.md` demands an "independent cross-family
review" that rule R5 forbids gating on and §2 forbids claiming.

Preserve unrelated edits. Do not revert anything already on `main`, and do not
restate wave 1b's numbers from memory — re-measure them on the tree you are on.

Owned files only:

- `templates/AGENTS.md`
- `templates/handoff/NEXT_PROMPT.md`
- `templates/SYNC_PROMPT.md` (only if it repeats the same two wordings)
- `scripts/ai_common.py`, `scripts/sync_verify.py`, `scripts/checkpoint.py`,
  `scripts/init_sync.py` — for the deferred minors, each with a red-first test
- `docs/evidence/wave1b-facts.md` (append; never rewrite a measured row)
- `.ai/**` (this repo's own install: its records, index, handoff and config)

## Current draft hashes — diagnostic only, not approved pins

- `templates/AGENTS.md`: `f3650fb59cd009a2…`
- `templates/SYNC_PROMPT.md`: `fe5b292c73c40b02…`
- `scripts/sync_verify.py`: `a2851b722eb3b71c…`

## Known hazards to inspect first

1. `.ai/scripts/sync_verify.py` is the copy that actually governs, and it is
   outside `protected_paths`. It matches `scripts/sync_verify.py` today; nothing
   detects it drifting after you edit the source. Add the drift check before you
   rely on a green in-repo verifier, and do not "fix" this by protecting
   `.ai/scripts/*` — that only protects a generated copy.
2. The coverage walk unions the editable lists of every accepted record in the
   window, so wave 1b's record keeps authorising its paths after this stage
   opens. Your own record must enumerate what it touches rather than widen a
   pattern: `fnmatch`'s `*` crosses `/`.
3. Three checks that look like content checks only test presence and line count:
   `required .ai/state/BLOCKERS.md`, `budget` on the handoff files, and
   `registered project checks`. An unfilled template passes all three. Fill them.
4. `480 passed, 5 skipped` and `20/24 checks passed, 4 skipped` are pinned in
   exact-count assertions. If your change moves a count, re-measure each test's
   own summary line — several edit the config, so they do not equal the baseline.

## Mandatory outcome

- Each wave-1c item has a test that fails against current `main` first, and the
  first-fail output is recorded in the PR description.
- The in-repo verifier stays green on this tree, and `sync_verify` output for a
  fresh install is quoted with its named SKIPs, never as "all green".
- Evidence to produce: the red-before-green log, the fresh-install and migrated
  counts, and the in-repo `25/25` line re-measured after your changes.
- Stop for exactly one independent review when done, by a reviewer with no
  shared context; describe it as "reviewed by a different model" only if a
  different model did it, and never as cross-family verification.

## Absolute stop boundary

No tag, no GitHub Release, no version bump, no push to `main`, no merge without
the user asking in terms. Never `git add -A`, never `git add -f` the gitignored
`.superpowers/`, never force-push, never rewrite published history, never commit
a held `.ai/runtime/WRITER_LOCK.json` — release the lock before staging. No
research-project content belongs in this repository at any point.
