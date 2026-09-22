# Next Prompt — wave 1d is landed; what remains is the user's merge and any funded row

You are the single active implementation executor. Read, in order:
`.ai/state/CURRENT.md` §2-3, `.ai/state/TASK.md`, `.ai/state/BLOCKERS.md` (binding
disclosures), `.ai/state/ROLE_POLICY.md` §1-3 (tiers, R3/R5 as amended — R5 records
and never gates), and the two wave-1d records:
`.ai/state/authorizations/2026-09-22-wave1d.md` (runtime face) and
`docs/release-authorizations/2026-09-22-wave1d-product-changes.md` (release face).
Spec §2 (publishing red lines) is under `docs/superpowers/specs/`.

## Which face is which — the rule that shapes every step

`scripts/`, `templates/`, `tests/`, `README.md`, `SKILL.md` and `reference.md` ship
to other people. They are authorised in `docs/release-authorizations/`, never by a
record under `.ai/state/authorizations/`, and `protected_paths` does not list them:
`path coverage` will not catch the mistake, so the rule has to be held in your head.
Everything else — `.ai/**`, `AGENTS.md`, `CHANGELOG.md`, `docs/evidence/**`,
`docs/release-authorizations/**` — is this repository's own runtime face.

## Where the branch stands

`v2.1-wave1d-deferred-queue`: both wave-1d records `verdict: accepted`, wave 1c
`status: closed`, and the acceptance commit is this branch's tip. Whether its PR is
open is a `gh pr list` away; this file deliberately does not answer it, because the
commit that changes the verdicts cannot also contain the push that follows them.
Wave 1d shipped check 10 `governing copy` (each `.ai/scripts/*.py` against its
`scripts/` twin), the runtime window bound by the same `_base_conflicts` the release
face uses, one anchor predicate (`ai_common.is_full_sha`), cases for two shipped arms
no test reached, and the `CHANGELOG.md` entries wave 1c owed.
`docs/evidence/wave1d-facts.md` is the measurement-and-finding record;
`docs/evidence/wave1d-queue.md` is the queue.

## What is actually left

1. **Nothing to code without the user.** Merging PR #3 → #4 → #5, tagging, GitHub
   Release and any version bump are theirs, each in its own terms. A branch that is
   green and unmerged is a finished stage, not a stalled one.
2. **Queue rows, if the user funds them**: Q6 (`_load` duplicated across 15 test
   files under 5 signatures), Q8 (a diverged sidecar keeps running the old verifier),
   Q9 (a spent grant never expires inside its window), Q10 (runtime bullets still
   accept `*`, and `*` crosses `/`), Q11 (a typo'd `release_paths` is a silent SKIP),
   Q12 (`authorizations_dir` resolves differently in two readers), Q14 (four ways the
   window guard does not fire), Q15 (a `git show` that exits 0 and writes nothing
   still reads as a clean commit — the fix is one more arm plus a red test).
3. **Q13 is not work.** Eight ids (M-3, M-8..M-14) have no definition in any tracked
   file. Do not invent rows to match a count; the row says so and why.

## Measurements you must re-run rather than quote

- `python .ai/scripts/sync_verify.py` — on the accepted tree it prints no FAILED
  line, and `path coverage` / `release authorization` each name their covered total.
  Both totals move with every later commit that touches a protected or shipped path,
  so quote them only from the run you are holding.
- `python -m pytest tests/ -n 8 -o addopts= -q` — its own line, on your tree.
- A default install ends `== 21/27 checks passed, 6 skipped ==`, and `== 22/27,
  5 skipped ==` after `--migrate`, **as measured at the commit
  `docs/evidence/wave1d-facts.md` names**. Adding or removing a check moves both
  figures and `tests/test_authorization_records.py` goes red to say so: re-measure
  from the run, and move `README.md`, `SKILL.md` and `CHANGELOG.md` in the same
  commit, naming the commit each figure came from.

## Hazards that will bite you

1. Adding a check moves every pinned count. Never edit an expectation back to the
   old number.
2. `check_governing_copy` decides "is this the skill's source checkout" from
   `scripts/init_sync.py` PLUS at least one shared installed name, and prints
   `SKIP(undecidable-source-walk)` when those disagree. Do not simplify it back to a
   single filename test: that version held an innocent install permanently red, and
   the version after it called a deleted source walk an install.
3. The installer fills the slots only it can know. Once filled, the install differs
   from its template, so `is_template_shaped()` calls it hand-edited and `--force`
   refreshes nothing — `installer_slot_lines()` is the fix; leave it.
4. Two host traps: reading `AGENTS.md` as UTF-8 crashed on a GBK file, and `exists()`
   answers False for files this host merely denies, so it cannot guard that read;
   `.ai/runtime/WRITER_LOCK.json` is tracked and holds a released record
   `docs/evidence/` cites, so re-acquiring overwrites it.
5. A value folded across lines in a `## Governance` block makes §6 reject the whole
   block — `fields` comes back `{}` and the record can never be accepted (W17).
6. `sync_verify.py` runs the test suite as one of its `extra_checks`. Never quote a
   total from a run that overlapped your own edits — freeze the tree, then measure.

## Mandatory outcome

Every item fails against the tree it is meant to fix, with that output in the PR;
`sync_verify.py` and `python -m pytest tests/ -n 8 -o addopts= -q` are run after the
change and reported as they print, not as remembered. Stop for one review with fresh
context, and record what it was: say "reviewed by a different model" only when a
different model did it, and note any pass that died before it reported.

## Absolute stop boundary

No tag, no Release, no version bump, no merge of any PR, no push to `main`, no
change to the user's global git config — not credentials, not anything — without the
user asking in terms. Never `git add -A`, never `git add -f` the gitignored
`.superpowers/`, never force-push, never rewrite published history, never edit an
accepted record to satisfy a check it now refuses (close the stage, or open a new
one). No research-project content in this repository. A figure that exists only under
`.superpowers/` is not evidence: a reader of the clone cannot reach it.
