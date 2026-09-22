# The deferred queue, as a tracked artifact

> Written 2026-09-22 by qoder-cli under
> `.ai/state/authorizations/2026-09-22-wave1d.md`. This file exists because four
> public artifacts (`.ai/state/CURRENT.md`, `.ai/state/TASK.md`,
> `.ai/state/BLOCKERS.md`, `.ai/handoff/NEXT_PROMPT.md`) pointed a fresh session at
> "wave-1b minors: M-3, M-4, M-5, M-7..M-14" and **no tracked file defines any of
> those ids**. They live in `.superpowers/`, which `AGENTS.md` and
> `.ai/state/BLOCKERS.md` both state a reader cannot reach. That is the failure
> `docs/evidence/wave1b-facts.md` §7 names in its own words — "no invented defect
> numbers … an identifier it does not define would be a dangling promise" — committed
> by the wave that wrote the warning.

Two rules for this table. A row is only here if a tracked artifact or the ledger
says what the item *is*; and the status column distinguishes "fixed, with a case
that was red first" from "looked at and left" from "cannot be resolved".

| # | item | what it actually is | status |
|---|---|---|---|
| Q1 | governing-copy drift | `.ai/scripts/*.py` is the copy that governs an install and nothing compared it to `scripts/*.py`. Wave 1c edited `scripts/` and hand-copied twice, going green both times without proving the governing verifier matched. Named in `docs/evidence/wave1b-facts.md` §7 and in `.ai/state/DECISIONS.md`. | open → this stage |
| Q2 | runtime window narrowing | `governance.window_start_commit` is one config line compared to nothing; advancing it drops commits from the walk and they read as covered. Closed on the release face in wave 1c by `_release_base_conflicts`; the runtime face has no record-declared base, and W18 left its empty-window hole open on purpose. | open → this stage |
| Q3 | two predicates for one question | `checkpoint._review_is_sha` accepts uppercase hex; `ai_common.window_is_valid` refuses it. Recorded in wave 1b's own ledger as a 1c item. | open → this stage |
| Q4 | M-2 | `_migration_commit` reads `listing.ok` and deliberately keeps `ok=True` when the post-commit listing fails, naming the degradation instead. Fixed in code in wave 1b with no test. | open → this stage (test only) |
| Q5 | M-5 | `tests/test_tristate_history.py:227` asserts the literal substring `"git log"` inside an error string, so the assertion tests wording rather than the contract. | open → this stage |
| Q6 | M-4 | `_load` is duplicated across 15 test files under 5 signatures (the ledger corrects an earlier "3 files" claim). A shared helper in `tests/helpers.py` is the fix. | left open — see the note below |
| Q7 | M-7 | `init_sync.py --migrate` is blocked by its own earlier writer lock and the hint never says "release the lock first". Wave 1b recorded it as an operator-experience note for the release note, not a code defect. | open → `CHANGELOG.md` |
| Q8 | sidecar divergence | A v2.0 install with a diverged sidecar keeps running the OLD verifier and reports `== 14/14 ==`, which is rosier than the current `20/24` shape. From wave 1b's ledger, "for the merge decision". | left open, named |
| Q9 | stale-grant rule | Coverage unions the `## Editable files` of every accepted record in the window, so a spent record keeps authorising. Wave 1c added `status: open\|closed` for the concurrency question and deliberately did NOT give grants an expiry: an accepted record still never expires inside its window. | left open by decision |
| Q10 | runtime-record globs | `release authorization` refuses `*?[` in accepted release bullets; the runtime walk still accepts a bullet of `*`, which would cover every protected path in the window forever. Found twice (W17, W22). The asymmetry is real, not an oversight: this repository's own accepted records use runtime wildcards, so refusing them would rewrite approved grants after the fact. | left open, named |
| Q11 | `release_paths` typed wrong | A typo'd or emptied `release_paths` yields `SKIP(no-release-paths)` at rc 0 with no unknown-key warning anywhere; `required_files` has a floor, this does not. Found by W22's second reviewer. | left open, named |
| Q12 | reader split on `authorizations_dir` | `sync_verify` resolves a relative `authorizations_dir` against the checkout, `checkpoint` also tries `.ai/`, so a config of `state/authorizations` makes one reader count records the other cannot see. Found by W22's first reviewer, pre-existing. | left open, named |
| Q13 | M-8..M-14 | The ledger's whole remainder in one clause: "M-3(rc2 child→return0), M-4(dedupe _load, 15 files), M-5(bad_err literal), M-7(migrate self-lock hint), M-8..M-14 (operator wording/dubious-ownership stderr/agent-facing templates)". M-3 is the only one of that group this stage could not pin to a tracked line: no `.superpowers/` file, test or comment states which child, which exit code, and which return. | **cannot be resolved** — M-3 and M-8..M-14 have no definition anywhere in this repository or its private ledger, so no row claims to be one of them. Publishing seven numbered rows to match a count of fourteen would be the dangling-promise defect again with better formatting. |

## What is NOT a row

M-1 (`CHANGELOG.md` claimed "exactly one named `[SKIP]` forever") and M-6 (the
escaping-path refusal had no test) are already closed on `main` in wave 1b — they
appear here only so the numbering gap is explained rather than looked for.

## Reading this table as a queue

Rows marked "this stage" are wave 1d's scope under
`docs/release-authorizations/2026-09-22-wave1d-product-changes.md`. Rows marked
"left open, named" are the project's known limits and belong in any write-up that
says what the protocol does not do; they are not hidden behind a green run.
