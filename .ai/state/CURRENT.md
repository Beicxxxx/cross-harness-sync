# Current Project State — the single source of truth for progress

> Last updated: 2026-09-23 02:31 (+10:00) by cursor (PR #3/#4/#5 merged to main).
> Budget: this file stays ≤ 60 lines (enforced by `.ai/scripts/sync_verify.py`).

## At a glance (for humans; machines treat this as authoritative)

| Item | State |
|---|---|
| Current stage | Wave 1c + 1d merged on `main` tip `22f460d`; no next wave funded |
| Authorization | wave-1d both faces still `verdict: accepted` (1 live); wave 1c `accepted` + `status: closed` |
| Blockers | tag, GitHub Release, version bump, and void-queue funding are the user's |
| Health check | `python .ai/scripts/sync_verify.py` |
| Red lines | no "all green", no "enforced", no "cross-family"; no tag/Release without the user |

## 1. Objective (one sentence)

Make one repository's work pick-up-able by several AI harnesses and several
machines using files and git alone. Background: the v2.1 design spec under
`docs/superpowers/specs/`, retrieved on demand, never inline here.

## 2. Active authorization (this stage)

No funded implementation row. Wave 1d's records remain the last accepted live
pair (runtime `.ai/state/authorizations/2026-09-22-wave1d.md`, release
`docs/release-authorizations/2026-09-22-wave1d-product-changes.md`). They were
not edited at merge. Open void: `docs/evidence/wave1d-queue.md`.

## 3. Where the work stands

| Stream | State |
|---|---|
| Wave 1a | merged; 26 of 27 defects fixed, D14 was the single deferral |
| Wave 1b | merged as PR #1 (`3a5f2a9`) |
| This repo's own install | `.ai/` is on `main` (PR #2 merged as `0bc4d7f`) |
| Wave 1c | merged via PR #3 then #4 (`dc364f5`, `53fcfb9`) |
| Wave 1d | merged via PR #5 (`22f460d`) |
| Release | undecided: no tag, no GitHub Release, no version bump |

## 4. Stage history

Archived: `.ai/state/archive/STAGE_MAP.md` — one line per stage, pointers only.

## 5. Standing rules (retrieve on demand, never inline)

- Roles/review tiers: `.ai/state/ROLE_POLICY.md` (L1 — read when executing or reviewing).
- Decision retrieval: `.ai/state/DECISIONS_INDEX.md` (index only; read the single
  archived entry before reversing a past decision).
- A number may only be published from the tree it describes. `docs/evidence/` is
  the citable source; `.superpowers/` is private reasoning, never reachable by a
  reader of the clone.
- Unverifiable here and never to be claimed as tested: a second physical machine
  (D6/D16), a real shallow clone turning ancestry into `UNKNOWN`, and a review
  by a genuinely different model family.
