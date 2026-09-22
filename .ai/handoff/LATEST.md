# Latest Handoff

> Updated: 2026-09-22 12:15 (+10:00) by qoder-cli, mid wave 1c: the release-face
> fixes are landed and tested, the review and the deferred minors are not.
> Budget: ≤ 80 lines. Background and boundary statements live in
> `.ai/state/CURRENT.md` — link, never copy.

## 1. Done

- PR #2 merged as `0bc4d7f`, so `main` carries `.ai/` and the §10.D figures are
  reachable by a clone. Nothing here restates those figures; they belong to the
  tree `docs/evidence/wave1b-facts.md` describes.
- The user ruled on a contradiction inside the shipped policy: R3 required a
  different model family at T2/T3 while R5 said family is recorded and never
  gates. Cross-family is now the default with a **recorded** `same-family`
  fallback, restated consistently in the policy, `templates/`, `README` and `SKILL`.
- Three release-face defects fixed red-first in `tests/test_lane_1c_governance.py`:
  the R3/R5 contradiction, `git add -A` ordered by the shipped instructions, and
  slots (`<NAME> <<EMAIL>>`, `Adopted: … by <who>`) that no code ever filled and
  no check ever caught — while the unfilled ROLE_POLICY was digest-pinned.
- `init_sync.py` resolves the slots only it can know (from the repository's own
  config), names the ones it cannot, and drops ROLE_POLICY section 7 with a `WARN`
  instead of inventing someone else's boundaries. `sync_verify.py` reports residue.
- This repository's runtime face updated to match: `.ai/state/ROLE_POLICY.md`
  finished and re-pinned, `AGENTS.md` states the two-face rule, and the install
  copies under `.ai/scripts/` were synced by hand.

## 2. Not done

- No review has run on this increment, so
  `.ai/state/authorizations/2026-09-22-wave1c.md` records `verdict: pending`. Do
  not write "reviewed" here until one has.
- Nothing is pushed: the branch has no upstream and there is no PR #3 yet.
- The CHANGELOG entry for the release documents is not written, though `README.md`
  and `SKILL.md` figures were re-measured.
- Deferred: 14 wave-1b minors, the governing-copy drift check, the stale-grant
  rule. All listed in `handoff/NEXT_PROMPT.md`.

## 3. Evidence pointers

- `docs/evidence/wave1c-facts.md` — W1…W12, each measured on this tree, including
  the red-at-base run and the two regressions this stage caused and fixed.
- `docs/release-authorizations/2026-09-22-wave1c-product-changes.md` — what ships
  and why, authorised outside the runtime record.
- `tests/test_lane_1c_governance.py` — the 9 cases; run them against a base worktree
  to reproduce W1.

## 4. Warnings

- `protected_paths` dropped `scripts/*` and `templates/*`. `path coverage` therefore
  reads 8 where wave 1b read 33. That is the ruling, not a regression — but it also
  means **nothing in the runtime check now guards an unauthorised edit to shipped
  code**. The release record and the review are the control.
- `.ai/scripts/*.py` was synced by hand this time and still has no drift check, so a
  green `sync_verify` does not prove the installed verifier matches `scripts/`.
- Counts are pinned in three places at once (fresh, migrated, this repo). A new check
  moves all three; `test_authorization_records.py` is the tripwire that says so.

## 5. Next step

Commit, push the branch and open PR #3 with the red-at-base output inline (a clone
cannot reach `.superpowers/`). Then one review — cross-family where a second family
is reachable, otherwise same-family with no shared context — and only then fill the
record's `reviewer` and `verdict`. Ask the user before any tag or Release.

## 6. Must-read list

- `.ai/state/ROLE_POLICY.md` §1–3 as amended — the rule this stage changed.
- `docs/evidence/wave1c-facts.md` W6 and W10 — the two-face consequence and the
  upgrade path that breaking it would silently destroy.
- `docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` §2 — the
  publishing red lines, binding on any text that leaves this repo.
