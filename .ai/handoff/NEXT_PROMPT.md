# Next Prompt — finish wave 1c: the deferred minors, then the release documents

You are the single active implementation executor. Read, in order:
`.ai/state/ROLE_POLICY.md` (tiers, R1–R7 — note that R3 and R5 were reconciled on
2026-09-22 and cross-family is now a recorded preference, not a gate);
`.ai/state/CURRENT.md` §5 and `.ai/state/BLOCKERS.md` (binding disclosures);
`.ai/state/authorizations/2026-09-22-wave1c.md` (runtime face) and
`docs/release-authorizations/2026-09-22-wave1c-product-changes.md` (release face);
spec §2 (publishing red lines) under `docs/superpowers/specs/`.

## Which face is which — the rule that shapes every step below

`templates/` and `scripts/` ship to other people. They are authorised in
`docs/release-authorizations/`, never by a record under `.ai/state/authorizations/`,
and `protected_paths` no longer lists them: the previous stage registered the
release face there, which let this repository's own runtime certify what gets
published. The user ruled on this on 2026-09-22. Editing a shipped file under a
runtime record is the exact error to avoid; `path coverage` will no longer catch it.

## Done, on branch `v2.1-wave1c-governance-defects`

- The three defects found by line number, all fixed on the release face with
  red-first tests in `tests/test_lane_1c_governance.py` (9 cases): `R3`/`R5`
  contradicted each other; the templates and `README.md`/`SKILL.md` ordered
  `git add -A`; `<NAME> <<EMAIL>>` and the `Adopted:` line were copied verbatim and
  nothing checked them.
- `init_sync.py` now resolves the slots only it can know (project name, remote,
  commit identity from the repository's own config) and `sync_verify.py` reports
  what is left. Section 7 is dropped with a `WARN`, never invented for a stranger.
- `.ai/state/ROLE_POLICY.md` is finished and re-pinned; `AGENTS.md` states the
  two-face rule. Measurements: `docs/evidence/wave1c-facts.md`.

Two claims in the previous version of this file were wrong and are withdrawn: the
identity defect was never in `templates/AGENTS.md` (which holds a placeholder, not
a sentence pointing at repo history — the sentence was this repository's own), and
the "third template defect" I logged from it did not exist.

## Still to do — wave 1c's deferred list

- Wave-1b minors: M-3, M-4, M-5, M-7..M-14; `checkpoint._review_is_sha` accepting
  uppercase; `_migration_commit`'s post-commit listing check fixed without a test;
  15 duplicated `_load` helpers across 5 signatures.
- The governing-copy drift check: `.ai/scripts/*.py` is the copy that actually runs
  and it is outside `protected_paths`. Nothing detects it diverging from `scripts/`,
  so a green `sync_verify` is not evidence the installed verifier matches the source.
  This stage hit that limit itself — the fix landed in `scripts/` and had to be
  copied by hand. Fix = a drift check, not protecting the copy.
- The stale-grant rule: coverage unions the editable lists of every accepted record
  in the window, so a closed stage keeps authorising. `_section_bullets` reads each
  bullet as an `fnmatch` pattern and `*` crosses `/`, so enumerate, never wildcard.
- Re-measure the three figures `SKILL.md`/`README.md` publish, and land a CHANGELOG
  entry per release document touched. Do not carry numbers from
  `docs/evidence/wave1b-facts.md` — they belong to their own trees.

## Hazards that bit this stage

1. Adding a check moves every pinned count (`20/24`→`21/25` fresh,
   `21/24`→`22/25` migrated). `tests/test_authorization_records.py` is the
   tripwire; when it pulls, re-measure rather than editing the expectation.
2. Filling the installer's own slots makes the output differ from its template, so
   `is_template_shaped()` starts calling every install hand-edited and `--force`
   refreshes nothing. `installer_slot_lines()` is the fix — do not "simplify" it.
3. Reading `AGENTS.md` as UTF-8 crashed on a GBK file. `exists()` answers False for
   files this host merely denies, so it cannot guard that read either.
4. `.ai/runtime/WRITER_LOCK.json` holds a released record that `docs/evidence/`
   cites as D5; re-acquiring overwrites it. This stage holds epoch 3, released at
   close-out, and the older record survives in the dogfood commits.
5. `480 passed, 5 skipped` is wave 1b's number on wave 1b's tree. Read the suite's
   own line on the tree you are writing about.

## Mandatory outcome

Every item fails against the tree it is meant to fix, with that output in the PR;
`python .ai/scripts/sync_verify.py` stays green on this tree with the figure
re-measured after your change rather than copied; `python -m pytest tests/ -n 8
-o addopts= -q` reports its own totals. Stop for one review, cross-family where a
second family is reachable, and record which it was — say "reviewed by a different
model" only when one did.

## Absolute stop boundary

No tag, no Release, no version bump, no merge of any PR, no push to `main`, no
change to the user's global git config — not credentials, not anything — without
the user asking in terms. Never `git add -A`, never `git add -f` the gitignored
`.superpowers/`, never force-push, never rewrite published history. No
research-project content in this repository. A figure that exists only under
`.superpowers/` is not evidence: a reader of the clone cannot reach it.
