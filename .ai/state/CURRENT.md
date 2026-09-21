# Current Project State — the single source of truth for progress

> Last updated: 2026-09-22 08:42 (+10:00) by qoder-cli (spec 10.D dogfood landed).
> Budget: this file stays ≤ 60 lines (enforced by `.ai/scripts/sync_verify.py`).

## At a glance (for humans; machines treat this as authoritative)

| Item | State |
|---|---|
| Current stage | v2.1.0 wave 1b merged (PR #1); this repo now runs under its own protocol |
| Authorization | `.ai/state/authorizations/2026-09-22-wave1b-dogfood.md` (T2, accepted) |
| Blockers | none active; three claims below are unverifiable on this host |
| Health check | `python .ai/scripts/sync_verify.py` |
| Red lines | no "all green", no "enforced", no "cross-family"; no tag or release without the user |

## 1. Objective (one sentence)

Make one repository's work pick-up-able by several AI harnesses and several
machines using files and git alone.
Background lives in
`docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` — retrieve
on demand, never inline.

## 2. Active authorization (this stage)

`.ai/state/authorizations/2026-09-22-wave1b-dogfood.md` — no digest pinned: a stage record
that changes while it is executed is not a freezing artifact.
Executor: qoder-cli controller. Reviewer: a qoder-cli subagent with no shared
context — same model family, so this is a separate-context review and must never
be described as cross-family verification (rule R5 records family, it does not
gate on it).

## 3. Where the work stands

| Stream | State |
|---|---|
| Wave 1a | merged; 26 of 27 defects fixed, D14 was the single deferral |
| Wave 1b | merged as PR #1 (`3a5f2a9`): governance records, coverage walk, `--review-prompt`, `--migrate`, D14, N1 |
| This repo's own install | `.ai/` landed here by this stage — spec 10.D |
| Wave 1c | not started; needs its own authorization record before touching `scripts/` or `templates/` |
| Release | undecided: no tag, no GitHub Release |

## 4. Stage history

Archived: `.ai/state/archive/STAGE_MAP.md` (one line per stage; historical
numbers never renamed). Pointers only — do not restate history here.

## 5. Standing rules (retrieve on demand, never inline)

- Roles/review tiers: `.ai/state/ROLE_POLICY.md` (L1 — read when executing or reviewing).
- Decision retrieval: `.ai/state/DECISIONS_INDEX.md` (index only; read the single
  archived entry before reversing a past decision).
- A number may only be published from the tree it describes.
  `docs/evidence/wave1b-facts.md` is the citable source; `.superpowers/` is
  private reasoning and is never evidence a reader can reach.
- Unverifiable here and never to be claimed as tested: a second physical machine
  (D6/D16), a real shallow clone turning ancestry into `UNKNOWN`, and a review
  by a genuinely different model family.
