# Current Blockers

> Last updated: 2026-09-23 02:31 (+10:00)
> Updated by: cursor (merge stack landed; remaining items are user decisions).

## Active blocker

Nothing technical. PR #3, #4 and #5 are MERGED into `main` (merge commits
`dc364f5`, `53fcfb9`, `22f460d`). What remains is the user's call: tag, GitHub
Release, any version bump, and whether to fund rows in
`docs/evidence/wave1d-queue.md` (Q6, Q8–Q12, Q14, Q15; Q13 is not work).

## Not blockers

- The merge order was #3 → retarget #4 to `main` → merge #4 → retarget #5 →
  merge #5. Stacked bases are resolved.
- Wave 1d's accepted records were left untouched at merge; closing them by
  `status` is a separate stage if the next writer wants zero live accepted
  records before opening a new one.
- Credential Manager / non-interactive push: still solved via
  `credential.helper='!gh auth git-credential'` when needed.
- Binding disclosures below are unchanged from the wave-1d close-out.

## Binding disclosures — carry into later write-ups

1. Four things are unverifiable on this host and must never be described as
   tested: a second physical machine (D6/D16), a real shallow clone turning
   ancestry into `UNKNOWN`, a review by a genuinely different model family, and
   any execution of wave 1b under this `.ai/` — it did not happen.
2. The verifier detects omission, not fabrication. A `[PASS] path coverage` line
   cannot distinguish an honest authorization record from an invented one, and
   the writer lock is advisory.
3. The window guards bound what a record SAYS. Queue row Q14 lists four ways a
   narrowed coverage window still reports no FAILED line — all four turn on
   `status`/`verdict` being self-reports.
4. `governing copy` compares what runs to what is authored. It cannot tell a
   stale copy from a hand-edited one, and on an undecidable tree says
   `SKIP(undecidable-source-walk)`.
5. Every number published outside this repository must have been measured on the
   tree it describes. `docs/evidence/` is the citable source; `.superpowers/` is
   gitignored.

## Standing constraints

- Frequently changing state files are never pinning targets.
- One active writer at a time.
- No tag, no GitHub Release, no version bump without the user asking in terms.
