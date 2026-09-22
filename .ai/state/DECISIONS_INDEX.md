# Decisions Index (retrieval entry point — read THIS file, never the full DECISIONS body)

> Rule: new decision = one line here + ≤ 15 lines in `DECISIONS.md` active pages.
> Full text: the most recent ~20 entries live in `DECISIONS.md`; older ones in
> `archive/DECISIONS_<yyyymm>_full.md`.
> Before reversing a past decision: locate it here, read ONLY that single entry.

| Date | Decision | Location |
|---|---|---|
| 2026-09-22 | Fix wave's own defects closed by the controller, not a second lane | DECISIONS.md |
| 2026-09-22 | Spec 10.D satisfied as certification of what landed, not a retroactive process claim | DECISIONS.md |
| 2026-09-22 | Two shipped templates instruct behaviour the protocol forbids (`git add -A`; "cross-family review") | DECISIONS.md |
| 2026-09-22 | Governing-copy drift and stale record grants documented, not closed | DECISIONS.md |
| 2026-09-22 | Release face and runtime face are separate authorities: a record under `.ai/state/authorizations/` cannot certify shipped code | DECISIONS.md |
| 2026-09-22 | Cross-family review is a preference; a same-family downgrade must be recorded | DECISIONS.md |
| 2026-09-22 | A record verdict and its stage lifecycle are two fields (`verdict` vs `status`); retiring a stage must not retract its coverage | DECISIONS.md |
| 2026-09-22 | Accepted release records must declare `window_start_commit`; a moved anchor that drops their commits is a FAIL, not a quieter PASS | DECISIONS.md |
