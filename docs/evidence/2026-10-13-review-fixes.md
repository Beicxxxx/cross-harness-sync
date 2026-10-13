# October code review fixes — evidence

Base: `306683e9ea9a56ab3994a2f0c614a8a021dbe23e`; date 2026-10-13 Sydney.
Executor: Codex / GPT-6 / effort NOT_REPORTED. Reviewer: Codex / GPT-6 / configured ultra; same-family, fresh-context, uncalibrated.

## Scope and baseline

Six findings: partial-template data loss, negated secret ignore, migration
commit recovery, authorization-directory escape, required-file parity, and
two omitted release authorization paths. Q9/Q10/Q14 remain deliberate limits.
Baseline full suite: `550 passed, 5 skipped in 121.24s`, exit 0.
Baseline installed verifier: release authorization FAIL, four uncovered pairs
at 5b5d83f/85aeab0 for tests/test_version_and_naming.py and
tests/test_worktree_refusal.py. This corrects the applicability of the old
wave-1e precommit success claim; it is not rewritten as a historical success.

## Red before green

Product code unchanged from the base when running:
`python -m pytest tests/test_review_regressions.py -n 4 -o addopts= -q --tb=short`
Result: `9 failed, 1 passed in 5.17s` (exit 1). The control already rejecting
an absolute CLI path passed. One earlier test run had a broken fault-injection
import; the result above is after repairing the fixture, before product edits.

The migration case intercepts only the first Git commit, after real staging;
real second/third runs test retry then idempotency, not a mocked clean preflight.
All filesystem fixtures live outside the working repository.

After initial fixes: related tests (review regressions, init safety, migration,
validate parity and config errors): `134 passed in 60.85s`, exit 0.
A follow-up boundary for user update metadata was then added and measured:
`python -m pytest tests/test_review_regressions.py -k force -o addopts= -q --tb=line`
Result: `1 failed, 2 passed, 8 deselected in 4.57s`. Restricting the installer
slot matcher to its owning templates addresses this same data-loss finding.

Template boundary and compatibility run after that fix: `34 passed in 13.10s`,
exit 0 (review regressions, init safety, lane-1c governance).

## Final validation

Pre-acceptance working tree: `python .ai/scripts/sync_verify.py` ran the
complete suite: `561 passed, 5 skipped in 109.99s`, child exit 0. Governing
copy: 3 installed files byte-identical. Verifier: `27/28 checks passed`, exit 1,
only release authorization failed on the four old pairs while the new grant
remains pending independent review. This is not reported as a successful gate.
First independent T2 review (Codex / GPT-6 / configured ultra, same-family,
fresh-context, uncalibrated) returned REJECT on two residual boundaries:
required files escaping the repo, and retries discarding the original version
and rollback evidence. Both were accepted for correction within the six fixes.

Residual reproductions: `python -m pytest tests/test_review_regressions.py
-k "failed_migration or outside_repository" -n 4 -o addopts= -q --tb=short`:
`4 failed in 5.85s`, exit 1, before those corrections. Recovery now includes a
real v2.0.0 script fixture, initial Git commit failure, successful retry,
preserved origin/start/touched paths/journal, then a verifying no-op.

After corrections, review regressions + migrate + validate parity + config
errors + ai_common: `162 passed in 22.43s`, exit 0. The repo-relative predicate
is shared by both readers, including resolved-path containment. Retry journals
preserve the previous incomplete attempt instead of erasing its exclusions.
The same reviewer returned ACCEPT on the scoped closure check: 4 passed,
10 deselected; all three installed copies byte-identical to source. No second
reviewer, cross-family claim, or reviewer-authored edits. Final full validation
will run on the implementation commit; its immutable revision and result will
be recorded in the close-out section below.

## Authorization reconciliation

New release record: docs/release-authorizations/2026-10-13-review-fixes.md.
The two historical paths are explicit grants under the existing union rule;
the old accepted record will only be closed by status. No history rewrite,
retroactive successful-check claim, version bump or release is involved.
