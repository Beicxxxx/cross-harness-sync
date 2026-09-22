# Next Prompt — main holds wave 1c+1d; only owner decisions remain

You are the single active writer only if the user funds new work. Read, in order:
`.ai/state/CURRENT.md` §2–3, `.ai/state/TASK.md`, `.ai/state/BLOCKERS.md`
(binding disclosures), `.ai/state/ROLE_POLICY.md` §1–3. Spec §2 (publishing red
lines) is under `docs/superpowers/specs/`.

## There is nothing to implement until the owner decides

`main` tip is `22f460d` (Merge PR #5). PR #3, #4 and #5 are MERGED. Tag, GitHub
Release, version bump, and any void-queue coding need a fresh ask in those terms.
Do not "tidy" prose about finished merges.

If you are asked to continue anyway:
1. `python .ai/scripts/checkpoint.py --lock --agent <your-name>` — re-acquiring
   overwrites `.ai/runtime/WRITER_LOCK.json`, which `docs/evidence/` cites.
2. Re-run `python .ai/scripts/sync_verify.py` before quoting any figure.

## Where it actually stands

On `main` at `22f460d`, measured this close-out session:

- `== 28/28 checks passed ==`, no `FAILED:` line;
- `path coverage: 97 protected touches covered`;
- `release authorization: 122 release-face (commit, path) pairs covered by
  accepted record(s) (2 record(s) in docs/release-authorizations)`;
- `swarm boundary: 3 accepted of 3 records … 1 live, 2 closed`;
- suite, via `extra_checks`: `538 passed, 5 skipped`.

`docs/evidence/wave1d-facts.md` V13 still names a pre-merge tree. Quote neither
old nor new figures without re-running on the tip you claim.

## What is left in the void (not authorized to start)

`docs/evidence/wave1d-queue.md`: Q6, Q8, Q9, Q10, Q11, Q12, Q14, Q15. Q13 is not
work (eight ids with no reachable definition). Each needs user funding first.

## Rules that bind every step

- Two authorities. Release-face paths answer to `docs/release-authorizations/`;
  runtime `.ai/state/authorizations/` never certifies a shipped file.
- Publish only numbers measured on the tree they describe.
- Adding a check moves pinned counts; re-measure, never edit expectations back.
- Windows host: ASCII console; `exists()` False on Access Denied; `AGENTS.md`
  may not be UTF-8; folded `## Governance` values reject the whole block.
- Line budgets: `CURRENT.md` ≤ 60, `LATEST.md` ≤ 80, `NEXT_PROMPT.md` ≤ 100,
  `AGENTS.md` ≤ 65.

## Absolute stop boundary

No tag, no Release, no version bump, no force-push, no rewrite of published
history, no `git add -A`, no force-add of `.superpowers/`, no edit of an accepted
record to satisfy a check it now refuses (close by `status`, or open a new
stage). Commits use this repository's LOCAL `user.name`/`user.email`. No
research-project content here.
