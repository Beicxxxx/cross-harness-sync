# Release authorization — wave 1e void queue and release

> Issued 2026-09-23 02:47 (+10:00) by the user's instruction to finish every
> remaining undone item. Recorded by cursor.
> Base commit: `e6e10299bc58eba8ca89be09075a982ecaee0699`.

## What ships

| File | Defect in the shipped product |
|---|---|
| `tests/helpers.py` + many `tests/test_*.py` | `_load` duplicated across ~15 files under ~5 signatures (Q6). |
| `scripts/sync_verify.py` | A `.py.new` sidecar left by migrate/scripts-only means the OLD installed verifier still runs and can look healthier than current (Q8). |
| `scripts/sync_verify.py` | Typo'd / emptied `release_paths` (or unknown config keys) yield silent `SKIP(no-release-paths)` at rc 0 (Q11). |
| `scripts/checkpoint.py`, `scripts/ai_common.py` | Relative `authorizations_dir` resolves against checkout in verify but also against `.ai/` in checkpoint (Q12). |
| `scripts/init_sync.py` | Post-commit `git show` rc 0 with zero bytes still reports clean commit and skips containment recheck (Q15). |
| `README.md`, `SKILL.md`, `CHANGELOG.md`, `templates/*` as needed | Publish re-measured install figures and the void dispositions; version bump for the release. |

Q9 / Q10 / Q14 stay known limits (no grant expiry; runtime wildcards grandfathered; window-guard escapes are self-reports) — dispositioned in evidence, not "fixed" by pretending the protocol enforces what it records.

## Editable files

- `scripts/sync_verify.py`
- `scripts/ai_common.py`
- `scripts/checkpoint.py`
- `scripts/init_sync.py`
- `README.md`
- `SKILL.md`
- `reference.md`
- `CHANGELOG.md`
- `templates/AUTHORIZATION.md`
- `templates/sync_config.json`
- `tests/helpers.py`
- `tests/test_authorization_records.py`
- `tests/test_migrate.py`
- `tests/test_tristate_history.py`
- `tests/test_coverage_walk.py`
- `tests/test_review_prompt.py`
- `tests/test_harness_smoke.py`
- `tests/test_config_errors.py`
- `tests/test_subprocess_hardening.py`
- `tests/test_second_machine.py`
- `tests/test_lane_1c_governance.py`
- `tests/test_lane_1c_release_gate.py`
- `tests/test_lane_1d_governing_copy.py`
- `tests/test_validate_parity.py`
- `tests/test_write_atomicity.py`
- `tests/test_init_flags.py`
- `tests/test_init_safety.py`
- `tests/test_install_encoding.py`
- `tests/test_governance_record.py`
- `tests/test_ai_common.py`
- `tests/test_glob_match.py`
- `tests/test_required_files.py`
- `tests/test_config_merge.py`
- `tests/test_lane_1e_void.py`

## Roles

- Executor: cursor agent.
- Reviewer: fresh-context subagent(s); model family NOT_REPORTED (R5).

## Completion condition

Red-first cases for Q6/Q8/Q11/Q12/Q15; tripwire counts in
`test_authorization_records.py` re-measured, never edited back. Suite green;
verifier no FAILED line. Version + tag + GitHub Release match CHANGELOG.

## Governance

```governance
tier: T2
executor: cursor/agent
reviewer: cursor fresh-context T2 + F1 re-review ACCEPT; model family NOT_REPORTED (R5)
verdict: accepted
status: open
window_start_commit: e6e10299bc58eba8ca89be09075a982ecaee0699
red_before_green: true
user_authorized: true
```

## Boundary

Tag and Release are in scope for this stage (user asked for every undone item).
Runtime state is governed by `.ai/state/authorizations/2026-09-23-wave1e.md`.
