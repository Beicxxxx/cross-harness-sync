# cross-harness-sync v2.1 — Wave 1 design: make the claims true before making them louder

Date: 2026-09-21
Status: approved design, awaiting implementation plan
Repo: https://github.com/Beicxxxx/cross-harness-sync (v2.0.0, MIT, ~1552 lines)
Author of changes: Claude (executor). Cross-family review: Qwen3.8-Max, 7 single-domain
reviewers (see §9).

## 1. Goal

Wave 1 has one goal: **the protocol's central promise — a second machine or a second
harness can safely take over this repo's work — must actually hold.** Everything in
this spec serves that.

A governance-enforcement feature was designed first and then largely withdrawn during
review (§9). What remains is deliberately small and deliberately honest about its own
boundary.

## 2. Positioning (defensible wording only)

What may be claimed:

> Protected paths are declared in config. Every commit touching one must be covered by an
> accepted authorization whose editable-file list includes that path. `sync_verify.py`
> walks `git log` and reports uncovered commits. This detects **omission** — a skipped or
> forgotten review survives in history for anyone who re-runs the verifier. It does
> **not** detect a fabricated record, because nothing binds a recorded name to an actual
> model invocation.

And the scope claim, which is the real one:

> This brings a path-scoped mandatory-independent-review gate into the situation where
> CODEOWNERS and Gerrit structurally cannot exist: no host-side admin rights (forked
> patches, self-hosted forges, private repos whose branch protection you don't own),
> and authors that are LLM agents with no forge identity to be a code owner of.

What must NOT be claimed:

- "enforced" — say **verifiable**, and state the omission/fabrication split.
- "proves coverage" — the walk is over a declared set of refs and fails closed when it
  cannot run, so it is bounded by repository history availability.
- novelty of the check itself. Gerrit submit requirements (`file` predicate +
  `user=non_uploader` + `distinctvoters`) and `Reviewed-by:`/DCO trailers have done
  path-scoped mandatory non-author review, auditable from history, for two decades.
  Naming those neighbours head-on is the credibility move, not hiding them.
- cross-**model-family** review as a decidable gate. See §6 — family is recorded, never
  gated, which is what the repo's own rule R5 already says ("record … without creating
  a gate").

## 3. Non-goals (wave 1)

npm packaging, `.agents/skills/` standard layout, CI, badges, tags/releases/CHANGELOG,
README rewrite, real token measurement, marketplace submissions, cryptographic
attestation (cosign/in-toto), commit-trailer protocol, overlapping-epoch forensics over
`git log -p` of the lock file.

Deferred items are waves 2–3 and depend on this wave being true.

**Plan split.** This wave is intended as two implementation plans, in order: **1a** =
defects D1–D26, which are independent per file and parallelizable; **1b** = §6 governance
plus §8 migration, which must come after 1a because the coverage walk depends on D3 and
D4 (config merge and unreadable-config handling) and migration depends on D22 (version
comparison). Writing 1b first would build it on the fail-open config path that D3/D4
describe.

## 4. Design law

**Degradation may only ever produce a named `WARN` or `SKIP`, never `PASS`.**
A "file absent, so skip" branch is legal only after proving that file is covered by a
necessity check elsewhere.

Derived from three independent review findings that each converged on the same class of
failure, and from measuring a premise that was assumed rather than tested:

- The `-n <cap>` history bound originally proposed to make auditing affordable was
  itself a fail-open surface (past the cap it emitted WARN). Measurement: cost is
  cap x files-per-commit, not history length — 20k-commit repo, `-n 500` = 15 ms, full
  walk = 191 ms. So the cap solved an unmeasured non-problem and created the hole.
  Bounding is therefore done by **pathspec**, with `timeout=` as the only guardrail.
- Every convenience escape hatch in a fail-closed tool becomes the vulnerability.

## 5. Wave 1a — defect fixes (26 items)

Severity: C = critical, M = major, m = minor. "Conv" = independently confirmed by more
than one reviewer.

| # | Sev | Defect | Fix | Regression test |
|---|---|---|---|---|
| D1 | C | `read_json` swallows `JSONDecodeError` → a merge-conflicted or corrupt `WRITER_LOCK.json` (which is deliberately git-tracked, so two machines locking is a *guaranteed* conflict) reads as `{}` = "no lock"; `--prime` prints "free to acquire" and both agents write state. `--unlock` then rewrites the conflicted file, erasing the evidence. **[conv]** | Distinguish *missing* from *unparseable*; unparseable/conflict-marked = HELD + loud error. Never rewrite a file that failed to parse. | write `<<<<<<<` into lock; `--prime` and `--lock` must report HELD/error, exit nonzero |
| D2 | C | `cmd_unlock` guards the holder only when `--agent` is passed, yet `cmd_prime`'s own output and `cmd_handoff` both instruct a bare `--unlock`. The tool teaches users to violate R1. | Require `--agent` (or `--force`) unless the record is expired; fix the two instruction strings to match. | A holds lock; B runs bare `--unlock` → refused |
| D3 | C | `merged.update(cfg)` is a shallow merge, so any project `budgets` entry replaces all five default caps and any `secret_files` list drops `.env`. Result: over-budget `CURRENT.md` and a tracked `.env`, reported green. **[conv]** | Deep-merge per namespace; report shadowed/added keys in the evidence line. | config with one `budgets` key → other caps still enforced |
| D4 | C | Invalid/absent `sync_config.json` → prints WARNING, falls back to defaults, exit code can still be 0. | "config unreadable" is a FAIL. Never silently govern with defaults. | malformed JSON → FAIL + rc 1 |
| D5 | C | `sync_verify.run()` uses `text=True`; on a cp936 Windows console a raw UTF-8 path raises in subprocess's reader thread, which dies, leaving `proc.stdout is None` with `returncode == 0` → an empty path set reads as "no protected paths touched" → **fail-open**. Live in shipped code. | Capture bytes; `decode("utf-8","surrogateescape")`; never treat `rc==0` as sufficiency. | force non-ASCII path + cp936 locale → check must FAIL/UNKNOWN, not pass |
| D6 | C | `secret_mirrors` FAILs when either side is missing, but mirrored secrets are git-ignored by design — so a fresh clone on machine two can never pass close-out. Permanent red on the protocol's main path. | SKIP-with-reason when neither side exists; FAIL only when both exist and key sets differ. | clone without `.env` → SKIP, not FAIL |
| D7 | C | `init_sync.py --force` overwrites live `CURRENT/TASK/DECISIONS/config` with empty templates while refreshing scripts. Destroys work state in a tool where `.ai/state` *is* the work state. | Scope `--force` to scaffolding; add `--scripts-only`; refuse to clobber a state file whose content is not template-identical. | non-template CURRENT.md + `--force` → preserved, warned |
| D8 | M | `write_json` uses `shutil.move`: atomic on POSIX, but Windows `os.rename` raises FileExistsError and it degrades to copy+unlink. | `os.replace`. | unit: replace over existing target |
| D9 | M | Temp name is `path.with_suffix(".tmp")` — two local concurrent writers clobber the same temp. | `tempfile.mkstemp` in the same dir + `os.replace`. | two writers, no torn file |
| D10 | M | `expires_at` missing or unparseable (incl. `...Z` on Python < 3.11) → `if expires and ...` falls through → **lock never expires**. (Naive-datetime `TypeError` is real but only reachable via hand-edited locks; fix both.) | Unparseable/naive → treat as expired + WARN; missing → FAIL. | lock with no `expires_at` |
| D11 | M | `check_secrets_ignored` calls `run()` unguarded → `TimeoutExpired` (600 s) and `FileNotFoundError` (no git) abort the whole verify with a traceback instead of one FAIL line. | Catch `(OSError, TimeoutExpired)` like `check_extra` already does; probe `shutil.which("git")` once up front. | PATH without git → clean FAIL lines |
| D12 | M | Non-git tree → every secret check reports `git check-ignore rc=128`; the diagnostic ("fatal: not a git repository") is on stderr and discarded. | Probe `git rev-parse --is-inside-work-tree` once; one clear FAIL. **Must stay FAIL** — converting to skip would fail open on secrets. | scaffold outside a repo |
| D13 | M | `sync_verify.py` and `init_sync.py` have no UTF-8 stdout guard (`checkpoint.py` does); printing `→`, `≤`, box characters or a non-ASCII `extra_checks` tail crashes on piped/redirected output — exactly how harness hooks capture it. | Same wrapper in both, plus `sys.stderr`, plus `errors="replace"`. | pipe through a pipe on Windows |
| D14 | M | `fnmatch.fnmatch()` applies `os.path.normcase` → lowercases and rewrites separators on Windows, so **one `protected_paths` config matches different file sets on the two machines**. | `fnmatch.fnmatchcase()` on forward-slash paths; record case policy in config. | mixed-case path, both platforms |
| D15 | M | Two linked worktrees on one machine each hold an independent on-disk `WRITER_LOCK.json`, so R1 breaks locally with no git involved. `resolve()` also follows symlinks, silently pointing ROOT elsewhere. | Assert `AI_DIR.parent == git rev-parse --show-toplevel`; detect worktree via `--git-common-dir != --git-dir`; refuse symlinked `.ai`. | linked worktree → loud refusal |
| D16 | M | Empty dirs don't survive clone and `cmd_handoff` never `mkdir`s `RUNTIME_DIR` (unlike `cmd_checkpoint`/`cmd_lock`) → first `--handoff` on a fresh clone crashes inside `write_json`. | `.gitkeep` for the runtime/handoff/state archive dirs + `mkdir` inside `write_json`. | clone then `--handoff` |
| D17 | M | `update_gitignore` appends all five lines whenever *any* is absent → duplicated `.env` and a second block in an already-configured repo; and it prints `len(missing)` rather than what it wrote. | Append only truly absent lines; report what was written. | repo already listing `.env` |
| D18 | M | `--no-agents-block` skips creating `AGENTS.md`, still writes a `CLAUDE.md` pointer to it, and leaves `"AGENTS.md": 65` in config → verify exits 1 forever, contradicting init's own "should be all green". | Under that flag, prune the budget entry and skip the CLAUDE.md pointer. Do **not** fix by making missing budgets a WARN: `AGENTS.md` is in no `REQUIRED_FILES`, so that would leave it wholly unmonitored. | `--no-agents-block` then verify → green |
| D19 | M | Root is derived as `Path(__file__).resolve().parent.parent`; running a script from outside `.ai/scripts/` silently targets the parent directory. | Assert `AI_DIR.name == ".ai"`, else refuse. | copy script to `scripts/` and run |
| D20 | m | `.env` with a BOM (Notepad) yields `'\ufeffFOO'` → false mirror mismatch vs the mac copy. | Read with `utf-8-sig`. | BOM'd `.env` pair |
| D21 | m | `extra_checks.cmd` typed `list[str]`, but a bare string works on Windows and raises on POSIX — asymmetric behaviour for the same config. | Validate and coerce with a clear error. | string cmd on either platform |
| D22 | m | `PROTOCOL_VERSION` in `init_sync.py` is never compared against `.ai/protocol/VERSION`, so installed-script/protocol skew is invisible. This is load-bearing for §8 (migration cannot detect skew it never recorded). | Compare and report; refuse on unknown-major. | VERSION hand-edited to `9.9.9` |
| D23 | m | Required-file lists are triplicated and already differ: `sync_verify.py`, `checkpoint.py --validate`, and `cmd_status` (which adds `ROLE_POLICY.md`/`NEXT_PROMPT.md` and drops `VERSION`). All three omit `ROLE_POLICY.md` as a *requirement* even though AGENTS.md and `cmd_status` treat it as central. | Single source in config; note `checkpoint --validate` must then read config, which is why D4 must land first. | drift test |
| D24 | m | `copy_file` has no source-existence check → traceback mid-install, leaving a half-scaffolded repo. | Check source, fail with a named line. | deleted template |
| D25 | m | `MILESTONES.md` is referenced in four places (`init_sync.py`, `checkpoint.py --prime`, `templates/AGENTS.md`, `templates/SYNC_PROMPT.md`) but never created and has no template — inviting exactly the "agents invent parallel MEMORY files" failure the repo forbids. | Delete the four references; the DECISIONS archive already serves L2. | grep for MILESTONES == 0 |
| D26 | m | Docs call the caps "token budgets" while the code counts `splitlines()`. Rename to **line budgets**. Residual, documented honestly: line count is a weak proxy for CJK state files, which the language rule permits. | Rename display strings only; every check `name` stays byte-identical. | grep assertion, see §10.E |

Rule for all of the above: keep every check `name`, CLI flag, and command string
byte-identical except where a rename is explicitly listed. `reference.md` documents hook
command strings that live in `.claude/settings.json` — outside `.ai/`, invisible to
migration — so a renamed command silently kills post-compaction re-priming.

## 6. Wave 1b — governance surface, reduced to what is decidable

**Kept (three checks + one feature).**

1. **§6 pin-violation check** — FAIL if an authorization's `Pinned baselines` lists
   `CURRENT.md`, `TASK.md`, `BLOCKERS.md` or `LATEST.md`. This is the only proposed check
   whose falsifiable fact lies entirely inside the repo. It also encodes a rule that came
   from a real incident (a pinned fast-changing state file stalled a routine edit).
2. **`ROLE_POLICY.md` becomes required, and its SHA-256 is pinned in
   `.ai/sync_config.json`** — changing the governance document then requires a config
   edit, and config edits are diffs a human actually reads. Anchor-string grepping is
   rejected: `"T1" in text` is satisfied by "R12", survives deletion of the §1 table body,
   and stays green while R3 is rewritten to permit same-family review.
3. **Omission coverage walk** — protected paths from config; a commit touching one is
   *covered* iff some accepted authorization whose existing `## Editable files` list
   includes that path. Coverage therefore **derives from a field the v2.0 template
   already has** rather than from a newly duplicated one. Union of two passes:
   `git log --no-merges --full-history --name-only -z --pretty=format:%H -- <pathspec>`
   and `git log --merges -m --first-parent --name-only -z -- <pathspec>`. The merge pass
   is not optional: a merge commit's own diff (conflict resolutions, evil merges) is
   precisely what an agent produces when two machines edit `CURRENT.md` under contention,
   and it never appears in a non-merge traversal. `-z` yields raw unquoted bytes; parse
   with `split(b"\0")`, never `splitlines()`.
4. **`checkpoint.py --review-prompt`** (new, positive feature) — emits exactly the
   authorization, the diff, and the verify output, and nothing else. This serves the
   documented loss ("reviewer re-ran the executor's full suite → wasted spend"; "reviewer
   read scope is hard") by making the honest path cheap, instead of adding another control.

**Every history query is three-valued: `TRUE | FALSE | UNKNOWN`, and `UNKNOWN` halts.**
Measured exit codes: `merge-base --is-ancestor` gives 0 / 1 / **128** for ancestor /
present-but-not-ancestor / *cannot determine* (shallow clone, absent object) — so
"cannot determine" is distinguishable, and any `rc == 0` boolean test collapses it into a
licence to clobber. Use `git cat-file -e <sha>^{commit}` for existence
(`rev-parse --verify <absent>` returns **0** and echoes the string, so it is useless as a
probe), `git rev-parse --is-shallow-repository` for shallowness, and
`git diff --name-status -z <base> <HEAD>` plus `git rev-list --count <base>..HEAD` for
lineage instead of inferring from a log walk. Store 40-hex SHAs (measured ambiguity at
20k commits: 1 collision at 7 chars, 9 at 6, 0 at 8); set `GIT_TERMINAL_PROMPT=0` and
`GIT_OPTIONAL_LOCKS=0`; treat `dubious ownership` as its own actionable error.

**Recorded but never gated: `executor_family`, `reviewer_family`, `executor_model`,
`reviewer_model`.** Rule R5 of this repo already states the answer — "record harness +
model + effort **without creating a gate**". Family equality is undecidable without a
registry nobody wrote (Kimi vs Moonshot? GLM vs ChatGLM? Cursor the harness vs Claude the
model?), and gating on it converts a one-bit lie into a two-bit lie that is easier to
tell. R3 therefore stays a prose rule interpreted by the human or the other model that
reads the diff; the verifier enforces R2 (identity), tier consistency, and omission.
Reusing ARIS's existing `executor_family`/`reviewer_family` field names keeps the two
toolchains' traces comparable instead of inventing a third convention.

**Dropped, with reasons recorded so nobody reintroduces them:** `covers_commits` and
`covers_paths` as new record fields — one fact would otherwise live in four places (two
record fields, `INDEX.md`, and `CURRENT.md`'s authorization pointer), reintroducing the
"JSON+MD+addendum triplet" that this repo's own template bans; the `-n` cap; anchor grep;
family as a gate; commit trailers (`Co-authored-by`/`Reviewed-by`) because a trailer's
referent is equally outside the repo while being weaker — amend/rebase drop them, the
audit trail splits out of `.ai/`, and the committer is the executor anyway;
overlapping-epoch forensics over the lock file's history.

Note what is **not** dropped: `.ai/state/authorizations/` itself. That directory is not a
new governance invention but the missing answer to a v2.0 design hole — the protocol
mandates "one stage = one authorization file" while `init_sync.py` gives instances no
canonical home, `REQUIRED_FILES` does not list them, and `reference.md`'s layout diagram
has no slot for them. Without a fixed location there is nothing for §6.1 or §6.3 to read.
`INDEX.md` is kept because the index-first idiom already exists in `DECISIONS_INDEX.md`.

**Governance record format, for the records that remain:** a `## Governance` heading whose
key/value pairs live inside a ```` ```governance ```` fenced block — the fence gives
unambiguous start/end and removes the nested-bullet, stray-line and continuation problem,
while staying stdlib-parseable and readable in a rendered diff. Required keys: `tier`,
`executor`, `reviewer`, `verdict`, plus `red_before_green` and `user_authorized` where
applicable. Contract details: split on the first `": "` only; keys are
`[a-z][a-z0-9_]*`; duplicate key is **fatal** (no last-wins) because this is audit data;
unknown keys are non-fatal so the schema stays forward-compatible; the only sanctioned
sentinels are `n/a` and `NOT_REPORTED`; a value matching `^<[^<>]*>$` with ASCII angle
brackets is an unfilled template and is fatal — applied only inside the fenced block, so
prose and Chinese angle punctuation (`《》〈〉`) are never scanned. Absent block in a legacy
document is a **named WARN, never PASS**.

## 7. Strictness and defaults

Default strict, per the owner's decision — and this survives review because after §6 the
strict checks are all intra-repo decidable and rarely red in normal use. `protected_paths`
defaults to **empty**, and that is not a weakening: with an empty list the coverage check
reports `SKIP(no-protected-paths)` by name rather than pretending to govern, and the
documented failure mode this avoids is the steady state predicted by review — "one honest
permanently-red week, then `protected_paths: []` and zero coverage".

Exit codes: 0 all green, 1 any FAIL, 2 usage error. Each check emits exactly one
`record(name, ok, evidence)` line with a stable name.

## 8. Migration (`init_sync.py --migrate`)

Records what v2.0 never recorded. Writes `.ai/protocol/MIGRATION.json`
(`from`, `to`, `started`, `completed`, `files_touched[]`), and re-running it is a
verifying no-op. Sets `governance.window_start_commit = HEAD` **only when history
exists**: zero commits, detached HEAD, or unparseable/unknown-major VERSION → refuse and
write nothing; `"NO_HISTORY"` is an explicit sentinel that reports `SKIP(no-history)`,
never `PASS`. Version comparison parses semver as a tuple, never string-compares
(`2.10.0` vs `2.1.0`), and `PROTOCOL_VERSION` vs `.ai/protocol/VERSION` per D22.
Detects in-place customized scripts by comparing HEAD blobs against v2.0 hashes embedded
in the migrator, refuses outright if `.ai/scripts/` has unstaged edits (unrecoverable),
and writes `.new` sidecars instead of overwriting on divergence; treats untracked files,
shallow truncation, and `.gitattributes`/`core.autocrlf` normalization as MODIFIED,
because byte comparison gives false positives there. Never guesses an existing
authorization location — a wrong guess fabricates an authoritative record source — so it
creates `.ai/state/authorizations/` and requires an explicit `--authorizations-dir` to
point elsewhere. Edits `sync_config.json` as **text** to preserve comments, deep-merging
new namespaces and refusing on invalid JSON (fixing it silently would drop the owner's
keys). Migration mutates tracked state, so it must itself hold the writer lock, and it
must exclude `WRITER_LOCK.json` from its own commit. The commit contains only `.ai/**`
plus a tagged message so it is revertible; the journal states what is *not* reversible
(appended `.gitignore` lines, the appended `AGENTS.md` managed block, any overwritten
customized file). Cross-machine double-migration is expected to conflict in
`.gitignore`, `AGENTS.md`, `VERSION`, and `sync_config.json`; `--ff-only` plus
no-force-push means the loser rebases by hand, so the migrator must be idempotent rather
than merely safe.

Known unsolvable, documented rather than worked around: retro-active per-repo anchor sets
(dropped anyway), customization detection when `.ai/scripts/` is untracked or history is
shallow (information genuinely absent), serializing migration across machines with no
server (the lock guarding it is itself a conflicting tracked file), and hook command
strings in `.claude/settings.json` which live outside `.ai/` and are invisible to
migration.

## 9. How this design was produced

Seven single-domain read-only reviewers, all dispatched on a different model family
than the executor (no subagent segment on this host reported a Claude model; the exact
tier could not be confirmed from session logs, so this does not claim which one),
dispatched in parallel from a shared written brief so they could not drift: blind defect
audit; adversarial verification of the executor's own 9 claimed defects; git-plumbing
feasibility (live measurements on git 2.55 / Windows / cp936); hostile design critique;
prior-art check; migration and back-compat audit; parse-contract design.

This satisfies the repo's own R2 and R5 — the author's self-check is corroborating
evidence, not the review. Material changes it forced: the enforcement-first framing was
replaced by defect-fixing-first; 4 of the executor's 9 defect claims were corrected
(one described an unreachable crash and missed the reachable bug on the same line; two
cited the wrong file; one proposed a fix that would have left `AGENTS.md` unmonitored);
the coverage walk survived only after being rebuilt three-valued and pathspec-bounded;
family-gating and commit trailers were withdrawn; the defect list grew 9 → 26; and the
`legacy-no-governance → PASS` default proposed by one reviewer was overruled as exactly
the silent-pass class this wave exists to remove.

## 10. Acceptance criteria

A. All 26 defects have a regression test that **fails against v2.0.0** first, with the
   first-fail output recorded in the PR description — R4 applied to this protocol's own
   development, which is also the strongest evidence artifact for a later submission.
B. `sync_verify.py` runs green on a fresh `init_sync.py` scaffold **cloned to a second
   machine** (D6 and D16 are the tests that this promise was never verified end to end).
C. A seeded-violation demo: commits touching a protected path with (no covering
   authorization / `tier: T1` claimed on a protected path / protected path present in no
   accepted authorization's editable-file list), each pasted with its FAIL line, plus a
   shallow-clone run showing `UNKNOWN → halt` rather than green.
D. The wave itself is executed under a real `.ai/` install of this protocol, with a lock
   record and a governance record naming executor and reviewer — described as "reviewed by
   a different model", not as "cross-family verified".
E. `grep -rn "MILESTONES" .` returns nothing; `grep -rn "token budget" .` returns
   nothing; every check name in the output is stable across the v2.0 → v2.1 diff except
   the two documented renames.

## 11. Open risks

The omission-only framing is weaker than what this wave started out claiming, and it is
the version that survives review; if a later design can bind a recorded reviewer name to
an actual model invocation without a server, §6 items can be revisited. Realistic
candidate: optional cosign attestation, explicitly out of scope here because it requires
keys and an operator.
