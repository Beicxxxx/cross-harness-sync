# Release authorization — October code review fixes

Issued 2026-10-13 (Australia/Sydney) by the user: "有问题就都修复".
Base: `306683e9ea9a56ab3994a2f0c614a8a021dbe23e`.

## Scope

Preserve partially edited state under --force; reject negated secret-ignore
rules; recover failed migration commits; validate effective authorization
paths before migration writes; align required-file resolution. Add red-first
regressions and update the affected existing migration assertion.

Explicitly reconcile the two omitted wave-1e test paths below. This new grant
covers their existing touches at 5b5d83f/85aeab0 under the established coverage
union; it does not claim those historical commits passed the release check.
Keep the old accepted record intact except its closed status.

## Editable files

- `scripts/ai_common.py`
- `scripts/init_sync.py`
- `scripts/checkpoint.py`
- `scripts/sync_verify.py`
- `tests/test_review_regressions.py`
- `tests/test_migrate.py`
- `tests/test_version_and_naming.py`
- `tests/test_worktree_refusal.py`
- `CHANGELOG.md`

## Pins, roles and completion

Base commit above is the comparison baseline; no mutable-state hash pins.
Executor: Codex / GPT-6 / effort NOT_REPORTED.
Reviewer: Codex / GPT-6 / configured ultra; same-family, fresh-context,
uncalibrated. Final scoped closure verdict: ACCEPT. Red-first regressions, full suite, review, governing-copy parity
and release-coverage verification required. No version bump, tag or release.

## Governance

```governance
tier: T2
executor: Codex / GPT-6 / effort NOT_REPORTED
reviewer: Codex / GPT-6 / configured ultra; same-family, fresh-context, uncalibrated; ACCEPT
verdict: accepted
status: open
window_start_commit: 306683e9ea9a56ab3994a2f0c614a8a021dbe23e
red_before_green: true
user_authorized: true
```
