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
| F4 | B5 fixes, same command as F1 | `479 passed, 5 skipped in 47.19s` (`created: 8/8 workers`, `8 workers [484 items]`): 450 → 479 is the 29 red-first cases §5 lists, and the 5 skips are the same POSIX-only set as F1 |

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

## 6. The greps, stated as measured

`git grep -n "MILESTONES" -- .` returns 7 lines and `git grep -n "token budget"
-- .` returns 5. All 12 are inside `docs/superpowers/` — the prose that names the
defect (D25/D26) and the §10.E acceptance line. A repo-wide grep is therefore NOT
empty and no doc claims it is; 0 hits exist in any shipped surface (`scripts/`,
`templates/`, `SKILL.md`, `README.md`, `reference.md`, `CHANGELOG.md`).
