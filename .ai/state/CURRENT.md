# Current Project State — the single source of truth for progress

> Last updated: 2026-09-23 03:17 (+10:00) by cursor (wave 1e accepted; release pending
> tag). Budget: this file stays ≤ 60 lines.

## At a glance (for humans; machines treat this as authoritative)

| Item | State |
|---|---|
| Current stage | Wave 1e on `v2.1-wave1e-void-and-release`; void queue closed |
| Authorization | wave-1e both faces `verdict: accepted` (1 live); prior waves closed |
| Blockers | tag `v2.1.1` + GitHub Release after this tip is on `main` |
| Health check | `python .ai/scripts/sync_verify.py` |
| Red lines | no "all green", no "enforced", no "cross-family" without evidence |

## 1. Objective (one sentence)

Make one repository's work pick-up-able by several AI harnesses and several
machines using files and git alone.

## 2. Active authorization (this stage)

`.ai/state/authorizations/2026-09-23-wave1e.md` and
`docs/release-authorizations/2026-09-23-wave1e-void-and-release.md` — both
`verdict: accepted` after T2 review + F1 re-review ACCEPT. Facts:
`docs/evidence/wave1e-facts.md`. Queue dispositions:
`docs/evidence/wave1d-queue.md`.

## 3. Where the work stands

| Stream | State |
|---|---|
| Wave 1a–1d | on `main` (PR #3/#4/#5 merged) |
| Wave 1e | accepted: Q6/Q8/Q11/Q12/Q15 closed; Q9/Q10/Q14 known limits; Q13 unresolvable |
| Protocol stamp | still `2.1.0` (skill release tag is `v2.1.1`, not a protocol bump) |
| Release | tag + GitHub Release after merge to `main` |

## 4. Stage history

Archived: `.ai/state/archive/STAGE_MAP.md` — one line per stage, pointers only.

## 5. Standing rules (retrieve on demand, never inline)

- Roles/review tiers: `.ai/state/ROLE_POLICY.md`.
- Decision retrieval: `.ai/state/DECISIONS_INDEX.md`.
- Publish only numbers measured on the tree they describe (`docs/evidence/`).
- Unverifiable here: second physical machine, real shallow clone → `UNKNOWN`,
  genuinely different model-family review.
