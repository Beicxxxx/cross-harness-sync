# Current Project State — the single source of truth for progress

> Last updated: <YYYY-MM-DD HH:MM> (<timezone>) by <harness/model> (<what triggered the update>).
> Budget: this file stays ≤ 60 lines (enforced by `.ai/scripts/sync_verify.py`).

## At a glance (for humans; machines treat this as authoritative)

| Item | State |
|---|---|
| Current stage | <one line> |
| Authorization | <active authorization file, or "none"> |
| Blockers | <one line, or "none"> |
| Health check | `python .ai/scripts/sync_verify.py` |
| Red lines | <one line pointing at standing prohibitions> |

## 1. Objective (one sentence)

<What this project is trying to achieve, one sentence only.>
Background lives in <path-to-long-context-doc> — retrieve on demand, never inline.

## 2. Active authorization (this stage)

`<path-to-authorization.md>` — SHA-256: `<hash if pinned>`
Executor: <harness/model>; Reviewer: <harness/model (cross-family)>.

## 3. Where the work stands

| Stream | State |
|---|---|
| <workstream 1> | <one line> |
| <workstream 2> | <one line> |

## 4. Stage history

Archived: `.ai/state/archive/STAGE_MAP.md` (one line per stage; historical
numbers never renamed). Pointers only — do not restate history here.

## 5. Standing rules (retrieve on demand, never inline)

- Roles/review tiers: `.ai/state/ROLE_POLICY.md` (L1 — read when executing or reviewing).
- Decision retrieval: `.ai/state/DECISIONS_INDEX.md` (index only; read the single
  archived entry before reversing a past decision).
