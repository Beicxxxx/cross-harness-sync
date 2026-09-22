# Latest Handoff

> Updated: 2026-09-22 18:28 (+10:00) by qoder-cli, mid wave 1c: the release gate
> and the verdict-vs-`status` split are pushed on PR #3 and stacked PR #4.
> Budget: ≤ 80 lines. Background and boundary statements live in
> `.ai/state/CURRENT.md` — link, never copy.

## 1. Done

- PR #2 merged as `0bc4d7f`, so `main` carries `.ai/`. The §10.D figures belong to
  the tree `docs/evidence/wave1b-facts.md` describes and are not restated here.
- The user ruled on a contradiction inside the shipped policy (R3 required a
  different model family at T2/T3; R5 says family is recorded, never gating).
  Cross-family is now the default with a **recorded** `same-family` fallback.
- Four release-face defect groups, each red-first: the R3/R5 contradiction,
  `git add -A` ordered by the shipped instructions, slots no code ever filled while
  the unfilled ROLE_POLICY was digest-pinned, and an installer that resolved them
  from the machine instead of the repository. `tests/test_lane_1c_governance.py`.
- `sync_verify.py` gained `release authorization`: the shipped surface is now
  authorised in `docs/release-authorizations/`, not by a record under `.ai/`,
  with its own window anchor, shape checks, glob refusal and empty-window arms.
  `tests/test_lane_1c_release_gate.py`.
- `verdict` and `status` are separate fields (W19): closing a finished stage no
  longer retracts the coverage its record grants, and `swarm boundary` counts
  live writers. `scripts/{ai_common,sync_verify,checkpoint}.py`,
  `templates/AUTHORIZATION.md`, `tests/test_swarm_boundary.py`.
- The gate's own review then found it advisory where it claimed to be a wall: an
  unreadable release record sat under a coverage PASS, and `release_window_start_commit`
  could be moved forward so the dropped commits read as covered. Accepted records must
  now name their base, an anchor that passed one is a FAIL, and a zero-touch window with
  nothing accepted is a named SKIP. `tests/test_lane_1c_release_gate.py` C4-18..C4-22.
- Runtime face kept in step: ROLE_POLICY re-pinned, `AGENTS.md` states the
  two-face rule, the `.ai/scripts/` copies synced by hand.

## 2. Not done

- Neither record is accepted: both read `verdict: pending`. Four fresh-context
  passes have run (W13, W17, twice in W22); the closure they produced has not been
  looked at, and `window_start_commit` is new shipped behaviour since.
- The CHANGELOG entry for the release documents is not written, though
  `README.md` and `SKILL.md` figures were re-measured.
- Deferred: 14 wave-1b minors, the governing-copy drift check, the stale-grant
  rule, `*`-crosses-`/` for runtime records, and the coverage walk's share of the
  degenerate-window guard (W18 says why it is not wired).

## 3. Evidence pointers

- `docs/evidence/wave1c-facts.md` — W1…W23, each measured on this tree: the
  red-at-base runs, the stale counts a reviewer caught (six now, W22's included),
  and the acceptance dry-run (W19) that found the lifecycle defect.
- `docs/release-authorizations/2026-09-22-wave1c-product-changes.md` — what ships
  and why, authorised outside the runtime record.

## 4. Warnings

- `python .ai/scripts/sync_verify.py` reads `== 25/27 ==` with `FAILED: path
  coverage, release authorization`, and that is the mechanism rather than a
  regression: a pending record certifies nothing. W19 holds the three measurements
  that locate the gap and the one rehearsal (reverted) that closes it.
- `.ai/scripts/*` is synced by hand and has no drift check, so a green
  `sync_verify` does not prove the installed verifier matches `scripts/`.
- Counts are pinned in three places (fresh, migrated, this repo);
  `test_authorization_records.py` is the tripwire. Any figure quoted from a
  handoff is stale by construction — re-run the command.

## 5. Next step

One fresh-context pass over W23's closures — the base cross-check, the unreadable
and unanchored window arms, the review prompt's closed-record line. Then ONE commit
that accepts both records and writes `status: closed` on
`.ai/state/authorizations/2026-09-22-wave1b-dogfood.md` — never its `verdict`,
which is what covers wave 1b's own touches. Merging is the user's call.

## 6. Must-read list

- `.ai/state/ROLE_POLICY.md` §1–3 as amended — the rule this stage changed.
- `docs/evidence/wave1c-facts.md` W6, W10 and W19 — the two-face consequence, the
  upgrade path breaking it would silently destroy, and the acceptance cycle.
- `docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` §2 — the
  publishing red lines, binding on any text that leaves this repo.
