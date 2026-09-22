# Current Project State — the single source of truth for progress

> Last updated: 2026-09-23 01:40 (+10:00) by qoder-cli (wave 1d reviewed; records
> not yet accepted).
> Budget: this file stays ≤ 60 lines (enforced by `.ai/scripts/sync_verify.py`).

## At a glance (for humans; machines treat this as authoritative)

| Item | State |
|---|---|
| Current stage | Wave 1d on `v2.1-wave1d-deferred-queue`; wave 1c on PR #3 + stacked PR #4; PR #2 merged as `0bc4d7f` |
| Authorization | both wave-1d records `verdict: pending` — reviewed, not yet accepted; wave 1c's two are `accepted` |
| Blockers | merge only: PR #3 and PR #4 are the user's call, as are tag and Release |
| Health check | `python .ai/scripts/sync_verify.py` |
| Red lines | no "all green", no "enforced", no "cross-family"; no tag or release without the user |

## 1. Objective (one sentence)

Make one repository's work pick-up-able by several AI harnesses and several
machines using files and git alone. Background: the v2.1 design spec under
`docs/superpowers/specs/`, retrieved on demand, never inline here.

## 2. Active authorization (this stage)

`.ai/state/authorizations/2026-09-22-wave1d.md` (runtime face) and
`docs/release-authorizations/2026-09-22-wave1d-product-changes.md` (what ships) —
both `verdict: pending`, both reviewed. Accepting them also closes wave 1c by
`status`, because two live accepted records in one window is the condition
`swarm boundary` exists to refuse. Measurements and each review finding's
disposition: `docs/evidence/wave1d-facts.md`; the open queue:
`docs/evidence/wave1d-queue.md`. Reviewers were fresh-context subagents; their model
families are not readable from this host's logs, so the honest value is
`NOT_REPORTED` — R5 forbids guessing either way.

## 3. Where the work stands

| Stream | State |
|---|---|
| Wave 1a | merged; 26 of 27 defects fixed, D14 was the single deferral |
| Wave 1b | merged as PR #1 (`3a5f2a9`): governance records, coverage walk, `--review-prompt`, `--migrate`, D14, N1 |
| This repo's own install | `.ai/` is on `main` (PR #2 merged as `0bc4d7f`) |
| Wave 1c | accepted on PR #3/#4, unmerged: policy/R3-R5, `git add -A`, unfilled slots, the release gate, and verdict-vs-`status` |
| Wave 1d | reviewed, records pending, on its own branch: check 10 `governing copy`, the runtime window guard shared with the release face, one anchor predicate, and the deferred queue as a tracked file with every row dispositioned |
| Release | undecided: no tag, no GitHub Release |

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
