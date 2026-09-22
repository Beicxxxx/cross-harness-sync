# Next Prompt — wave 1e accepted; land v2.1.1 on main

You are finishing an already-authorized release. Read CURRENT.md §2–3, TASK.md,
BLOCKERS.md, ROLE_POLICY.md §1–3.

## Task

1. Ensure wave 1e is on `main` (merge PR if needed).
2. Re-run `python .ai/scripts/sync_verify.py` on that tip; quote only those figures.
3. Tag `v2.1.1` (protocol stamp stays `2.1.0`) and create the GitHub Release from
   the CHANGELOG wave 1e section.
4. Update handoff; unlock; stop.

## Absolute stop boundary

No force-push, no history rewrite, no `git add -A`, no force-add of
`.superpowers/`, no global git config edits, no protocol stamp claim that is not
measured.
