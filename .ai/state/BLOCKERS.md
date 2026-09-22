# Current Blockers

> Last updated: 2026-09-23 01:50 (+10:00)
> Updated by: qoder-cli (wave 1d reviewed; records `pending`; nothing merged).

## Active blocker

Nothing technical. Wave 1d's two records read `verdict: pending` because the
acceptance commit has not been made; they have had two fresh-context review passes,
the second aimed at the first one's closures — which is the step wave 1c skipped and
disclosed skipping (W24). What is left to the user is merge (PR #3, then PR #4, then
wave 1d's own), tag/Release, and how much of `docs/evidence/wave1d-queue.md`'s
remaining rows to fund.

## Not blockers

- The push that looked impossible was Git Credential Manager trying to prompt in
  a shell with no `/dev/tty`. It is solved, not pending: per-command
  `credential.helper='!gh auth git-credential'` pushes fine non-interactively.
- Wave 1d's scope (queue rows Q1-Q5, Q7) is closed. The rows marked "left open,
  named" — Q6, Q8-Q12, Q14, Q15 — are decisions, not backlog, and Q13 says plainly
  that eight ids have no definition a reader can reach. Wave 1c's old spelling
  ("14 minors: M-3, M-4, M-5, M-7..M-14") named ids no tracked file defines, which
  is the dangling-reference defect this file warns about, committed by the wave that
  warned.
- One of the two passes this stage dispatched died in the model service and was not
  repeated; the other covered both scopes. Recorded in
  `docs/evidence/wave1d-facts.md` rather than smoothed into "two reviews".
- `budget AGENTS.md` went red twice while wave 1c filled the installed files in (69
  lines, then 66, against a cap of 65). The check was right and the file now fits; a
  budget that only bites other people's text is not a budget.
- The `.ai/` install postdates wave 1b, so it certifies what landed rather than
  how each step was reviewed. That is a limit on the claim, not an open task.

## Binding disclosures — carry into later write-ups

1. Four things are unverifiable on this host and must never be described as
   tested: a second physical machine (D6/D16), a real shallow clone turning
   ancestry into `UNKNOWN` (the evidence is a monkeypatched probe plus one
   POSIX-marked test that skips here), a review by a genuinely different model
   family, and any execution of wave 1b under this `.ai/` — it did not happen.
2. The verifier detects omission, not fabrication. A `[PASS] path coverage` line
   cannot distinguish an honest authorization record from an invented one, and
   the writer lock is advisory: nothing here prevents a concurrent writer.
3. The window guards bound what a record SAYS. Queue row Q14 lists four ways a
   narrowed coverage window still reports no FAILED line — closing the stage, never
   declaring a base, emptying the anchor, de-accepting the verdict — and all four
   turn on `status`/`verdict` being self-reports. No sentence in this repository may
   say the window is "enforced" or "bound" without saying by what.
4. `governing copy` compares what runs to what is authored. It cannot tell a stale
   copy from a hand-edited one, does not assert that every authored file was
   installed, and on a tree whose `scripts/init_sync.py` name is taken by unrelated
   code says so as `SKIP(undecidable-source-walk)` rather than pick a reading.
5. Every number published outside this repository must have been measured on the
   tree it describes. `docs/evidence/` is the citable source; `.superpowers/` holds
   private reasoning and is gitignored, so figures that appear only there are not
   evidence a reader can reach.

## Standing constraints

- Frequently changing state files are never pinning targets.
- One active writer at a time.
- No tag, no GitHub Release, no version bump, no push to `main` without the user
  asking for it in terms.
