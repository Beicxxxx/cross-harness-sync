# Current Project State — the single source of truth for progress

> Last updated: 2026-09-23 03:25 (+10:00) by cursor (v2.1.1 tagged and released).
> Budget: ≤ 60 lines.

## At a glance

| Item | State |
|---|---|
| Current stage | Wave 1e on `main` tip `85aeab0`; tag `v2.1.1` published |
| Authorization | wave-1e both faces `verdict: accepted` (1 live) |
| Blockers | none |
| Health check | `python .ai/scripts/sync_verify.py` |
| Red lines | no "all green", no "enforced", no unverified cross-family |

## 1. Objective

Make one repository's work pick-up-able by several AI harnesses and several
machines using files and git alone.

## 2. Active authorization

`.ai/state/authorizations/2026-09-23-wave1e.md` and
`docs/release-authorizations/2026-09-23-wave1e-void-and-release.md` — accepted.
Facts: `docs/evidence/wave1e-facts.md`. Queue: `docs/evidence/wave1d-queue.md`.

## 3. Where the work stands

| Stream | State |
|---|---|
| Waves 1a–1d | on `main` |
| Wave 1e | merged as PR #6; void queue closed |
| Release | GitHub Release `v2.1.1`; protocol stamp still `2.1.0` |
| Next | no funded row |

## 4. Stage history

`.ai/state/archive/STAGE_MAP.md` — pointers only.

## 5. Standing rules

- Roles: `.ai/state/ROLE_POLICY.md`. Decisions: `DECISIONS_INDEX.md`.
- Publish only numbers measured on the tree they describe.
- Unverifiable here: second machine, real shallow → `UNKNOWN`, different family.
