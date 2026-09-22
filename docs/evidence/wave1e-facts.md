# Wave 1e facts — void closures and release

> Under `.ai/state/authorizations/2026-09-23-wave1e.md`. Figures land here only
> after re-measurement on the tip they describe.

## Known limits left named (not defects)

Published under `CHANGELOG.md` `## v2.1.1 — wave 1e`. Queue rows Q9/Q10/Q14 carry
matching `closed by decision:` status. Q13 remains cannot-be-resolved.

## Measurements

| # | what | command | result, verbatim | tree |
|---|---|---|---|---|
| V1 | full suite | `python -m pytest tests/ -n 8 -o addopts= -q` | `550 passed, 5 skipped` | accepted working tree on `v2.1-wave1e-void-and-release` |
| V2 | this repository verifier | `python .ai/scripts/sync_verify.py` | `== 28/28 checks passed ==`, no `FAILED:` line; suite via extra_checks `550 passed, 5 skipped`; `swarm boundary: 4 accepted… 1 live, 3 closed` | same tip as V1 |
| V3 | fresh/migrated tripwire (executor report) | `tests/test_authorization_records.py` pins | still `== 21/27 checks passed, 6 skipped ==` / migrated `== 22/27 checks passed, 5 skipped ==` | same wave; re-measured by executor, not edited back |

V2's swarm line shows wave 1e still `pending` (0 live). Acceptance flips that to 1 live and closes nothing else already closed.

## Review findings (fresh-context T2)

| # | severity | disposition |
|---|---|---|
| F1 | blocker | closed: incomplete migrate writes `to: null` + `incomplete: true`; recovery re-run after adopting sidecar stamps PROTOCOL (red: `test_adopting_a_sidecar_then_re_migrating_stamps_the_protocol`) |
| F2 | major | closed: incomplete commit message / print no longer claim `vN -> PROTOCOL` |
| F3 | major | closed: recovery red above; incomplete re-run no longer takes verify-only |
| F4 | nit | closed: queue Q6 status narrowed (primary `_load*` files, not "across the suite") |
| F5 | nit | closed: `reference.md` omit-vs-empty `release_paths` wording aligned with Q11 |
