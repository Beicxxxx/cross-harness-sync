# Release authorization — wave 1d product changes

> Issued 2026-09-22 20:20 (+10:00) by the user's instruction to continue and to
> leave no mess. Recorded by qoder-cli (controller).
> Base commit: `aecd536bc2e073e19d60ebc984ba614f1a6fc549` (wave 1c accepted).

## What ships

Six lines, each a gap wave 1c found by being bitten by the first, by its own
reviewers on the second and third, and by a count that moved under it on the
fourth and fifth; the sixth is two shipped arms that no test case ever reached.
Each row is the defect in the product as published, not a description of the diff.

| File | Defect in the shipped product |
|---|---|
| `scripts/sync_verify.py` | `.ai/scripts/*.py` are the copies that actually govern an installing repository, and nothing compared them to `scripts/*.py`. Wave 1c edited the source twice and hand-copied, reporting green each time while the governing verifier could have been anything. A protocol whose own installed copy can silently differ from what it ships has no answer to "which rules ran". |
| `scripts/sync_verify.py` | The runtime coverage walk takes its window from one config line and compares it to nothing, so advancing `governance.window_start_commit` drops commits from the walk and they read as covered rather than as missing. Wave 1c closed this for the release face by asking each accepted record to declare its base; the runtime face has no such declaration, and the hole is the same shape. |
| `scripts/checkpoint.py`, `scripts/ai_common.py` | `checkpoint._review_is_sha` accepts uppercase hex where `ai_common.window_is_valid` refuses it, so one repository carries two definitions of "is this a commit id" and the review prompt's window answer can disagree with the verifier's. One predicate, in `ai_common`, is the fix. |
| `templates/AUTHORIZATION.md` | The template told a stage that `window_start_commit:` is "release records only". It is now the line that binds THIS repository's own coverage window too: a live accepted runtime record that states its base refuses an anchor moved past it, and one that states nothing is unguarded at its back edge. A field whose contract lives only in the checker is a field people get wrong. |
| `README.md`, `SKILL.md` | Both publish the fresh-install and migrated-install verifier figures as measured numbers. A check added to the shipped verifier falsifies them on the day it lands, which is how wave 1c's own review found the pair unprotected; they are re-measured here rather than carried forward. |
| `tests/test_migrate.py`, `tests/test_tristate_history.py` | Two arms of the shipped code had no case reaching them. `_migration_commit`'s post-commit listing path — the one wave 1b's final review changed precisely because an error there used to print `0 path(s) committed` over a commit nobody rechecked — shipped with no test at all, and one suite assertion checked that an error string contained the words `git log` instead of checking that it tells an operator which query died and with what code. A green suite is not coverage, and a reader of `tests/` cannot tell the difference from here. |

## What is deliberately not in here

No new config key, and no change to `templates/sync_config.json`: the drift check
compares the two installed copies by file name and digest, so it cannot be turned
off by a project's config and cannot be widened to paths the install does not have.
The narrowing guard reads the base each record already states rather than inventing
a field, because a field is a self-report and history is not — which is why
`templates/AUTHORIZATION.md` is in here: the field existed, and its contract on the
runtime side existed only inside the checker.
`tests/` is in the release face and is enumerated below, since a shipped test that
pins a count is part of what a downstream project reads.

## Editable files

One path per bullet. The bullet parser takes a bullet's FIRST backtick span as its
pattern, and accepted release records are refused a `*` outright, so a packed line
grants nothing to its second path and a wildcard grants too much forever.

- `scripts/sync_verify.py`
- `scripts/ai_common.py`
- `scripts/checkpoint.py`
- `README.md`
- `reference.md`
- `SKILL.md`
- `templates/AUTHORIZATION.md`
- `tests/test_lane_1d_governing_copy.py`
- `tests/test_migrate.py`
- `tests/test_tristate_history.py`
- `tests/test_coverage_walk.py`
- `tests/test_authorization_records.py`
- `tests/test_review_prompt.py`
- `tests/test_harness_smoke.py`
- `tests/test_config_errors.py`
- `tests/test_subprocess_hardening.py`
- `tests/test_second_machine.py`

## Roles

- Executor: qoder-cli controller.
- Reviewer: none yet, and `verdict` stays `pending` for that reason. Wave 1c
  accepted its own final closures without a pass over them and said so in
  `docs/evidence/wave1c-facts.md` W24; repeating that silently is the mess this
  stage exists to clear.

## Completion condition

Each row above has a case that was red against `aecd536bc2e073e19d60ebc984ba614f1a6fc549`
first: D-1..D-7 in `tests/test_lane_1d_governing_copy.py` (the drift check and its
collision fix), E-1 in `tests/test_coverage_walk.py` (the narrowing guard) and the
uppercase-anchor case in `tests/test_review_prompt.py`. E-2, E-3 and E-4 in the
coverage file are controls — they pin what the new rules must NOT do and they were
green at the base because the walk had not yet been asked anything about a base.
D-5 is not a control in that sense and is not claimed as one: it was red with the
rest of its lane, since no `governing copy` line existed to PASS on.
The check-count tripwire in `tests/test_authorization_records.py` is expected to
pull when a check is added: re-measure the fresh-install and migrated totals from
the run rather than editing the expectation to the old number.

## Governance

```governance
tier: T2
executor: qoder-cli/controller
reviewer: NOT_REPORTED (no pass has run on this stage)
verdict: pending
status: open
window_start_commit: aecd536bc2e073e19d60ebc984ba614f1a6fc549
red_before_green: true
user_authorized: true
```

## Boundary

No tag, no GitHub Release, no version bump, no merge. `.ai/state/authorizations/
2026-09-22-wave1d.md` governs this repository's own files and grants nothing here.
