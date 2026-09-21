# Wave 1b measured facts — cross-harness-sync v2.1.0

Tracked copy of the numbers `CHANGELOG.md`'s wave-1b section quotes. It exists
because the original evidence lived under `.superpowers/`, which is gitignored:
a clone of this repository could not verify a single figure. Absolute paths are
stripped throughout; every row names the command, so a reader can re-run it.

Host for all rows: Windows nt, Python 3.14.5, pytest 9.1.1, xdist 3.8.0, git
2.x, one foreground session per measurement.

## 1. Full suite

| # | command | measured |
|---|---|---|
| F1 | `python -m pytest tests/ -n 8 -o addopts=""` at `3546c08` | `450 passed, 5 skipped` |
| F2 | same command, after the wave-1b doc edits at `3546c08` | `450 passed, 5 skipped` (elapsed differed; elapsed is host load and is not quoted as a fact) |
| F3 | `python -m pytest tests/test_coverage_walk.py::test_the_shallow_or_indeterminate_halt_is_pinned_on_this_host tests/test_coverage_walk.py::test_a_real_shallow_clone_halts_the_walk -n 0 -o addopts="" -v -rs` | `[TRUE-True] PASSED`, `[UNKNOWN-True] PASSED`, `[FALSE-False] PASSED`, `test_a_real_shallow_clone_halts_the_walk SKIPPED` (`posix-only test, running on nt`), `3 passed, 1 skipped` |
| F4 | same command, at `9937e0a` (the first fix wave for the three false-greens in §5) | **`2 failed, 477 passed, 5 skipped`** — the two failures were `test_no_milestones_references_remain` and `test_d26_unit_claim_is_clean_outside_templates`, and this file caused both: it quoted the two grep patterns verbatim, and `docs/evidence/` is scanned by both guards. Recorded rather than edited away because a published number that hides a red run is the thing §4 is about |
| F5 | same command, at HEAD after the §5 I-2c fix and the de-quoting of §6 below | `480 passed, 5 skipped` (`42-49s` depending on host load): 450 → 480 is the 29 red-first cases §5 lists for I-1/I-2/I-4 plus the one case for I-2c, and the 5 skips are the same POSIX-only set as F1 |


The 5 skips at F1/F2 are the POSIX-only tests named by their markers; the count
`450` is test FUNCTIONS, so a parametrized case counts once per parameter set
entry.

## 2. Fresh install, and migration of a repo that HAS history

Recipe for both rows: `git init` a throwaway repo with one seed commit, run
`python <repo-source>/scripts/init_sync.py <repo>`, then
`python <repo>/.ai/scripts/sync_verify.py`.

| # | fact | measured |
|---|---|---|
| B2 | fresh install, verify rc | `0` |
| B2 | fresh install total line | `== 20/24 checks passed, 4 skipped ==` |
| B3 | hand count of `[PASS]` lines in that report | 20 — equals the numerator; the four `[SKIP]` lines are `registered project checks`, `path coverage`, `pin violation`, `role policy integrity`; 20 + 4 = 24 |
| B4 | a **genuine v2.0.0** tree (scaffolded by the `e692e73` installer) before upgrade | `== 14/14 checks passed ==`, rc 0, zero `[SKIP]` lines → 24 − 14 = 10 more checks in v2.1 |
| B5 | that v2.0 tree, committed, after `init_sync.py --migrate` | `== 21/24 checks passed, 3 skipped ==`, rc 0 |
| B6 | which line flips between B2 and B5 | `role policy integrity`: `SKIP(no-sha-pinned)` → `[PASS] … digests to the pinned 03f80ef052c5…(4899 bytes)` |
| B8 | a second `--migrate` on the same repo | rc 0; `already migrated (2.0.0 -> 2.1.0); verifying the recorded state and writing nothing.`; exactly 5 `[PASS] migrate verify …` lines; `git rev-parse HEAD` unchanged and `git rev-list --count HEAD` 3 → 3 |
| B9 | genuine v2.0 install committed then `--migrate` | rc 0, `13 path(s) committed`, no `.new` sidecar |
| B10 | genuine v2.0 install with `.ai/` NOT in HEAD then `--migrate` | rc 0, exactly 2 `[WARN] preserved customised script:` lines during the run plus 2 in the recap, sidecars `.ai/scripts/checkpoint.py.new` and `.ai/scripts/sync_verify.py.new`, and the post-migrate verify still reports the v2.0 shape because the install keeps running the OLD verifier |

**Re-measured at the B5 commit, after the false-green fixes** (same recipes,
same host, one foreground session): fresh install `== 20/24 checks passed, 4
skipped ==` at rc 0; genuine v2.0 tree before upgrade `== 14/14 checks passed ==`;
the same tree after `--migrate` `== 21/24 checks passed, 3 skipped ==`. No count
moved, so no figure in `CHANGELOG.md` was re-pinned to an unmeasured number.

## 3. Seeded violations

Recipe: throwaway repo, `init_sync.py`, one commit touching `src/core/engine.py`,
`protected_paths: ["src/core/*"]`, `governance.window_start_commit` set to the
commit before it.

| # | seeded condition | measured line (rc) |
|---|---|---|
| C1 | protected-path commit, zero authorizations | `[FAIL] path coverage: 1 uncovered of 1 protected touches: <0b30785e src/core/engine.py> -- no accepted authorization's `## Editable files` lists these paths …`, rc 1 |
| C2 | an ACCEPTED authorization whose list names a different path | byte-identical `[FAIL] path coverage:` line to C1, rc 1 |
| C3 | positive control: accepted record listing `src/core/*` | `[PASS] path coverage: 1 protected touches covered` |
| C4 | authorization pinning `CURRENT.md` | `[FAIL] pin violation: 1 forbidden pin(s): … pins CURRENT.md …`, rc 1 |
| C5 | two (then three) ACCEPTED authorizations live | `[FAIL] swarm boundary: 2 concurrent accepted authorizations (…): … one stage = one live authorization`, rc 1 |
| C6 | real shallow clone on this nt host (`git clone --depth 1 file://…`) | `[FAIL] path coverage: shallow/indeterminate history (true): …`, rc 1 |
| C7 | `is_shallow → UNKNOWN` | not reproducible with a real clone here; pinned only through F3's monkeypatched parametrization, whose assertion is the string `shallow/indeterminate history (unknown)` inside the evidence |

## 4. Dogfood in a throwaway clone — and what it does NOT prove

`git clone --no-hardlinks <this repo> <tmp>/clone` at `3546c08`, then
`init_sync.py`, `checkpoint.py --lock --agent …`, one authorization `.md` with a
fenced `## Governance` block, `--migrate`, `sync_verify.py`.

| # | fact | measured |
|---|---|---|
| D2 | `--migrate` while another agent holds the lock | rc 2, `MIGRATE REFUSED: the writer lock could not be acquired, and --migrate mutates tracked state`, nothing written |
| D3 | that clone right after `init_sync.py` + one accepted authorization | `== 21/24 checks passed, 3 skipped ==` |
| D4 | clone after `--migrate` + the covering authorization | `== 23/24 checks passed, 1 skipped ==`, the single SKIP being `registered project checks`, with `[PASS] path coverage: 0 protected touches covered` |
| D5 | `checkpoint.py --review-prompt` in that clone | rc 0; the three banners `== REVIEW PROMPT: AUTHORIZATION ==`, `… DIFF ==`, `… VERIFY ==` and no fourth |
| D6 | `--migrate` with git unreachable (PATH reduced to the Python dir) | rc 2; `MIGRATE REFUSED: git could not be asked what this tree's HEAD is …`; `Nothing was written: this run made no change to the install, the index, the config, or the history.` |

**This is not self-dogfooding.** No `.ai/` directory was created in this
repository's own root, and none exists there: the wave ran under a *clone's*
install. Spec §10.D as written asks for this wave to execute under the repo's own
`.ai/`, and that was NOT done. The rows above are substitute evidence for the
install/migrate/verify machinery only. Migrating this repository's own root — and
thereby making the shipped `path coverage` walk govern the history it is quoted
against — is wave-1c work.

## 5. The three false-greens closed after the final review, red-first

Each was measured failing on the pre-fix tree, then passing after the fix, in one
foreground session on this host.

| id | pre-fix measured behaviour (rc) | post-fix |
|---|---|---|
| I-1 | `governance.window_start_commit: "HEAD"`, a real protected commit, no covering authorization: `[PASS] path coverage: 0 protected touches covered`, rc 0 | `[FAIL] path coverage: window anchor is not a commit id: …`, rc 1. Pinned by `tests/test_coverage_walk.py::test_a_non_commit_window_anchor_fails_rather_than_governing_nothing` (6 anchors: `HEAD`, `main`, a 39-char id, a 40-char UPPERCASE id, `HEAD~1`, `not-a-rev`), all 6 red pre-fix, green post-fix, with `test_a_valid_anchor_still_governs_the_same_tree` as the non-vacuity control |
| I-2 | `protected_paths: ["SRC/*"]`, `protected_paths_case: "case-insensitive"`, commit touching `src/engine.py`, no covering authorization: `[PASS] path coverage: 0 protected touches covered`, rc 0 | `[FAIL] path coverage: 1 uncovered of 1 protected touches: <… src/engine.py>`, rc 1 — the candidate set now goes to git as `:(icase)SRC/*`. Pinned by `test_case_insensitive_policy_reaches_the_candidate_set` (red pre-fix) with `test_case_insensitive_policy_covers_once_the_record_says_so` as the green control |
| I-2b | a protected set matching no tracked file at all: `[PASS] path coverage: 0 protected touches covered`, rc 0 | `[WARN] path coverage: no tracked file matches any registered protected_paths pattern(s) …` plus `SKIP(void-protected-set)`. Pinned by `test_a_protected_set_matching_no_tracked_file_is_a_named_warn` (red pre-fix) with `test_a_protected_set_that_does_match_tracked_files_books_the_pass` as the control that still books the PASS |
| I-4 | two flat accepted records + one nested: `sync_verify` counted **3** (`[FAIL] swarm boundary: 3 concurrent accepted authorizations (…, sub/nested-stage.md)`) while `--review-prompt` printed `[AMBIGUOUS AUTHORIZATION] 2 accepted records`. Measured directly on the pre-fix `HEAD` scripts copied into a throwaway install | both readers now use `ai_common.authorization_records()`: the verifier counts 2 and the prompt names the same 2, and the nested record counts for nothing in either. Pinned by `tests/test_review_prompt.py::test_the_verifier_and_the_review_prompt_see_the_same_records` plus `tests/test_authorization_records.py::test_the_record_walk_is_flat_and_keeps_the_index_out` |
| I-2c | found by the re-review of the wave that fixed I-1/I-2, not by its implementer: when the void check itself could not answer (a `git ls-files` that times out or cannot read the index) the walk printed its `[WARN]` and fell through to `[PASS] path coverage: 0 protected touches covered`, rc 0 — a degradation reading as a verdict, which 4 forbids and `_protected_set_is_void`'s own docstring disclaims | `[WARN] …` plus `SKIP(void-check-unavailable): …`, and the line is never booked as a PASS. Pinned by `test_an_indeterminate_void_check_cannot_book_the_pass`, mutation-checked by reverting the arm: the test then fails on exactly `[PASS] path coverage: 0 protected touches covered`. `test_a_protected_set_that_does_match_tracked_files_books_the_pass` is the unpatched control that still earns the PASS |


## 6. The greps, stated as measured

Two greps decide whether D25 and D26 are fixed. Neither can be typed verbatim into
a tracked document without becoming its own hit — the same reason
`tests/test_version_and_naming.py` builds its pattern as `"MILE" + "STONES"` and
`tests/test_doc_wording.py` as `"token " + "budget"` — so they are named here by
what they match: the status file D25 deleted, and the two-word name the caps
carried before D26 renamed them to line budgets.

Measured on this tree, `git grep -n <pattern> -- .` returns 7 lines for the first
and 5 for the second. All 12 are inside `docs/superpowers/` — the prose that names
each defect and the §10.E acceptance line, which is the only place a copy of the
patterns has to live. That leaves 0 hits in every shipped surface (`scripts/`,
`templates/`, `SKILL.md`, `README.md`, `reference.md`, `CHANGELOG.md`), and 0 in
this file, which the two enforcing guards (`test_no_milestones_references_remain`,
`test_d26_unit_claim_is_clean_outside_templates`) do scan: both exclude
`docs/superpowers/` and neither excludes `docs/evidence/`, which is why this
section describes the patterns instead of quoting them. A repo-wide grep is
therefore NOT empty and no doc claims it is.

## 7. The in-repo install (spec 10.D), measured on `main` after PR #1

Recipe, on `3a5f2a9`: `python scripts/init_sync.py .`, then
`checkpoint.py --lock --agent qoder-cli`, then in `.ai/sync_config.json` set
`protected_paths` to `["scripts/*", "templates/*", "docs/evidence/*"]`,
`protected_paths_case` to `case-sensitive`, `role_policy_sha256` to the digest of
the installed `.ai/state/ROLE_POLICY.md`, and `governance.window_start_commit` to
`db091bdcea61daf73bb9cbcae446ef893490bd50` — the wave's own base, so the walk
judges real history rather than a fixture. The stage record's
`## Editable files` list was generated by the coverage walk itself, not typed.

| # | fact | measured |
|---|---|---|
| D1 | verifier run BEFORE any authorization record exists | `[FAIL] path coverage: 29 uncovered of 29 protected touches: <13c37d55 scripts/checkpoint.py>, <3546c089 scripts/init_sync.py>, <3a5f2a9c docs/evidence/wave1b-facts.md>, …`, `== 21/24 checks passed, 2 skipped ==`, rc 1 |
| D2 | same command after the accepted record | `[PASS] path coverage: 29 protected touches covered`, `[PASS] pin violation: 1 authorization record(s), no state file pinned`, `[PASS] role policy integrity: … digests to the pinned 03f80ef052c50475… (4899 bytes)`, `[PASS] swarm boundary: 1 accepted authorization(s) of 1 record(s) in the window`, `== 23/24 checks passed, 1 skipped ==`, rc 0 |
| D3 | registering the project's own suite as an `extra_checks` entry | `[PASS] python test suite: cmd \`python -m pytest tests/ -n 8 -o addopts= -q\` rc=0; 480 passed, 5 skipped in 58.10s` — the 5 POSIX-only skips are named inside the check's own evidence line, which is why they do not appear in the verifier's summary tail |
| D4 | final in-repo state, before the stage's own commit | `== 25/25 checks passed ==`, rc 0, and **no `[SKIP]` line at all** — the only install in this document with nothing unregistered |
| D4b | same command after `ddcf5f9` landed | `[PASS] path coverage: 30 protected touches covered`, `== 25/25 checks passed ==`, rc 0. The stage commit touches `docs/evidence/wave1b-facts.md`, which is a protected path it lists, so the count moves from 29 to 30. Expect it to move again: every later commit that touches a protected path adds one, and stays green only while an accepted record names that path — which is the mechanism, not a flaw in the number above |
| D5 | the lock record while held | `.ai/runtime/WRITER_LOCK.json`: `"agent": "qoder-cli"`, reason `wave1b dogfood: install this protocol into its own repository (spec 10.D)`, `acquired_at 2026-09-22T08:37:29+10:00`, `expires_at 2026-09-22T12:37:29+10:00`, `released_at null`, `epoch 1` |
| D6 | `checkpoint.py --review-prompt` on this install | rc 0, all three blocks produced: `== REVIEW PROMPT: AUTHORIZATION ==` at line 1, `: DIFF ==` at 76, `: VERIFY ==` at 6748, 6778 lines total. With a real governance window the DIFF block is the whole wave, not one commit |

What `25/25` does not mean: it is this repository's own registered check set, and
it says nothing about the limits named in the CHANGELOG — a second physical
machine, a real shallow clone, a review by a genuinely different model family —
none of which this install can reach. The record certifies scope and coverage of
what landed; it does not attest that each earlier step of wave 1b ran under a
lock, because it did not: the install postdates the wave.

| D7 | the review this stage's record promises | a fresh `general-purpose` subagent with no shared context reviewed the prepared tree before commit and returned LAND-AFTER-FIX with 0 Critical and 4 Important; its own recount of the walk agreed with the record's editable list exactly (19 non-merge + 10 merge-parent touches over 10 distinct paths). Same model family as the executor, so this is a separate-context review and not cross-family verification |

Found by doing this by hand, and logged in `.ai/state/DECISIONS.md` for wave 1c
rather than numbered here (the public defect table stops at D26, and an
identifier it does not define would be a dangling promise):

- `templates/AGENTS.md` tells every harness to run `git add -A && git commit &&
  git push` two lines above its own "never commit secrets" rule. A protocol whose
  startup document recommends a blanket add cannot claim the discipline it pins.
- `.ai/scripts/*.py` are the copies that actually govern, and they sit outside
  `protected_paths`. They are byte-identical to `scripts/*.py` today (verified by
  digest at this stage), so the exposure is prospective and unmonitored: a later
  wave can edit the source and leave the governing verifier behind while it
  reports green. Extending protected paths does not fix it — the fix is a drift
  check between the two, which is wave-1c work.
- The coverage walk unions the editable lists of every accepted record in the
  window, so a stage's authorisation keeps its force after the stage closes. It
  is inert here only because `.ai/` is not a protected path.
- Three required-but-unfilled files (`state/BLOCKERS.md`,
  `handoff/LATEST.md`, `handoff/NEXT_PROMPT.md`) PASS both the required-file and
  the budget checks as untouched templates. Presence is not content; that gap is
  the same shape as every other "the file exists, therefore green" claim this
  wave exists to close, and it is now filled in by hand for this stage.

Filling the file in also tripped `budget AGENTS.md` twice (69 lines, then 66,
against a cap of 65) — the budget check bites the author's own editorialising,
which is the point of it.
