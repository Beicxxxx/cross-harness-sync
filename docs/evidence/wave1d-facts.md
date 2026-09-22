# Wave 1d facts — what was measured, and what the review found

> Written 2026-09-22 by qoder-cli under
> `.ai/state/authorizations/2026-09-22-wave1d.md` (runtime face). Every figure here
> was produced on the tree it describes, with the commit named, because that rule is
> the one this project has broken most often — including in the two waves this row
> format comes from.

## Measurements

| # | what | command | result, verbatim | tree |
|---|---|---|---|---|
| V1 | full suite, quiet tree | `python -m pytest tests/ -n 8 -o addopts= -q` | `537 passed, 5 skipped` | W1's fix in the tree, on top of `d3c3165` (uncommitted when run — the commit that contains it is the next row's subject) |
| V2 | fresh install into a throwaway git repo | `python scripts/init_sync.py <tmp>` then the installed `sync_verify.py` | `== 21/27 checks passed, 6 skipped ==` | `d3c3165` |
| V3 | the same install after `--migrate` | `python scripts/init_sync.py <tmp> --migrate` | `== 22/27 checks passed, 5 skipped ==` | `d3c3165` |
| V4 | this repository, both records still `pending` | `python .ai/scripts/sync_verify.py` | `== 26/28 checks passed ==`, `FAILED: path coverage, release authorization` | `d3c3165` |
| V5 | the drift check on this repository | same command, its own line | `[PASS] governing copy: 3 installed files byte-identical to their twins in scripts/ (sha-256 over the whole file)` | `d3c3165` |
| V6 | the name collision the review found | fresh install + an own `scripts/init_sync.py`, no twins | before the fix: `[FAIL] governing copy: 3 of 3 installed files are not the bytes their source says …`; after: `[SKIP] governing copy: SKIP(not-source-checkout): scripts/ shares no file name with .ai/scripts/, …` | `d3c3165` + working tree |
| V7 | `--migrate` under another agent's lock | `checkpoint.py --lock --agent someone-else`, then `init_sync.py <tmp> --migrate` | rc 2, `MIGRATE REFUSED: the writer lock could not be acquired…` / ``checkpoint.py --lock` exited 1: LOCK CONFLICT: held by someone-else until …` / `Advisory lock: you may wait for expiry, coordinate, or re-run with --force --reason "<why>"` | `d3c3165` |
| V8 | the failure string Q5's assertion now demands | `ai_common.log_paths(repo, ["--no-merges", "definitely-not-a-ref"], ["docs"])` | `"git log rc=128: fatal: bad revision 'definitely-not-a-ref'"` | `d3c3165` |
| V9 | wave 1c's release-face file count, for the CHANGELOG entry | `git diff --name-only 0bc4d7f5..aecd536 -- scripts templates README.md SKILL.md reference.md tests` | 22 lines | `aecd536` |
| V10 | which tracked artifact named the deferred ids | `git show aecd536:<file> \| grep "M-[0-9]"` over the four L0/L1 handoff files | one hit: `.ai/handoff/NEXT_PROMPT.md:47`; CURRENT/TASK/BLOCKERS published the count only | `aecd536` |
| V11 | X1's ambiguous tree, after the fix | same scaffold, `scripts/init_sync.py` present, all three twins deleted | `[SKIP] governing copy: SKIP(undecidable-source-walk): scripts/init_sync.py is present but scripts/ holds none of the 3 installed name(s), so this check cannot tell 'scripts/ is unrelated code that borrows the installer's filename' from 'the source side of these copies was deleted'; neither reading is a pass and neither is compared` | working tree, post-X1 |
| V12 | suite and verifier, once the review fixes were in | `python -m pytest tests/ -n 8 -o addopts= -q`; `python .ai/scripts/sync_verify.py` | `538 passed, 5 skipped`; `== 25/28 checks passed ==` with `FAILED: budget .ai/handoff/LATEST.md, path coverage, release authorization` at the first run and the budget line cleared by the handoff trim before the commit | working tree on `9150b6a`, before the commit that carries this row |
| V13 | the accepted tree: both wave-1d records `verdict: accepted`, wave 1c `status: closed` | `python .ai/scripts/sync_verify.py`, re-run twice | `== 28/28 checks passed ==`, no `FAILED:` line, `[PASS] governing copy: 3 installed files byte-identical to their twins in scripts/ (sha-256 over the whole file)`, `[PASS] path coverage: 75 protected touches covered`, `[PASS] release authorization: 78 release-face (commit, path) pairs covered by accepted record(s) (2 record(s) in docs/release-authorizations)`, `[PASS] swarm boundary: 3 accepted authorization(s) of 3 record(s) in the window -- 1 of them live, 2 closed`, and its `extra_checks` suite line `538 passed, 5 skipped`. The first run of this pair printed `== 27/28 ==` with `FAILED: budget .ai/state/CURRENT.md` — the close-out rewrite had pushed that file to 61 lines against a cap of 60, so the check was right and the file was trimmed, not the cap raised | working tree on `98d5ce2`, uncommitted when run — the acceptance commit is this row's tree |

V2/V3 are the two figures `README.md` and `SKILL.md` publish, and they are what
`tests/test_authorization_records.py` pins by name; V4's two FAILED lines are the
mechanism, not a regression — a `verdict: pending` record certifies nothing, which
is the whole design of the release gate.

## The pass over this stage, and where each finding went

One fresh-context reviewer, dispatched with no prior context, read
`check_governing_copy`/`_base_conflicts` and every claim the stage wrote, and
reproduced the figures above in its own throwaway repos. Its first dispatch (the
code-only pass) died in the model service and was not repeated; the second covered
both, and this row says so rather than implying two passes ran.

| # | finding | disposition |
|---|---|---|
| W1 | A plain install owning its own `scripts/init_sync.py` was read as the skill's checkout and held permanently red over three twins it never had — the witness was a filename, described in the code as "structural" | closed, red-first as D-7: the answer now needs the witness AND one shared installed name; the collision probe at V6 is the pair of outputs |
| W2 | "the runtime window is bound by the records that live in it" overclaimed: three escapes exist — closed-and-narrowed in one edit, a baseless record, and `window_start_commit: ""` → `SKIP(no-window: unset)` | closed as wording, `CHANGELOG.md` + `docs/evidence/wave1d-queue.md` Q14 now name all three; the first two are decisions, the third is the never-migrated shape |
| W3 | This record's own completion condition said the window "cannot be advanced at all" because wave 1c is live, citing a helper since renamed and a base wave 1c does not carry | closed: the paragraph now says the anchor stays put as a decision, names Q14 as the reason nothing machine-side enforces it, and states what the new guard DOES bind (this record's own declared base) |
| W4 | "E-2, E-3, E-4 and D-5 are controls, green before and after" — D-5 was red at the base with the rest of its lane | closed: the release record's completion condition separates the three real controls from D-5, and says which were green and why |
| W5 | "seven ids", and "no definition anywhere in this repository OR its private ledger" | closed: eight (M-3 + M-8..M-14), and the ledger's one-clause gloss is quoted into Q13 so the reachable copy lives in a tracked file; nothing in the row depends on opening the private one |
| W6 | "four public artifacts name M-3, M-4, M-5, M-7..M-14" | closed: V10 is the measurement; the record and the CHANGELOG now say one named the ids and three published the count |
| W7 | `.ai/state/TASK.md` carried a stale suite total | closed at close-out, from V1 |
| W8 | `.ai/sync_config.json` was listed as editable "for the drift check's own config key", and no key was added and the file was never touched | closed: the bullet says what it is for now |
| W9 | the template documents the moved-past case but not that a malformed or off-history declared base is itself a FAIL | closed: `templates/AUTHORIZATION.md` now states it, and `reference.md` already covered it for the release face the guard is shared from |

The reviewer also confirmed, by re-running rather than reading: V2/V3, SKILL.md's six
skip names, V7's refusal text, V8's string, Q15's code claim, and that every path
this stage touched is listed in the correct one of the two records — no shipped file
resting on a runtime grant, which is the error this wave's records exist to prevent.

## What this stage still cannot claim

- **No cross-family review.** The reviewer ran in a separate context on this host's
  session model; the family and tier of a subagent are not readable from anything
  this host logs, so `reviewer_family` is `NOT_REPORTED` and no sentence here or in
  a record says "reviewed by a different model". One of the two dispatched passes
  never ran at all (W-row preamble).
- **`red_before_green` is honest per item, not per lane.** D-1..D-7, E-1 and the
  uppercase case were each red against the tree they were meant to fix; the D/E
  cases landed in the same commits as their fixes, so the red exists in this
  session's runs and not in a separate commit. That is weaker than a red commit and
  is stated instead of being dressed up as one.
- **`governing copy` still cannot tell a stale copy from a hand-edited one**, and it
  does not assert that every authored file was installed; both limits are in its
  own docstring and in `reference.md`.
- Wave 1c's two records were `status: open` at the time of the two review passes, and
  its runtime record declares no base, so Q14's first two escapes were the state of
  this tree rather than a hypothesis. Acceptance (V13) closes wave 1c by `status`,
  which does not fix either one: a live baseless record becomes a closed record, and
  a closed record is never asked. The mechanism's reach is unchanged by this stage.

## The second pass, over these closures

The first pass's findings are above; a second fresh reviewer was then pointed at
`f3b270e` and `9150b6a` specifically, with the instruction to attack the closures
rather than re-open what was agreed — because wave 1c accepted its own final
closures without such a pass and said so in `docs/evidence/wave1c-facts.md` W24. It
found eight things, and W1's fix was among them: the fix had traded a false red for
a false statement.

| # | finding | disposition |
|---|---|---|
| X1 | `not witness or not shared` let a genuine source walk whose twins were ALL deleted report `SKIP(not-source-checkout): … so this tree is an install rather than the skill's own checkout` — a claim the tree does not support, and a loud red turned into a skip. Reproduced: witness present, three twins deleted | closed: the two cases get different tokens. No witness is `not-source-checkout`; witness present and no installed name present is `SKIP(undecidable-source-walk)`, whose text says which two readings it cannot tell apart and that neither is a pass. Reproduced verbatim in V11 |
| X2 | no test covered "exactly one installed name is present in `scripts/`, and it is the drifted one" — a `shared` computed by digest equality instead of by name passed the whole lane while flipping that tree from FAIL to SKIP | closed by D-9, which is that tree. D-7 was also strengthened to assert the new token and to reject the false sentence |
| X3 | W7 was marked closed while `.ai/state/TASK.md` still published `516 passed, 5 skipped` | closed for real in the same close-out batch that writes this row, from V12 |
| X4 | Q14 claimed all its escapes appear in the template; the empty-anchor one did not | closed: `templates/AUTHORIZATION.md` now names the `""` → `SKIP(no-window: unset)` route, and the queue row claims four escapes instead of three |
| X5 | a fourth escape the enumeration missed: bases come only from ACCEPTED records, so de-accepting a stage's `verdict` and narrowing the anchor in one edit also empties the range | closed as disclosure (row Q14). Not closed as mechanism: binding the window to a record that no longer claims authority would invert what `verdict` means, and the family the escape belongs to — `status` and `verdict` are self-reports — is already stated as the limit |
| X6 | the template's new base-shape sentence read as if it applied to every record; the checks sit behind `if not live: continue`, so a `status: closed` record may carry a garbage base undetected | closed: the sentence says "a LIVE record's declared base", and adds that a closed one is not asked at all |
| X7 | `CHANGELOG.md` attributes the `21/27` / `22/27` pair to `7b44120` while this file records the same pair at `d3c3165` | closed by measuring once more on the final tree and naming that one commit in both files (V12), instead of keeping two attributions for one figure |
| X8 | `README.md` and `SKILL.md` publish the two totals without naming a commit | NOT changed, on purpose: the shipped README's form is "measured on the tree this line ships in — `git log -1 --format=%h` where you read it", which self-locates for a reader on any branch. A pinned sha would be false the moment the file is read on a later commit, which is the failure wave 1c's own review caught. Recorded here so the choice is a decision and not an oversight |

The reviewer also confirmed, by running rather than reading: W3's rewritten
completion condition is true (accepting both records and advancing the anchor past
`aecd536` prints the named FAIL); D-7's original collision case and D-4's stranded
copy both behave; a fresh install still ends `== 21/27 checks passed, 6 skipped ==`;
the installed mirror did not drift when the fix was copied; and every release-face
path this stage touched is enumerated in the release record, with no shipped file
resting on the runtime grant. Its one inaccuracy in the other direction: Q13's
quotation of the private ledger drops `→ release note` from the clause it quotes,
which is corrected here rather than in the row, since the row's claim is about the
shape of the gloss.
