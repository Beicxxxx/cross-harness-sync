# Changelog

## v2.1.0 — wave 1d (the deferred queue, published and then worked), 2026-09-22

Wave 1c ended owing two kinds of debt: shipped behaviour it had named but not
changed, and a deferred list that existed only as `M-3, M-7..M-14` inside a
gitignored directory. Both are dealt with here, in that order — a queue a reader
cannot open is not a queue.

### What is now shipped

- **`governing copy` (check 10)** — the bytes that ran the report are compared to
  the bytes this checkout ships: every `.ai/scripts/*.py` must digest to its twin
  in `scripts/`. `path coverage` cannot answer this, because it asks whether an
  edit was *authorised*, and a record naming both walks authorises a mismatch as
  readily as a match. The comparison is discriminated structurally by
  `scripts/init_sync.py`, the one file in that directory the installer never
  copies, so an ordinary install gets `SKIP(not-source-checkout)` instead of a red
  it was never asked to satisfy, and a project that keeps unrelated code in a
  `scripts/` directory is not held to a comparison its install never made. It
  checks that what runs matches what is authored; it does not check that every
  authored file got installed, because that list lives in an installer that is not
  installed, and re-deriving it here would be a second promise to keep in step.
- **The runtime coverage window is now bound by the records that live in it.**
  Wave 1c gave the release face this and left the runtime walk holding the same
  hole: `governance.window_start_commit` is one config line, the walk's reach is
  exactly that line, and advancing it drops the commits before it out of the range
  — where they read as neither covered nor uncovered, because nothing looks at
  them. `_base_conflicts` answers for both faces now, and the runtime check reads
  the records *before* it walks, since an empty range is precisely what a narrowed
  anchor produces. Two exemptions, both about history: a `status: closed` record
  does not bind the window forever (re-anchoring at each new wave is the
  lifecycle), and a runtime record that declares no base bounds nothing — runtime
  records predate the field, and an accepted one cannot be edited to add a line it
  never carried. A stage that omits the line is unguarded at its own back edge,
  which `templates/AUTHORIZATION.md` now says to the person writing the record.
- **One predicate for "is this a commit id".** `checkpoint.py --review-prompt`
  accepted an uppercase hex anchor that `ai_common.window_is_valid` — the copy the
  verifier and the migrator both use — refused. Git resolves either spelling, so
  the two commands never disagreed about a commit; they disagreed about whether a
  recorded field says anything at all, and the review prompt diffed happily from a
  window the walk calls unreadable. `ai_common.is_full_sha` is the shape now, and
  `window_is_valid` is that or `NO_HISTORY`.
- **Two shipped arms that no case reached now have cases.**
  `_migration_commit`'s post-commit listing path — rewritten in wave 1b precisely
  because a failed `git show` used to print `0 path(s) committed` while the
  containment recheck silently did not run — shipped without a test. One
  suite assertion demanded the substring `"git log"` inside an error string, which
  survives a reason that lost every fact it should carry; it now demands git's own
  echo of the offending argument and the exit code.
- **Published figures re-measured, not carried forward.** A default install ends
  `== 21/27 checks passed, 6 skipped ==`; after `--migrate`,
  `== 22/27 checks passed, 5 skipped ==` (both measured at `7b44120` on this host,
  and pinned by name in `tests/test_authorization_records.py`, which is the
  tripwire that pulls whenever a check arrives). The sixth skip is
  `governing copy`, and it names the reason above.

### What this wave did not fix, in print

`docs/evidence/wave1d-queue.md` is the tracked queue: fifteen rows, each with what
the item actually is, and a status column that distinguishes *closed with a case
that was red first* from *looked at and left* from *cannot be resolved*. Row Q13
is the last of those: wave 1c published "14 minors" and named seven ids that no
tracked file — and no file in the private ledger either — defines anywhere, so no
row claims to be one of them. Q15 is new to this wave: the listing guard reads
exit status, so a `git show` that exits 0 and writes nothing still reads as a
clean commit, which is the exact shape this protocol made illegal in
`extra_checks` and has not yet made illegal here.

### Operator note

`--migrate` refuses at exit 2 while another agent holds the writer lock. The
refusal names the holder, its expiry, and the three remedies that exist
(wait / coordinate / `--force --reason "<why>"`, which records the takeover in the
lock itself) — measured at `7b44120`, output quoted in the queue's Q7 row. Wave
1b's ledger filed that as a missing "release the lock first" hint; there is no
such hint to add, because releasing someone else's pen is not a thing the protocol
offers. What *is* owed and now written down is the behavior itself, in
`SKILL.md`'s upgrade section, which it already had.

## v2.1.0 — wave 1c (two faces of authorisation, and the placeholders the
installer owns), 2026-09-22

One release-document entry per shipped change is this file's rule, and wave 1c
broke it: `git diff --name-only 0bc4d7f5..aecd536 -- scripts templates README.md
SKILL.md reference.md tests` answers 22 files and this file said nothing about
them. That is the same omission the protocol exists to catch, committed by the
wave that wrote the warning, so the entry is written here — sourced from
`docs/release-authorizations/2026-09-22-wave1c-product-changes.md`, whose own base
is `0bc4d7f5`, and every behaviour below is still shipped on the tree this file
describes.

### What shipped

- **The release face and the runtime face are separate authorities.** `templates/`
  and `scripts/` ship to other people; they are authorised in
  `docs/release-authorizations/` and guarded by `tests/`, never by a record under
  `.ai/state/authorizations/`, which governs one repository. Registering the
  release paths in `protected_paths` let the repository that happens to *host* the
  product certify its own publication by writing a note in its own state
  directory — which is what wave 1b's dogfood did to its own `scripts/` and
  `templates/`, green, in a run whose every check passed.
- **`release authorization`** walks `release_window_start_commit..HEAD` over
  `release_paths` and requires an ACCEPTED release record's `## Editable files`.
  Its own review then found the gate was advisory where it claimed to be a wall,
  twice over: an unreadable record sat *under* a coverage PASS (named only inside
  that PASS's own text), and the anchor was one config line nobody compared to
  anything. Accepted records must now state their own `window_start_commit:`, an
  anchor past a live record's base is a FAIL, an unreadable record is a FAIL, and
  a zero-touch window with nothing accepted is `SKIP(quiet-window-unanchored)`
  rather than `0 pairs covered`. The pass after that found the new rule binding a
  *finished* stage's base to the window forever, so it applies to live records —
  the same `verdict`/`status` split as `swarm boundary`, and the same reason.
- **`verdict` and `status` are different fields, because they answer different
  questions.** `verdict: accepted` made a record the authority over the commits it
  names *and* said the stage was still live, so a repository that finished a second
  stage had two accepted records and `swarm boundary` went red forever — with the
  only exit being to rewrite the finished record's verdict, which retracted its
  coverage and made its own commits read as unauthorised. `status: open|closed`
  answers liveness alone, read by the boundary and the review prompt and
  deliberately not by the coverage walk. What `status` cannot do is protect a
  reader from a lie: a false `closed` costs nothing, so the reviewer is the check
  and the field only makes the claim visible.
- **`unfilled template slots`**: `required <file>` asks whether a state file exists
  and `budget <file>` asks how long it is, so a verbatim template copy answered
  both and printed PASSes — including for a `ROLE_POLICY.md` whose authorship line
  still read `by <who>`, in a file that is digest-pinned. The installer now
  resolves the slots only it can know (project name, remote, commit identity from
  the repository's own `--local` config, the Adopted line) and the verifier reports
  the rest.
- **Three instructions that shipped their own bug.** `templates/AGENTS.md` ordered
  `git add -A && git commit && git push` two lines above its rule against
  committing secrets. `templates/ROLE_POLICY.md` made a different model family a
  requirement at T2/T3 in R3 while R5 said family is recorded and never gates, and
  `TASK.md`/`CURRENT.md`/`NEXT_PROMPT.md` restated the same unconditional
  requirement in the files every agent fills in. R3/R5 is resolved as
  *cross-family is the preference, same-family is accepted where a second family
  is unreachable, and the record must say which it got* — and `SKILL.md`/R5 say
  "reviewed by a different model" only when one did.
- **A global git identity no longer leaks into a stranger's `AGENTS.md`.** The
  first cut of the slot resolver read `git config user.name`, which resolves local
  → global, so on a machine whose global identity is an institutional address the
  installer wrote that address into a repository that had never chosen it and
  reported the slot as resolved. It reads `--local` only now, and a missing local
  value stays missing. The hermetic test HOME could not see this, which is why the
  first cut passed its own suite; the case that pins it injects `GIT_CONFIG_GLOBAL`
  so the fallback cannot return unreported.
- **Section 7 of the role-policy template is dropped with a `WARN`**, not filled
  in. It asks for project boundaries the installer cannot know; inventing them for
  someone else's repository is shipping an instruction as if it were an answer.

### What wave 1c left standing, and said

Nothing above makes a review happen. The verifier detects omission, not
fabrication — a `[PASS]` cannot tell an honest record from an invented one — the
writer lock is advisory, `status: closed` is a self-report the boundary believes,
and an accepted record never expires inside its window. The releases also
published no cross-family attestation: this host's session log carries one model
field for every segment, so the records say `NOT_REPORTED` rather than guess.

## v2.1.0 — wave 1b (governance + migration), 2026-09-21

Wave 1b ships the governance surface of spec §6 and the migration of spec §8 on
top of wave 1a's correctness fixes. Canonical defect count for this release
line, stated once and used everywhere: 27 found, 26 fixed in wave 1a, D14 fixed in wave 1b.
The spec's §5 table
(`docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md`) is the
only authority for that number; no count in a commit message on this branch is
quotable.

### What is now shipped

- **`.ai/state/authorizations/` has a canonical home.** `init_sync.py` installs
  `INDEX.md` there, the required-file list names it, and `reference.md`'s layout
  diagram has a slot for it — the three holes spec §6 recorded for v2.0, which
  mandated "one stage = one authorization file" while giving instances nowhere
  to live.
- **Omission coverage walk** (`path coverage`): `protected_paths` comes from
  config, and every commit in `governance.window_start_commit..HEAD` that
  touches one must appear in some ACCEPTED authorization's own
  `## Editable files` list. Two `git log` passes (non-merge `--full-history`,
  merge `-m --first-parent`), `-z` raw bytes, and every history question
  three-valued — `UNKNOWN` halts at a named FAIL instead of borrowing the line
  an empty log would have printed. What this makes **verifiable** is *omission*:
  a skipped or forgotten review survives in history for anyone who re-runs the
  verifier. It does not detect a fabricated record, because nothing binds a
  recorded name to an actual model invocation.
- **Pin violation** (`pin violation`) — spec §6.1: an authorization that pins
  `CURRENT.md`, `TASK.md`, `BLOCKERS.md` or `LATEST.md` is a FAIL. This is the
  rule that came out of a real stall, and the only new check whose falsifiable
  fact lies entirely inside the repo.
- **Role-policy SHA integrity** (`role policy integrity`):
  `.ai/state/ROLE_POLICY.md` is digested against the `role_policy_sha256`
  pinned in `.ai/sync_config.json`, so rewriting the governance document now
  requires a config edit — a diff a human actually reads. No digest pinned is
  the named `SKIP(no-sha-pinned)`, never a PASS. Anchor-string grepping was
  rejected for the reason spec §6.2 gives: it stays green while the rule body
  is rewritten.
- **N1 swarm gate** (`swarm boundary`): more than one ACCEPTED authorization
  live in the window is a FAIL that names the files, because one stage = one
  live authorization. The gate **names and refuses the configuration in the
  report**; it does not prevent concurrent writes by an agent that never takes
  the writer lock, which is and stays advisory.
- **`checkpoint.py --review-prompt`**: the reviewer's read scope as one command —
  the active authorization, the diff, and the verify output, under the banners
  `== REVIEW PROMPT: AUTHORIZATION ==`, `== REVIEW PROMPT: DIFF ==`,
  `== REVIEW PROMPT: VERIFY ==`, and nothing else.
- **`init_sync.py --migrate`** (spec §8): the config keys, the role-policy pin,
  the window anchor, the authorization index, a `.ai/protocol/MIGRATION.json`
  record and a `.ai/protocol/MIGRATION.md` journal naming what a revert cannot
  undo, committed under `chore(cross-harness-sync-migrate)`. A re-run verifies
  and writes nothing.
- **D14**: `fnmatch` case/separator normalisation behind the new config key
  `protected_paths_case`, so a protected-path list means the same thing on a
  case-insensitive host as on a case-sensitive one. The matcher the deferral
  was waiting for now exists, which is what made the fix load-bearing.

### Measured at `3546c08` and re-measured at HEAD, on this host (Windows nt, Python 3.14.5)

Every figure below was produced in one foreground session on 2026-09-21, and
each one is re-measurable from a clone: the log-by-log detail is in
`docs/evidence/wave1b-facts.md` (tracked), which names the command, the tree and
the exact line for every number used here. The raw session transcripts additionally live
under `.superpowers/sdd/2026-09-21-cross-harness-sync-v2.1-wave1b-governance-migration/evidence/`,
which is gitignored and therefore is not evidence a reader can reach.

| Figure | Value |
|---|---|
| `python -m pytest tests/ -n 8 -o addopts=""` | `450 passed, 5 skipped` at `3546c08`. The first fix commit for the three false-greens below, `9937e0a`, measured **`2 failed, 477 passed, 5 skipped`**: the tracked evidence file it added quoted the two D25/D26 grep patterns verbatim and tripped the two wording guards that scan `docs/` outside `docs/superpowers/` (see §6 of that file for why the patterns cannot be typed here). At HEAD, after that and the `void-check-unavailable` fix: `480 passed, 5 skipped`, same 5 POSIX-only skips, 30 test cases added for the three false-greens plus one more for the arm the re-review caught, each red-first |
| Fresh install into a temp git repo, then `sync_verify.py` | `== 20/24 checks passed, 4 skipped ==`, rc 0; the `[PASS]` lines hand-counted to 20, the `[SKIP]` lines to 4. Re-measured at this commit after the B5 fixes: the same line, the same rc |
| The same repo carrying a **genuine v2.0.0 install** (scaffolded by the `e692e73` installer and committed), after `--migrate` | `== 21/24 checks passed, 3 skipped ==`, rc 0 — `role policy integrity` flips from SKIP to PASS |
| A second `--migrate` on that repo | rc 0: `already migrated (2.0.0 -> 2.1.0); verifying the recorded state and writing nothing.` then 5 `[PASS] migrate verify …` lines; `git rev-parse HEAD` unchanged and `git rev-list --count HEAD` 3 → 3 |
| That v2.0 install verified **before** any upgrade | `== 14/14 checks passed ==` — ten checks fewer than v2.1, and not one `[SKIP]` line |
| Seeded: a commit touching `src/core/*`, zero authorizations | `[FAIL] path coverage: 1 uncovered of 1 protected touches: <0b30785e src/core/engine.py> …`, rc 1 |
| Seeded: an ACCEPTED authorization whose list names a different path | the same `[FAIL] path coverage:` line, rc 1 — a record being present is not the same as it covering |
| Seeded: an authorization that pins `CURRENT.md` | `[FAIL] pin violation: 1 forbidden pin(s): … pins CURRENT.md …`, rc 1 |
| Seeded: two ACCEPTED authorizations live at once | `[FAIL] swarm boundary: 2 concurrent accepted authorizations (…): SKILL.md declares concurrent swarms out of scope, and one stage = one live authorization`, rc 1 |
| Shallow history | a real `git clone --depth 1 file://…` **on this nt host**: `[FAIL] path coverage: shallow/indeterminate history (true): the bounded walk cannot certify coverage of window f2b030fe..HEAD`, rc 1 |
| The void check itself cannot answer (`git ls-files` fails on a governed tree whose window is quiet) | `[WARN] path coverage: the registered set could not be matched against the tracked files (…)` then `[SKIP] path coverage: SKIP(void-check-unavailable): …`, and no `[PASS] path coverage:` line at all. Before this commit's fix the same tree printed `[PASS] path coverage: 0 protected touches covered`, rc 0 — the degradation-reading-as-a-verdict shape §4 forbids, caught by the re-review of the commit that fixed the two above rather than by its author |
| `is_shallow → UNKNOWN` | not reproducible with a real clone here; measured through B1's monkeypatched parametrization `tests/test_coverage_walk.py::test_the_shallow_or_indeterminate_halt_is_pinned_on_this_host[TRUE-True]` / `[UNKNOWN-True]` / `[FALSE-False]`, 3 passed. B1's real-clone test `test_a_real_shallow_clone_halts_the_walk` skips on this host with `posix-only test, running on nt` and is CI-gated; the manual clone above is the host-local substitute. |
| Dogfood in a throwaway clone of this repo | `== 23/24 checks passed, 1 skipped ==` with `[PASS] path coverage: 0 protected touches covered`, `[PASS] pin violation: 1 authorization record(s), no state file pinned`, `[PASS] role policy integrity: .ai/state/ROLE_POLICY.md digests to the pinned 03f80ef0…`, `[PASS] swarm boundary: 1 accepted authorization(s) of 1 record(s) in the window`. Superseded by the in-repo install below; kept because it measures a *clone's* default install, which is what a new user gets |

**Spec 10.D: this repository now runs under its own protocol, installed after the
merge.** `python scripts/init_sync.py .` landed `.ai/` in the repo root, the
writer lock was taken, `scripts/`, `templates/` and `docs/evidence/` were
registered as protected paths, the role-policy digest was pinned, and the
governance window was set to this wave's own base commit — so the coverage walk
judges the 29 real protected touches of wave 1b against one accepted stage
record, whose editable-file list the walk itself generated. Before that record
existed the same command printed `[FAIL] path coverage: 29 uncovered of 29
protected touches` at rc 1; after it, `[PASS] path coverage: 29 protected touches
covered`. With the project's own suite registered as an `extra_checks` entry the
in-repo run reaches `== 25/25 checks passed ==`, rc 0, with no `[SKIP]` line at
all — the only install in this file that registers nothing to be skipped about.

That is the honest ceiling of the claim: the install **postdates** the wave, so it
certifies what shipped and cannot attest that each earlier step ran under a lock
— wave 1b was executed while this repo had no `.ai/` at all, and no record here
says otherwise. Filling the installed files in by hand surfaced one new defect,
logged in `.ai/state/DECISIONS.md` for wave 1c: `templates/AGENTS.md` tells every
harness to run `git add -A && git commit && git push` two lines above its own
"never commit secrets" rule. Full rows, including the live lock record and the
`--review-prompt` output on a real window, are in §7 of
`docs/evidence/wave1b-facts.md`. One number there is stage-relative on purpose:
the walk reported 29 protected touches before this stage's own commit and 30
after it, because that commit touches a protected path the record lists. Each
later commit that touches one adds another, and it stays green only while an
accepted record names that path — that is the mechanism working, not a stale
figure.

**Re-measured after the final whole-branch review.** Three false-greens the
reviewer measured on this host are closed here, each red-first: a
`governance.window_start_commit` that is not a commit id (`HEAD`, `main`, a short
prefix) printed `[PASS] path coverage: 0 protected touches covered` over real
protected work and now FAILs by name; `protected_paths_case: "case-insensitive"`
reached only the authorization side of the comparison, so `["SRC/*"]` governed
nothing while `glob_match` said the file was protected, and the candidate set now
goes to git as `:(icase)`; and `sync_verify` and `--review-prompt` scanned the
authorizations directory with two different walks, so a record could be counted by
one and invisible to the other. A protected set that matches no tracked file is now
a named `[WARN]` plus `SKIP(void-protected-set)` instead of a PASS. The counts in
the table above did not move: a fresh install re-measured
`== 20/24 checks passed, 4 skipped ==` at rc 0, a genuine v2.0.0 install re-measured
`== 14/14 checks passed ==` before upgrade and `== 21/24 checks passed, 3 skipped ==`
after `--migrate`.

A default install is `== 20/24 checks passed, 4 skipped ==`, not 24/24. The four
named skips are `registered project checks`, `path coverage`
(`SKIP(no-protected-paths)`), `pin violation` (`SKIP(no-authorizations)`) and
`role policy integrity` (`SKIP(no-sha-pinned)`), and each says which of the two
possible reasons it took. `rc == 0` remains a verdict you may not stop reading
at.

### Release notes

**A genuine v2.0.0 install's first `--migrate` is not a silent refresh, and
what it prints depends on whether the install is in HEAD.** Both branches
measured:

- `.ai/scripts/` committed and byte-identical to the released v2.0 blobs → the
  scripts are refreshed and each replacement is named, e.g. `NOTE replaced:
  .ai/scripts/checkpoint.py (HEAD is the released v2.0.0 blob, so no hand edit
  is in the line being overwritten) - \`git diff HEAD^
  .ai/scripts/checkpoint.py\` names what went`. No `.new` sidecar.
- `.ai/scripts/` not in HEAD — never committed, or hand-edited; from inside the
  repo the two cannot be told apart — is the fail-safe branch: one
  `[WARN] preserved customised script:` line per script, the shipped copy
  written beside it as `.ai/scripts/checkpoint.py.new` and
  `sync_verify.py.new`, and the install left running the OLD verifier. Its
  report then stays `== 14/14 checks passed ==` after a migration that exited 0
  — ten v2.1 checks never ran, including all four governance checks. Review the
  sidecars and replace them by hand, then re-run `--migrate`; read
  `MIGRATION.md`, which names what a revert cannot undo.

**`--migrate` exits 2 when git is unreachable** instead of guessing whether the
tree is a repository: `MIGRATE REFUSED: git could not be asked what this tree's
HEAD is, so this run cannot tell a repository from a plain directory - and the
two answers send the migration in opposite directions`, with the actionable line
`` `git` is not on PATH, so this tree's history cannot be read at all `` and
`Nothing was written: this run made no change to the install, the index, the
config, or the history.` The same refusal (rc 2, nothing written) applies while
another agent holds the writer lock: `--migrate` takes its own
`init-sync-migrate` lock identity, so the agent holding the pen blocks the
migration on purpose.

### Limitation F7 — the version witness is self-referential

`.ai/protocol/VERSION` and the `PROTOCOL_VERSION` constant compiled into the
installed `checkpoint.py` / `sync_verify.py` are two files in the same tree an
agent can edit. Editing the stamp and the installed constant **together**
re-certifies the `protocol version matches installed scripts` line: there is no
signing key and nothing outside the checkout to corroborate against. The same
applies across the whole governance surface — `executor:` and `reviewer:` are
recorded strings, and `role_policy_sha256` only proves the document matches the
digest the config itself carries, so pinning and record can be edited as a pair.
A cross-model review of this protocol's own history is therefore
**corroborating, not proof**: it catches omission and accident, and it cannot
catch a coordinated edit. Spec §2 and §11 state this as the design stance; §11's
open risk is precisely that closing it needs something outside the repo (an
optional attestation with keys and an operator), which wave 1 excludes.

## v2.1.0 — wave 1a (defect fixes), 2026-09-21

Wave 1a is a correctness release: it fixes defects in the v2.0 scripts rather
than adding governance. **27 defects were found, 26 were fixed in wave 1a, and
D14 is the only deferral, to wave 1b, because the glob-matching code it applies
to does not exist yet** (quoted from the spec's §5 table — `docs/superpowers/specs/
2026-09-21-cross-harness-sync-v2.1-design.md` — which is the only authority for
that number; no count in a commit message on this branch is quotable, and two of
them are known to be wrong: `664bd67` states 21 where 18 was measured, and
`ec505e3` carries inferred per-file counts).

Every number below was regenerated in one final run at one pinned revision, and
says so next to it.

| Figure | Value | Measured at |
|---|---|---|
| Test suite, `python -m pytest tests/ -n 8 -o addopts=""` | `324 passed, 3 skipped`, no warnings block — no elapsed time is quoted here, because the one that was (`24.92s`) reproduced on no second run: re-runs measured 20.4-21.7 s at that revision and 22-28 s since, so a single figure is host load, not evidence | `d5aee6e` (counts); lane Y re-measured `340 passed, 3 skipped in 28.25s` at `ef749b9` |
| Fresh install into an empty git repo, then `sync_verify.py` | `== 18/19 checks passed, 1 skipped ==`, rc 0 | `d5aee6e` |
| Same install cloned to a second absolute path | `== 18/19 checks passed, 1 skipped ==`, rc 0 | `d5aee6e` |
| Tracked text still claiming the caps count tokens | 0 files — the two template hits were swept after this row was measured | `c288a52` |

Lane Q (the `extra_checks` `FAIL:`-tail demotion and the per-entry budgets
funnel) did not move the install's totals: a fresh install of its tree verified
`== 18/19 checks passed, 1 skipped ==` at rc 0 and the same install cloned to a
second absolute path printed the same line at rc 0, so the two rows above still
hold as printed; its own suite line is `341 passed, 3 skipped` (one test
function added), measured with the same command.

The one-line shape a reviewer sees on a default install never changes to
"everything passed": a default install registers no `extra_checks` and no
`secret_mirrors`, so it prints one or more named `[SKIP]`s forever (a wave-1a
default install printed exactly one; this release prints four, and the figure is
the `== 20/24 checks passed, 4 skipped ==` line quoted above). `rc == 0` is
not a verdict you can stop reading at.

### Development history — one commit inside this range is red

`584d7f3` ("fix(sync_verify): decisions_file and budgets keys cannot leave the
checkout") is **red on its own**: `60 failed, 264 passed, 3 skipped in 24.67s`,
measured at that sha in a fresh `git clone` with
`python -m pytest tests/ -n 8 -o addopts=""`. Its parent `3cd9036` measures
`324 passed, 3 skipped` and its child `2284fe6` `324 passed, 3 skipped` in the
same clone and the same command, and HEAD measured `340 passed, 3 skipped` before
this lane's tests landed, so the *fix* is fine and only the commit is not: one
lane's hunk set was split with `git apply --cached` and just the final tree was
gated, which is the risk `lane-Z2-report.md` "Concerns: 2" disclosed without
pricing. The 60 failures were not diagnosed one by one, and this note does not
claim to know which of them was which — only that the tree at that sha is not
the tree the tests were written against. Nothing is rewritten over it — the
branch's convention is additive commits and nothing here is pushed — so
`git bisect` will stop at `584d7f3`, and a reader of `git log` should learn that
from here rather than discover it. The same note covers `bc48332`, whose subject
names only the VERSION cross-check while one hunk of it also carries
`protect_stdio()`'s phantom-PASS fix; reverting "just the version check" reverts
that too.


### Breaking change — read before upgrading an existing install

Adopting wave 1a **without wave 1b's `--migrate` breaks both entry scripts on
every existing v2.0 install**: `checkpoint.py` and `sync_verify.py` now
hard-exit `2` with `[FAIL] install layout: ai_common.py is missing from
.ai/scripts/` unless `.ai/scripts/ai_common.py` is present, and v2.0 never
installed that file. The blast radius is wider than the plan originally said —
`checkpoint.py` too, not only `sync_verify.py` — and it includes private repos
the owner never re-runs the installer on.

The wave-1a-era workaround was one command per install:

```bash
python scripts/init_sync.py <repo> --scripts-only
```

It refreshes `.ai/scripts/` and `.ai/protocol/VERSION`, creates the tracked
`.gitkeep` placeholders for the empty protocol directories, appends the
`.gitignore` exception that makes them addable, names every script it replaces
with a `NOTE replaced:` line, and touches no state file, no `sync_config.json`,
no template, no `AGENTS.md` and no `CLAUDE.md`. It needs no `--force` and leaves
`.gitignore` consistent — but it is a refresh, **not** a migration: no
`MIGRATION.json`, no window-start commit, no reconciliation of hand-customized
scripts, no authorization-directory discovery. Those are exactly what wave 1b's
`--migrate` now ships — see the wave-1b section above.

### What changed (user-visible)

**The install and its upgrade path.** `--scripts-only` now does what its `--help`
always claimed. `--force` on `init_sync.py` refreshes only files still untouched
since their template and prints `KEEP (edited)` for files the caller wrote in;
`--clobber` overwrites those too; `--no-agents-block` drops the `AGENTS.md`
budget row instead of leaving the run permanently red; `--force` is refused with
`VERSION MISMATCH: …` (exit 1) when the installed `protocol/VERSION` is newer or
unparseable, so a stale skill checkout can no longer downgrade an install.
`.gitignore` is updated append-only, never re-blocked, and on the
`--scripts-only` path as well as the full one.

**Versions are compared, not assumed.** `.ai/protocol/VERSION` is stamped with
the installer's own `PROTOCOL_VERSION` (now `2.1.0`, previously a v2.0 stamp on
a v2.1 tree), the two are compared as parsed tuples, and the verifier reports
`protocol version readable`. The stamp is the *protocol* version, not the
skill's release version, and the two are not conflated anywhere in this release.

**Budgets are line budgets.** The check was `check_token_budgets` and the code
counts `splitlines()`; it is now `check_line_budgets` and the docs say line
budgets. Every printed check name (`budget <path>`, `FAILED:` lines) stayed
byte-identical — the rename is display and documentation only. A line is a weak
proxy for tokens in CJK state files, which this protocol permits; real token
accounting is a wave-2 measurement, not a wave-1 claim.

**Installs that cannot work are refused, loudly.** A linked git worktree, a
`.ai` reached through a symlink or a Windows junction, an install below the
repository root, and a layout git cannot describe are refused at exit 1 with a
message naming the `--force --reason` escape and the split it costs. The refusal
covers the state writers, not just `--lock`: `--handoff` and the bare
checkpoint classify the checkout before writing a byte. This is a documented
boundary, not support — and it bounds the multi-machine promise, because the
lock is a tracked file that only coordinates writers sharing one checkout's
history.

**The lock stopped being a suggestion in the places it claimed to be one.**
`--unlock` requires `--agent` (exit 2 without it, exit 1 if the lock is not
yours); `--force` requires `--reason` (exit 2 without it) and records the
takeover in the tracked `WRITER_LOCK.json`; `--force` without `--reason` no
longer depends on which branch the layout check happens to take. An
unparseable or conflict-marked lock record is HELD, never free, and is never
rewritten — `--force --discard-lock` is the only way to abandon one. What did
**not** change: the state-writing commands (`--handoff`, bare `checkpoint.py`)
still print a named `WARN …` and continue at exit 0 when another agent holds the
lock. They accept a concurrent writer; they do not reject one, and no copy of
this documentation claims otherwise.

**The verifier's silence is now distinguishable from its verdicts.** A config
that cannot be read is a FAIL, not a shrug and a default. `extra_checks` that
exit 0 having written nothing are a named `SKIP`, not a PASS. A secret mirror
present on one side only is a FAIL naming the missing side; both absent is the
named `SKIP` it should have been. `install layout` is booked as a `[PASS]` line
when it passes, so a report that never mentions the gate did not run it.
`checkpoint.py --validate` answers from the same required-file list and the same
floor the verifier uses, instead of a private seven-entry copy that omitted
`ROLE_POLICY.md`.

**Output that survives a Windows console.** Shipped output is ASCII-safe:
`checkpoint.py` emits a localized timezone name only when it is ASCII and the
UTC offset otherwise; subprocess plumbing captures bytes and decodes with
`surrogateescape` instead of trusting the console code page; `os.replace` and a
per-writer temp name replaced the two Windows-specific file races.

**Two promises were removed rather than fixed.** A milestone log named in four
shipped places and created by none (defect D25) — a file nothing writes invites
exactly the parallel-MEMORY-file failure this protocol forbids — is gone from
the shipped texts, and `DECISIONS` + `DECISIONS_INDEX` remain the L2 layer.
And the unmettable gate — the instruction to run `sync_verify.py` until the
report read clean, in the quickstart, in the managed block installed into every
`AGENTS.md`, in `--prime`, and in `.ai/SYNC_PROMPT.md` — is replaced everywhere
with the gate that can actually be met: no `FAILED:` line, a named `[SKIP]`
acceptable, silence not.

### What wave 1a deferred — and what has since landed

- **Shipped by wave 1b** (see the section above for each one's measured
  output): **`--migrate`** (§8) with its migration record, window-start commit,
  customized-script reconciliation and authorization-directory discovery;
  **D14**, the `fnmatch` case/separator normalisation, which needed the
  `protected_paths` matcher to exist first; and **the `protected_paths` coverage
  walk** (§6) plus `checkpoint.py --review-prompt` — the headline scope of the
  project, path-scoped independent review where CODEOWNERS and Gerrit
  structurally cannot exist. The two install rows in the table at the top of
  this section are wave-1a measurements of the wave-1a tree; a wave-1b default
  install prints `== 20/24 checks passed, 4 skipped ==`, and the same install
  after `--migrate` prints `== 21/24 checks passed, 3 skipped ==`.
- **Cross-machine verification.** The two-clone acceptance in
  `tests/test_second_machine.py` varies git author identity, HOME, and a
  registered `secret_mirrors` pair across a push/pull on one host; it is not
  cross-machine verification. Cross-machine handoff (a second host, a second
  locale and code page, real credentials, non-default `core.autocrlf`) has not
  been measured in wave 1a. Committer identity, note, is pinned to one fixture
  identity by the harness, so even the author-side half is author-only.
- **The symlink half of D15** cannot be exercised on this host without symlink
  privilege: the refusal is read from code and exercised for `linked-worktree`
  only. Stated as a coverage hole, not as a pass.
- **Real token measurement**, npm packaging, CI, and the `.agents/skills/`
  layout (spec §3 non-goals).

### What this release does not claim

`sync_verify.py` detects **omission, not fabrication**. It proves a required
state file, a line budget, a secret-ignore rule or a tracked placeholder is
missing; those go red on every run until fixed, and that part is enforced. It
cannot prove a review happened, that a recorded agent identity is honest, or that
a handoff describes work that occurred. The T1/T2/T3 review tiers and writer
discipline are **recorded** — installed, existence-checked, digested against the
pinned `role_policy_sha256`, and nothing more. The wave-1b coverage walk over
declared paths is bounded by repository history availability — a shallow or
indeterminate history halts with a named FAIL rather than certify coverage —
and it remains unable to bind a recorded name to a model invocation without a
server, or to survive a coordinated edit of the record and its witness (limitation
F7 above). That limit is the design stance, not a missing feature.
