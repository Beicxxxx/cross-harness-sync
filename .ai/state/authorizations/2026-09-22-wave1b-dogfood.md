# Authorization — wave 1b dogfood (install this protocol into its own repo)

> Issued: 2026-09-22 08:39:01 (澳大利亚东部标准时间) by the user, who approved
> 推送并开 PR，同步skill 和随后「现在合并，并接着做 dogfood」.
> Recorded by: qoder-cli (controller).
> Git commit at issuance: `3a5f2a9c488f8f5b8bc320de451579a746a835c0` — main immediately
> after the wave-1b merge; the repo had no `.ai/` at all at that point.

## Scope

spec 10.D: run this protocol's own wave under a real `.ai/` install. This stage
installs `.ai/` into the repository that ships the protocol, registers
`scripts/`, `templates/` and `docs/evidence/` as protected paths, pins the
role-policy digest, sets the governance window to the wave's own base commit
(`db091bd`), and writes the measured facts that the CHANGELOG points at.
It authorizes the files wave 1b actually touched in that window — the coverage
walk below is over real history, not a fixture, so a path this record omits
prints a FAIL rather than passing quietly.

## Editable files

- `docs/evidence/wave1b-facts.md`
- `scripts/ai_common.py`
- `scripts/checkpoint.py`
- `scripts/init_sync.py`
- `scripts/sync_verify.py`
- `templates/AGENTS.md`
- `templates/AUTHORIZATION.md`
- `templates/SYNC_PROMPT.md`
- `templates/authorizations/INDEX.md`
- `templates/sync_config.json`
- `.ai/protocol/VERSION`, `.ai/sync_config.json`, `.ai/SYNC_PROMPT.md`,
  `.ai/scripts/*.py`, `.ai/templates/*`, `.ai/state/*.md`,
  `.ai/state/authorizations/2026-09-22-wave1b-dogfood.md`, `.ai/handoff/*.md`,
  and the four `.gitkeep` files — the install itself, enumerated rather than
  wildcarded. No `.ai/**` grant appears here on purpose: the bullet parser reads
  each entry as an `fnmatch` pattern, so a live `**` would silently authorise
  every later edit to the governance config, the index and the installed
  verifier. The walk also unions the editable lists of every accepted record in
  the window, so a grant here keeps its force after this stage closes; `.ai/`
  sitting outside `protected_paths` is the only reason that is inert for a
  verdict rather than a hole. Closing it properly is wave-1c work — see
  `.ai/state/DECISIONS.md`.
- `AGENTS.md`, `CLAUDE.md`, `.gitignore` (written by `init_sync.py`)
- `CHANGELOG.md` (the §10.D disclosure line this stage replaces)

## Roles

- Executor: qoder-cli controller (implemented the fix inline rather than
  dispatching; mutation-checked and re-measured, see CHANGELOG).
- Reviewer: a qoder-cli `general-purpose` subagent with no shared context, run
  against the prepared diff. The reviewing model's family was **not recorded**, so no claim holds in
  either direction — including this record's earlier "same model family" wording,
  which this line replaces. R5 makes an unknown field `NOT_REPORTED`, not a guess;
  only the absence of shared context is evidenced.

## Completion condition

`python .ai/scripts/sync_verify.py` prints `[PASS] path coverage: 29 protected
touches covered` where it printed 29 uncovered before this record existed, plus
`[PASS] pin violation` and `[PASS] role policy integrity`; the full suite stays
at 480 passed / 5 skipped; every number reaching the CHANGELOG is re-measured on
this tree.

## Stop boundary

No tag, no GitHub Release, no version bump, no change under `scripts/` or
`templates/`. Wave 1c work needs its own record: this one is spent on the install
and on certifying what wave 1b already landed.

## Governance

```governance
tier: T2
executor: qoder-cli/controller
reviewer: qoder-cli/general-purpose-subagent (same family; separate context)
verdict: accepted
red_before_green: true
user_authorized: true
```
