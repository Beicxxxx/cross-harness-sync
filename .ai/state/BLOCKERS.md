# Current Blockers

> Last updated: 2026-09-22 08:52 (+10:00)
> Updated by: qoder-cli (spec 10.D install landed; this file was an empty template).

## Active blocker

No technical blocker. Progress is parked at a decision only the user can make:
whether to tag `v2.1.0` and publish a GitHub Release, and whether wave 1c starts
now. Nothing is waiting on a mechanism that does not exist.

## Not blockers

- Wave 1c's defect list is open (14 minors and the three items in
  `docs/evidence/wave1b-facts.md` §7). It is queued, not blocked.
- `budget AGENTS.md` went red twice while this stage filled the installed files
  in (69 lines, then 66, against a cap of 65). The check was right and the file
  now fits; a budget that only bites other people's text is not a budget.
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
3. Every number published outside this repository must have been measured on the
   tree it describes. `docs/evidence/wave1b-facts.md` is the citable source;
   `.superpowers/` holds private reasoning and is gitignored, so figures that
   appear only there are not evidence a reader can reach.

## Standing constraints

- Frequently changing state files are never pinning targets.
- One active writer at a time.
- No tag, no GitHub Release, no version bump, no push to `main` without the user
  asking for it in terms.
