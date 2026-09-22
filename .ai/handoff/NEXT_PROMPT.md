# Next Prompt — wave 1c: write its record before touching shipped code

You are the single active implementation executor. Read, in order:
`.ai/state/ROLE_POLICY.md` (tiers, R1–R7); `.ai/state/CURRENT.md` §5 and
`.ai/state/BLOCKERS.md` (binding disclosures); spec §2 (publishing red lines)
and §6 under `docs/superpowers/specs/`.

## The dogfood stage is published — wave 1c is the only work left

[PR #2](https://github.com/Beicxxxx/cross-harness-sync/pull/2) is OPEN against
`main`, 27 files, every commit authored as `Beicxxxx`. Prove it rather than
trusting this file: `git ls-remote --heads origin | grep dogfood` prints the live
tip, and `gh pr view 2 --json state,additions,commits` answers for the rest.

`main` still has no `.ai/`, because merging is the user's call. A reader of the
default branch gets the protocol without the install until they say otherwise, so
quote the PR, not `main`, for anything §10.D measured.

Two things that cost the last session its turn, now settled:

- `git push` fails in a non-interactive shell: Git Credential Manager tries to
  prompt, `/dev/tty` does not exist, and it dies with `could not read Username
  for 'https://github.com'`. A hang there is input that cannot arrive, not speed.
  This authenticates per command and persists nothing:
  `GIT_TERMINAL_PROMPT=0 git -c credential.helper='!gh auth git-credential' push`
- This repository's **local** `user.name`/`user.email` are now the owner's GitHub
  identity, because their global config carries a school address that must not
  represent this project. Leave both alone: never touch the global config, and do
  not plan to clean the 78 already-published `main` commits that do carry it —
  that needs a force-push to published history, which is refused by default.

## Task 1 — wave 1c: write its record before touching shipped code

The deferred list: wave-1b minors (M-3, M-4, M-5, M-7..M-14,
`checkpoint._review_is_sha` accepting uppercase, `_migration_commit`'s
post-commit listing check fixed without a test, 15 duplicated `_load` helpers in
5 signatures) plus the three findings in `docs/evidence/wave1b-facts.md` §7.
Start with the two template defects, both verified by line number:
`templates/AGENTS.md:48` says `git add -A && git commit && git push` two lines
above "never commit secrets"; `templates/handoff/NEXT_PROMPT.md:31` demands an
"independent cross-family review", which R5 forbids gating on and §2 forbids
claiming. `scripts/` and `templates/` are protected, so editing them without an
accepted record prints `[FAIL] path coverage: … uncovered of … protected touches`.

## Known hazards to inspect first

1. `.ai/scripts/*.py` is the copy that actually governs and sits **outside**
   `protected_paths`. Byte-identical to `scripts/*.py` today, digest-checked;
   nothing detects drift, so a green `sync_verify` is not evidence the installed
   verifier matches the source. Fix = a drift check, not protecting the copy.
2. Coverage unions the editable lists of every accepted record in the window, so
   wave 1b's record still authorises after this stage opens. Green coverage ≠
   current stage authorised.
3. `_section_bullets` reads each editable bullet as an `fnmatch` pattern and `*`
   crosses `/`: a `.ai/**` grant would authorise the config, index and installed
   verifier forever. Enumerate, as the current record does.
4. `required .ai/state/BLOCKERS.md`, the `budget` lines and
   `registered project checks` all pass on an unfilled template. Three state
   files shipped blank until this stage filled them.
5. `.ai/runtime/WRITER_LOCK.json` is un-ignored by a `!` rule, so a blanket add
   commits a live lock. It now holds the released record (§10.D's D5 evidence):
   re-acquiring the lock overwrites it, so `--add` specific paths and leave the
   file out rather than unstaging it after the fact.
6. Exact counts are pinned (`480 passed, 5 skipped`; fresh `20/24 … 4 skipped`;
   migrated `21/24 … 3 skipped`); re-measure each test's own summary, since
   several edit config and differ from the baseline.
7. `run_python` resolves script paths against `cwd` — pass absolute, or rc 2 with
   empty output reads like an installer refusal; `make_repo()` refuses in-repo.

## Mandatory outcome

Every wave-1c item fails against `main` first, with that output in the PR;
`python .ai/scripts/sync_verify.py` stays green on this tree with the figure
re-measured after your change rather than copied — at `51dcf20` it was
`== 25/25 checks passed ==`, rc 0, no `[SKIP]`, `path coverage: 32 protected
touches covered`, `python test suite … 480 passed, 5 skipped`. Handoff files are
not protected paths, so editing them leaves that count alone; touching
`docs/evidence/` moves it again. Stop for one fresh-context review when done and
call it "reviewed by a different model" only if a different model did it.

## Absolute stop boundary

No tag, no Release, no version bump, no merge of any PR, no push to `main`, no
change to the user's global git config — not credentials, not anything — without
the user asking in terms. Never `git add -A`, never `git add -f` the gitignored
`.superpowers/`, never force-push, never rewrite published history. No
research-project content in this repository. A figure that exists only under
`.superpowers/` is not evidence: a reader of the clone cannot reach it.
