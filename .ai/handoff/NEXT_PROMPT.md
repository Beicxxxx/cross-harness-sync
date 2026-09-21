# Next Prompt — push the dogfood stage, open PR #2, then start wave 1c

You are the single active implementation executor. Read, in order:

1. `.ai/state/ROLE_POLICY.md` (review tiers and rules R1–R7);
2. `.ai/state/CURRENT.md` §5, then `.ai/state/BLOCKERS.md` (binding disclosures);
3. `.ai/state/authorizations/2026-09-22-wave1b-dogfood.md` — the stage record
   covering the work described in "Task 0" below;
4. `docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` §2
   (publishing red lines) and §6 (the governance layer you are tightening).

## The one thing blocking everything else

The dogfood stage is **committed locally and never published**. `main` locally
equals `origin/main` at `3a5f2a9` (wave 1b, PR #1 merged), but the two
`.ai/`-install commits exist only on a local branch with no upstream:

    * v2.1-dogfood-10d   b32c818  (no upstream)   <- local only
      main               3a5f2a9  [origin/main]   <- what the world can clone
      v2.1-wave1b-...    3df7c11  [origin/...]    <- merged, kept for history

So a clone of the public repo today still has **no `.ai/` directory**, and every
number in `CHANGELOG.md` §"Spec 10.D" and §7 of
`docs/evidence/wave1b-facts.md` is therefore unpushed. Check this before
believing anything below: `git ls-remote --heads origin | grep dogfood` must
return a line, and `git log --oneline -1 origin/main` must not still say
`3a5f2a9` when you claim the stage is public.

`git push` fails in a non-interactive shell here — Git Credential Manager tries
to prompt, `/dev/tty` does not exist, and it dies with `could not read Username
for 'https://github.com'`. The `gh` CLI's own token is still valid, so `gh pr
create` and all reads work; only git's transport credential lapsed. Do not
assume a hang means "wait longer": it is waiting for input that cannot arrive.

Two ways forward, and the user decides which:

    # A — they run this once in a real terminal, browser auth pops:
    cd "F:\Papers and Projects\cross-harness-sync"
    git push -u origin v2.1-dogfood-10d

    # B — per-command, no persistent config change (still needs the user's
    # explicit go-ahead, since it routes their gh token into git):
    git -c credential.helper='!gh auth git-credential' push -u origin v2.1-dogfood-10d

After the push lands, open the PR with the body that is already written:

    gh pr create --base main --head v2.1-dogfood-10d \
      --title "feat(10D): run this protocol in its own repository" \
      --body-file .superpowers/sdd/2026-09-21-cross-harness-sync-v2.1-wave1b-governance-migration/pr2-body.md

That body file lives under gitignored `.superpowers/`; read it before pushing so
it is not the only copy if the workspace is cleaned.

## Task 0 — finish the dogfood stage (authorized, in flight)

Nothing about the dogfood work itself is unfinished: the install landed, the
stage record was reviewed by a separate-context reviewer (0 Critical, 4
Important, all closed), and the tree is clean. What remains is publication and
the release decision.

Owned files only (from `.ai/state/authorizations/2026-09-22-wave1b-dogfood.md`,
whose list the coverage walk generated):

- `scripts/ai_common.py`, `scripts/checkpoint.py`, `scripts/init_sync.py`,
  `scripts/sync_verify.py`
- `templates/AGENTS.md`, `templates/AUTHORIZATION.md`, `templates/SYNC_PROMPT.md`,
  `templates/authorizations/INDEX.md`, `templates/sync_config.json`
- `docs/evidence/wave1b-facts.md`
- the `.ai/` paths the record enumerates, plus `AGENTS.md`, `CLAUDE.md`,
  `.gitignore`, `CHANGELOG.md`

Anything not listed is read-only for this stage.

## Task 1 — wave 1c (needs its own record before you touch shipped code)

Land the deferred list: the wave-1b minors (M-3, M-4, M-5, M-7..M-14,
`checkpoint._review_is_sha` accepting uppercase, `_migration_commit`'s
post-commit listing check fixed without a test, the 15 duplicated `_load`
helpers across 5 signatures) plus the three findings in
`docs/evidence/wave1b-facts.md` §7.

Start with the two shipped-template defects, because they are what every harness
reads first — both verified by line number, not inferred:

- `templates/AGENTS.md:48` — `git add -A && git commit && git push`, two lines
  above the same file's "never commit secrets".
- `templates/handoff/NEXT_PROMPT.md:31` — "Stop for exactly one independent
  cross-family review when done." Rule R5 records model family and never gates on
  it, and §2 forbids the claim; following this line verbatim produces an
  overclaim.

Write the wave-1c authorization record **first**, and enumerate the files it
covers — `scripts/` and `templates/` are protected paths, so
`[FAIL] path coverage: … uncovered of … protected touches` is what you get if
you edit them without one.

## Known hazards to inspect first

1. `.ai/scripts/*.py` is the copy that actually governs and it is **outside**
   `protected_paths`. It is byte-identical to `scripts/*.py` right now (checked
   by digest at this stage), so nothing detects drift: you can edit
   `scripts/sync_verify.py`, commit, and the installed verifier that CI-less
   humans run keeps reporting green on the old code. Fix = a drift check, not
   adding `.ai/scripts/*` to `protected_paths`.
2. The coverage walk unions the editable lists of every accepted record in the
   window, so wave 1b's record still authorises its paths after this stage opens.
   Do not read a green `path coverage` as "the current stage is authorised".
3. `fnmatch`'s `*` crosses `/`, and `_section_bullets` reads each editable bullet
   as a pattern. `.ai/**` in a record would authorise the governance config, the
   index and the installed verifier forever — that is why the current record
   enumerates instead. Keep that.
4. `required .ai/state/BLOCKERS.md`, the `budget` lines, and
   `registered project checks` all pass on an **unfilled template**. Presence is
   not content; three such files shipped unfilled until this stage filled them.
5. `.ai/runtime/WRITER_LOCK.json` is un-ignored by a `!` rule, so a blanket add
   commits a live lock. Release it before staging, and note that `--unlock`
   writes `released_at` rather than deleting — a released lock is the durable
   evidence §10.D asks for.
6. Exact-count assertions: `480 passed, 5 skipped`, `20/24 checks passed,
   4 skipped` (fresh install) and `21/24 … 3 skipped` (migrated) are pinned. If
   you change the check set, re-measure **each test's own** summary — several
   edit config, so they are not the baseline numbers.
7. `helpers.git()` / `make_repo()` refuse targets inside this repository. Any
   install/verify measurement needs a temp path, and `run_python` resolves
   relative script paths against `cwd` — pass absolute, or you get rc 2 and an
   empty output that looks like an installer refusal.

## Mandatory outcome

- `git ls-remote` and `gh pr view 2` show the dogfood stage is actually public.
- Each wave-1c item has a test that fails against `main` first, with the
  first-fail output in the PR description.
- `python .ai/scripts/sync_verify.py` on this tree stays green, and any figure
  quoted from it is re-measured after your change, not copied from here. Current
  measured state on `b32c818`: `== 25/25 checks passed ==`, rc 0, no `[SKIP]`
  line, `python test suite … 480 passed, 5 skipped`, `[PASS] path coverage: 31
  protected touches covered`. Fresh install elsewhere still
  `== 20/24 checks passed, 4 skipped ==`.
- Stop for exactly one independent review by a fresh-context reviewer when done,
  and describe it as "reviewed by a different model" only if a different model
  actually did it — never as cross-family verification.

## Absolute stop boundary

No tag, no GitHub Release, no version bump, and no merge of any PR without the
user asking in terms. Never `git add -A`, never `git add -f` the gitignored
`.superpowers/`, never force-push, never rewrite published history. No push to
`main` directly — publish by branch and PR. Do not change the user's global
`git config`, including anything credential-related, without an explicit ask.
No research-project content belongs in this repository at any point, and no
figure that appears only under `.superpowers/` may be published as evidence: a
reader of the clone cannot reach it.
