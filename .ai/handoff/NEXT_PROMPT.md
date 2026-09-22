# Next Prompt — push the dogfood stage, open PR #2, then start wave 1c

You are the single active implementation executor. Read, in order:
`.ai/state/ROLE_POLICY.md` (tiers, R1–R7); `.ai/state/CURRENT.md` §5 and
`.ai/state/BLOCKERS.md` (binding disclosures);
`.ai/state/authorizations/2026-09-22-wave1b-dogfood.md`; spec §2 (publishing red
lines) and §6 under `docs/superpowers/specs/`.

## The one thing blocking everything else

The dogfood stage is committed locally and **never published**:

    * v2.1-dogfood-10d   (no upstream)   <- `git log --oneline main..HEAD`
      main               3a5f2a9  [origin/main]   <- all a clone can get

So the public repo still has no `.ai/`, and every §10.D figure in `CHANGELOG.md`
and `docs/evidence/wave1b-facts.md` §7 is unpushed. Prove publication rather than
trusting a claim: `git ls-remote --heads origin | grep dogfood` returns a line and
`gh pr view 2` exists.

`git push` cannot run in a non-interactive shell: Git Credential Manager tries to
prompt, `/dev/tty` does not exist, and it dies with `could not read Username for
'https://github.com'`. The `gh` token is still valid, so reads and `gh pr create`
work. A hang here is waiting for input that cannot arrive — not slow.

Two routes; the user picks, and B routes their gh token into git:

    # A — once, in a real terminal (browser auth pops):
    cd "F:\Papers and Projects\cross-harness-sync"
    git push -u origin v2.1-dogfood-10d
    # B — per-command, nothing persistent, needs explicit go-ahead:
    git -c credential.helper='!gh auth git-credential' push -u origin v2.1-dogfood-10d

Then `gh pr create --base main --head v2.1-dogfood-10d --title "feat(10D): run
this protocol in its own repository" --body-file
.superpowers/sdd/2026-09-21-cross-harness-sync-v2.1-wave1b-governance-migration/pr2-body.md`.
That body lives under gitignored `.superpowers/` and may be the only copy.

## Task 0 — the dogfood stage (authorized; nothing in it left undone)

The install landed and a separate-context reviewer closed 4 Importants before
commit. Owned files are enumerated in the stage record; anything not listed there
is read-only.

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
   commits a live lock. `--unlock` writes `released_at` rather than deleting —
   that released record is §10.D's evidence.
6. Exact counts are pinned (`480 passed, 5 skipped`; fresh `20/24 … 4 skipped`;
   migrated `21/24 … 3 skipped`); re-measure each test's own summary, since
   several edit config and differ from the baseline.
7. `run_python` resolves a relative script path against `cwd` — pass absolute, or
   rc 2 with empty output reads like an installer refusal. `helpers.git()` and
   `make_repo()` refuse targets inside this repo; use a temp path.

## Mandatory outcome

`git ls-remote` and `gh pr view 2` show the stage is public; every wave-1c item
fails against `main` first, with that output in the PR; `python
.ai/scripts/sync_verify.py` stays green on this tree with the figure re-measured
after your change rather than copied — at `b32c818` it was `== 25/25 checks
passed ==`, rc 0, no `[SKIP]`, `path coverage: 31 protected touches covered`,
`python test suite … 480 passed, 5 skipped`. Stop for one fresh-context review
when done and call it "reviewed by a different model" only if a different model
did it.

## Absolute stop boundary

No tag, no Release, no version bump, no merge of any PR, no push to `main` and no
change to the user's global git config — not credentials, not anything — without
the user asking in terms. Never `git add -A`, never `git add -f` the gitignored
`.superpowers/`, never force-push, never rewrite published history. No
research-project content in this repository. A figure that exists only under
`.superpowers/` is not evidence: a reader of the clone cannot reach it.
