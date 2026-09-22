# Latest Handoff

> Updated: 2026-09-22 12:12 (+10:00) by qoder-cli, mid wave 1c: the release-face
> fixes are pushed as [PR #3](https://github.com/Beicxxxx/cross-harness-sync/pull/3);
> the review and the deferred minors are not.
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
- [PR #3](https://github.com/Beicxxxx/cross-harness-sync/pull/3) is open against
  `main`, two commits split by face: `06dc156` release, `c4a9586` runtime.
- The CHANGELOG entry for the release documents is not written, though `README.md`
  and `SKILL.md` figures were re-measured.
- Closed since the review (`19fcfcb`): the emitted `git add -A`, three `reference.md`
  requirements, the `7 failed` count, the CONTROL argument, and three unsupported
  "same model family" assertions — the one on `main` corrected by new text, not by
  rewriting history. PR #4 added the release gate; its review found the record it
  depends on could never parse, fixed in `9b46161`. Three holes still block it: a
  PASS on a misspelled `release_paths`, on an anchor at HEAD, outside the repo.
- Deferred: 14 wave-1b minors, the governing-copy drift check, the stale-grant rule.

## 3. Evidence pointers

- `docs/evidence/wave1c-facts.md` — W1…W15, each measured on this tree, including
  the red-at-base run and the two regressions this stage caused and fixed.
- `docs/release-authorizations/2026-09-22-wave1c-product-changes.md` — what ships
  and why, authorised outside the runtime record.
- `tests/test_lane_1c_governance.py` — 11 cases; run them against a base worktree
  to reproduce W1.

## 4. Warnings

- `protected_paths` dropped `scripts/*` and `templates/*`, so the walk counts this
  repository's evidence commits alone and reads FAIL with rc 1 while the record is
  `pending` — an unaccepted record certifies nothing, which is the mechanism working.
  What is genuinely missing is a guard over the release face; see §2.
- `.ai/scripts/*.py` was synced by hand this time and still has no drift check, so a
  green `sync_verify` does not prove the installed verifier matches `scripts/`.
- Counts are pinned in three places at once (fresh, migrated, this repo). A new check
  moves all three; `test_authorization_records.py` is the tripwire that says so.

## 5. Next step

PR #4: the release-face check (a commit touching `scripts/` or `templates/` names an
accepted release record), red-first, plus the `22/25` tripwire. Then close PR #3 —
accepting its record only if the review is honestly attributed: this session's logs
held one segment, every model field `qfmodel`, no per-agent attribution, so no
cross-family attestation may be written (W14).

## 6. Must-read list

- `.ai/state/ROLE_POLICY.md` §1–3 as amended — the rule this stage changed.
- `docs/evidence/wave1c-facts.md` W6 and W10 — the two-face consequence and the
  upgrade path that breaking it would silently destroy.
- `docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` §2 — the
  publishing red lines, binding on any text that leaves this repo.
