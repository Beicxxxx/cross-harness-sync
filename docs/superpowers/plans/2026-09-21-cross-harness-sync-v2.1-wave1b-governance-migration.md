# cross-harness-sync v2.1 Wave 1b — Governance Records, Migration, D14 glob, N1 gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the parts of v2.1 that wave 1a deliberately deferred because their code did not exist yet — the `.ai/state/authorizations/` governance records and the three decidable checks that read them (omission coverage walk, pin-violation, ROLE_POLICY integrity), `checkpoint.py --review-prompt`, `init_sync.py --migrate`, the D14 forward-slash glob matcher, and the N1 swarm-boundary gate — each as a check that can only ever PASS on evidence it actually gathered.

**Architecture:** Add one shared, stateless foundation to `ai_common.py` (a governance-block parser, a case-policy glob matcher, and three-valued git-history probes), because every downstream lane needs the same primitives and a second copy is the D5 fail-open class this protocol exists to end. Then grow `sync_verify.py` with the four governance checks, add `--review-prompt` to `checkpoint.py`, and add `--migrate` to `init_sync.py`. The migration is last because §8 makes it create `authorizations/`, seed `governance.window_start_commit`, and record a `role_policy_sha256` that only exist once the governance layer is defined.

**Tech Stack:** Python 3.9+ stdlib only in anything shipped under `scripts/` (`fnmatch`, `hashlib`, `subprocess`, `json`, `re`, `argparse`, `pathlib`). `pytest` is a dev dependency only. git CLI via `ai_common.run_git`, output captured as bytes and decoded with `surrogateescape`.

**Spec:** `docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` — this plan argues from §4 (design law), §6 (governance surface), §7 (strictness/defaults), §8 (migration), §9 (how it was reviewed), §10 (acceptance). **Executors must read both files.** The wave-1a sibling plan is `docs/superpowers/plans/2026-09-21-cross-harness-sync-v2.1-wave1a-defect-fixes.md`; its Global Constraints carry forward and are reproduced below.

**Repository root (this wave):** `F:\Papers and Projects\cross-harness-sync` is the durable home repo, connected to `origin` `https://github.com/Beicxxxx/cross-harness-sync.git`. Wave 1a was verified at HEAD `8b0c328`; this branch (`v2.1-wave1b-governance-migration`) starts there. The old session path `C:\Users\Beichen\Documents\Qoder\2026-09-21\5bcb99ce\cross-harness-sync` is a read-only insurance copy — do not edit it.

## Global Constraints

Applies to every task. Values copied verbatim from the spec and the wave-1a plan (which still binds).

- stdlib only in anything shipped under `scripts/`. `pytest` may appear in `tests/` and `requirements-dev.txt` only.
- Python floor 3.9. Do not rely on `datetime.fromisoformat` accepting a trailing `Z` (needs 3.11); normalize explicitly (the `parse_ts` pattern at `checkpoint.py:347` is the reference).
- **Never treat `returncode == 0` as sufficient.** A child that exited 0 having written nothing is a named SKIP (see `sync_verify.check_extra`), never a PASS.
- **A degradation may produce only a named `WARN` or `SKIP`, never `PASS`** (spec §4). "File absent so skip" is legal only if that file is proven covered by a necessity check elsewhere.
- **Every history query is three-valued: `TRUE | FALSE | UNKNOWN`, and `UNKNOWN` halts** (spec §6). "Cannot determine" (rc 128, shallow, missing object, no git) is an error state, never folded into a boolean licence to proceed.
- **`family` is recorded, never gated** (spec §6, repo rule R5). Reuse the existing ARIS field names `executor_family`, `reviewer_family`, `executor_model`, `reviewer_model`; do not invent a third convention and do not branch on family equality.
- **D14 is now in scope and is the ONLY place its constraint is honoured:** use `fnmatch.fnmatchcase()` on forward-slash (`as_posix`) paths — `fnmatch.fnmatch()` calls `os.path.normcase()`, which lowercases and rewrites `/` to `\` on Windows, so one `protected_paths` config would match different file sets on the two machines. Record the case policy in config.
- **The governance fenced block is the whole record contract** (spec §6): split on the first `": "` only; keys match `[a-z][a-z0-9_]*`; a duplicate key is **fatal** (no last-wins — this is audit data); unknown keys are **non-fatal** (forward-compatible); the only sanctioned sentinels are `n/a` and `NOT_REPORTED`; a value matching `^<[^<>]*>$` with ASCII angle brackets is an unfilled template and is **fatal, applied only inside the fenced block** so prose and Chinese `《》〈〉` are never scanned. **An absent block in a legacy document is a named WARN, never PASS.**
- **`protected_paths` defaults to empty and that is not a weakening** (spec §7): with an empty list the coverage check reports `SKIP(no-protected-paths)` by name rather than pretending to govern.
- **Migration mutates tracked state, so it must itself hold the writer lock, exclude `WRITER_LOCK.json` from its own commit, contain only `.ai/**`, be idempotent (a re-run is a verifying no-op), edit `sync_config.json` as text to preserve shape, and refuse outright if `.ai/scripts/` has unstaged edits** (spec §8). Never guess an existing authorization location: create `.ai/state/authorizations/` and require an explicit `--authorizations-dir` to point elsewhere.
- Keep every existing check `name`, CLI flag, and command string byte-identical. No wave-1b renames are planned. `reference.md` documents hook command strings that live in `.claude/settings.json` — outside `.ai/`, invisible to migration — so a renamed command silently kills post-compaction re-priming; do not rename any hook string.
- **Exit codes** (spec §7): `0` all green, `1` any FAIL, `2` usage error / no verdict. Each check emits exactly one `record(name, ok, evidence)` line with a stable name.
- Every task ends with the R4 evidence step: paste the actual failing-output line from the red step into the commit message, and **only measured numbers** (wave-1a count ruling) — no suite total ever quoted from a commit body or an inference.

### Smoke-harness seam (a wave-1a convention this wave must honour, not re-break)

`tests/test_harness_smoke.py::test_fresh_scaffold_verifies_all_green` asserts every `[...]` check line is `[PASS]` OR the single `allowed_skip = ("[SKIP] registered project checks:",)`; its own comment says "a SECOND skip are still breaks". **Task B1 makes a default install emit additional named SKIPs** (`SKIP(no-protected-paths)`, and `role policy integrity` when no sha is pinned). B1 MUST extend that `allowed_skip` tuple in its own commit to name the new legitimate skips — that is the sanctioned "re-scope the assertion in your own commit, never weaken it silently" move from the wave-1a strictness-guard ruling. It is NOT permitted to delete the assertion or turn the fresh-install check into a bare `rc==0`. B1 owns the `test_harness_smoke.py` edit; no other lane and B4 must not touch it.

## Hard process rules carried from wave 1a (apply to execution, not authoring)

The subagent-driven execution of THIS plan must honour every rule the wave-1a ledger recorded:

1. **A brief is a file on disk; the prompt only points at it.** Never put the brief content in the dispatch prompt.
2. **Each lane owns exactly one source file; the concurrency ceiling is file contention, not CPU.** Fan out genuinely file-disjoint lanes in one message (the user's standing preference is maximal parallelism — many subagents + multi-thread CPU); serialise only where two tasks edit the same file, and name that constraint.
3. **Review packages must be path-scoped:** `git log/diff <base> <head> -- <the batch's paths>` into a hand-named file (lanes interleave on one branch; a range pulls siblings). Say in the reviewer prompt why it is not a range.
4. **Every dispatch carries an explicit tool-call budget and** "report ⚠️ UNVERIFIED rather than continue exploring" (a wave-1a reviewer crashed at 1.27M tokens after 16 calls; set budgets from the artifact count).
5. **Tests run in the foreground with a generous timeout; never background a test run and end the turn.**
6. **Commit messages carry only measured numbers.** Regenerate every suite total from one pinned revision in B4; the defect count stays `27 found, 26 fixed in wave 1a, D14 deferred to wave 1b` until D14 actually lands in B0, and no submission copy may claim "all green" or "rejects swarm configurations" before N1 is real.
7. **`git add` lists explicit paths only, never `-A`;** never leave the tree dirty; scratch/temp dirs live outside the repo, addressed by absolute path.
8. **Do not adopt wave 1a alone on an existing install** without 1b's `--migrate`: the new `ai_common.py` `SCRIPT_MAP` hard-exits on any v2.0 install that lacks it, breaking BOTH `checkpoint.py` and `sync_verify.py` there. This is exactly why `~/.agents/skills/cross-harness-sync` (verified pure v2.0 — `scripts/` has no `ai_common.py`, no `protocol/VERSION`) is synced only once, atomically, after this wave, as a separate human-approved release step.

### Test-harness idioms (verified against `tests/helpers.py` + `tests/conftest.py` — do not invent others)

- Import primitives: `from helpers import SCRIPTS, git, make_repo, run_python, scaffold`.
- Fixtures `ai_repo` (scaffolded throwaway repo under `tmp_path`), and `cp` / `sv` which are **script Paths** (`.ai/scripts/checkpoint.py`, `.ai/scripts/sync_verify.py`), **not callables**. Invoke them as `res = run_python(sv, [], cwd=ai_repo)`; assert on `res.lines` (the non-blank stdout lines) and `res.rc`.
- Run a checkpoint command: `run_python(cp, ["--review-prompt"], cwd=repo)`.
- Commit fixture state with `git(repo, "add", "src/keep.md")` and `git(repo, "commit", "-m", "...")` — `helpers.git` refuses any target inside REPO_ROOT, so only ever act on a `make_repo(tmp_path)`/`ai_repo` tree.
- To reach `ai_common`'s new pure functions from a test, load it by path the way `test_required_files.py` does (`importlib.util`), e.g. a module-local `_load("ai_common")`, then call `ai.glob_match(...)`, `ai.parse_governance_block(...)`, `ai.git_ancestor(repo, ...)`.

## File Structure

Files grouped by owner so parallel lanes cannot collide. New symbols are pinned here because a lane's implementer sees only their own task.

**Foundation — `scripts/ai_common.py` (Task B0, one owner, the critical-path head):**
- Modify: `scripts/ai_common.py` — add `import re` (top-level; it is NOT imported there yet), `import fnmatch`, `import hashlib`; append the governance parser, the D14 glob matcher, and the three-valued git probes; add constants near `PROTOCOL_VERSION` (`ai_common.py:171`). All stateless; import-safe on 3.9.
- Create: `tests/test_governance_record.py`, `tests/test_glob_match.py`, `tests/test_tristate_history.py`

New public names produced by B0 (consumed by B1/B2/B3):
- `parse_governance_block(text: str) -> tuple[dict | None, str | None]` → `(fields, err)`. `(None, None)` = no ` ```governance ` block (caller raises a named WARN, never PASS). `({}, "reason")` = block present but fatal (duplicate key / unfilled `<placeholder>` / bad key / unclosed). `(fields, None)` = parsed. Keys of interest: `tier`, `executor`, `reviewer`, `verdict`, `red_before_green`, `user_authorized`.
- `glob_match(rel_path: str, patterns: list[str], case_sensitive: bool = True) -> bool` → D14, `fnmatchcase` on `rel_path.replace("\\","/")`; never `normcase`.
- `git_ancestor(root, ancestor: str, descendant: str) -> str`, `commit_exists(root, sha: str) -> str`, `is_shallow(root) -> str` — each `"TRUE"|"FALSE"|"UNKNOWN"`.
- `log_paths(root, args: list[str], pathspec: list[str]) -> tuple[list[str] | None, str | None]` → `(paths, None)` on a clean rc 0 (parse by splitting the raw bytes on `b"\x00"`, never `splitlines()`), else `(None, reason)`.
- `AUTHORIZATIONS_SUBDIR = "state/authorizations"`, `SHA_HEX_LEN = 40`, `SHA256_HEX_LEN = 64`.

**Governance checks — `scripts/sync_verify.py` (Task B1, one owner):**
- Modify: `scripts/sync_verify.py` — add config keys `protected_paths` (list, REPLACE, entries validated repo-relative), `protected_paths_case` (str ∈ {case-sensitive, case-insensitive}), `authorizations_dir` (str, default `.ai/state/authorizations`), `role_policy_sha256` (str, 64-hex), `governance` (dict, deep, holding `window_start_commit`) into `DEFAULT_CONFIG`/`KEY_SHAPES`/`MERGE_POLICY`; add `check_coverage_walk`, `check_pin_violation`, `check_role_policy_integrity`, `check_swarm_boundary`, wire into the `main()` check-tuple loop (`sync_verify.py:989`).
- Modify: `tests/test_harness_smoke.py` — extend `allowed_skip` for the new legitimate fresh-install SKIPs (see the seam note; B1-only edit).
- Create: `tests/test_coverage_walk.py`, `tests/test_pin_violation.py`, `tests/test_role_policy_integrity.py`, `tests/test_swarm_boundary.py`

**Review prompt — `scripts/checkpoint.py` (Task B2, one owner):**
- Modify: `scripts/checkpoint.py` — add `--review-prompt` to the `main()` mutex group (`checkpoint.py:1147`) and a `cmd_review_prompt` emitting exactly {active authorization, diff, verify output} and nothing else.
- Create: `tests/test_review_prompt.py`

**Migration + records on disk — `scripts/init_sync.py` + templates + the required-file flip (Task B3, one owner):**
- Modify: `scripts/init_sync.py` — add `--migrate` / `--authorizations-dir` and the migration flow (MIGRATION.json, `governance.window_start_commit`, `role_policy_sha256`, customization detection vs embedded v2.0 hashes, `.new` sidecars, writer-lock-held, `.ai/**`-only commit, idempotent re-run).
- Modify: `scripts/ai_common.py` **is NOT edited in B3** — but B3 is the ONLY task that adds `.ai/state/authorizations/INDEX.md` to `DEFAULT_REQUIRED_FILES` (`ai_common.py:47`), which means B3 edits `ai_common.py` too. Therefore **B3 must run after B0's `ai_common.py` commit lands** (single-owner file rule), and B3's `ai_common.py` edit is confined to that one list entry.
- Modify: `templates/sync_config.json` — set the same five keys to their honest defaults (empty `protected_paths`, `""` sha, `governance: {}`).
- Create: `templates/authorizations/INDEX.md`; extend `templates/AUTHORIZATION.md` with a `## Governance` section carrying a ` ```governance ` block; make `init_sync` create `authorizations/INDEX.md` on fresh installs too.
- Modify: `tests/test_required_files.py` — flip the `assert not any("authorizations" in rel ...)` pin (line 108) to require the INDEX, in the same commit as the creation, keeping B3 atomic.
- Create: `tests/test_migrate.py`, `tests/test_authorization_records.py`

**Closure (Task B4, one owner, after B1/B3):**
- Modify: `CHANGELOG.md`, `README.md`, `SKILL.md`, `reference.md` — move §6/§8 items from "wave 1b / refresh not a migration / not enforced" prose into "shipped", restate the canonical count as `D14 fixed in wave 1b`, pin the new fresh-install check count, add §10.C/D evidence and the F7 "what this proves" disclosure.
- Create: `docs/superpowers/evidence/` artifacts referenced by §10.

## Dependency / lane graph

```
B0 (ai_common.py foundation)  ── first and green; the only owner of ai_common.py until B3,
        │                        and every lane imports parse_governance_block / glob_match /
        │                        git_ancestor / log_paths / commit_exists / is_shallow.
        ├── B1 (sync_verify.py + test_harness_smoke.py) ──┐  file-disjoint, run
        ├── B2 (checkpoint.py)                            ──┤  CONCURRENTLY (3 lanes,
        └── B3 (init_sync.py + templates/ + ai_common.py    │  3 owners, distinct files)
                required-list entry + test_required_files.py)┘ ← B3 also needs B1's config
                                                                 KEYS DEFINED; share this
                                                                 contract, B1 owns DEFAULT_CONFIG,
                                                                 B3 owns the template values.
                 └── B4 (closure) — after B1 and B3 green; full run, fresh-install +
                                    --migrate evidence, doc sync, count pin.
```
`--migrate` (B3) cannot precede the governance layer because it writes `governance.window_start_commit`, `role_policy_sha256`, and creates the records B1 reads — the coupling flagged as verified. B0 → {B1, B2, B3} → B4; B1/B2/B3 are the parallel wave.

---

## Task B0: Governance foundation in `ai_common.py` (parser, D14 glob, three-valued git)

The one task every other task imports. Additions are stateless functions/constants appended to `scripts/ai_common.py`. Red-before-green for D14 and the parser contract; the git probes reuse existing `run_git` (bytes-safe, scrubs `GIT_LOCATION_VARS`, sets `GIT_TERMINAL_PROMPT=0`/`GIT_OPTIONAL_LOCKS=0` via `os_environ_with_git_silence()` at `ai_common.py:275`).

**Files:** Modify `scripts/ai_common.py`. Test `tests/test_glob_match.py`, `tests/test_governance_record.py`, `tests/test_tristate_history.py`.
**Interfaces:** Consumes `run_git`/`decode`/`GitResult`. Produces `parse_governance_block`, `glob_match`, `git_ancestor`, `commit_exists`, `is_shallow`, `log_paths`, `AUTHORIZATIONS_SUBDIR`, `SHA_HEX_LEN`, `SHA256_HEX_LEN`.

- [ ] **Step 1: Write the failing glob test (D14 red)**

`tests/test_glob_match.py`:

```python
import importlib.util
from helpers import SCRIPTS

def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

ai = _load("ai_common")

def test_d14_glob_is_case_sensitive_and_separator_stable():
    pats = ["docs/superpowers/plans/*.md"]
    assert ai.glob_match("docs/superpowers/plans/2026-09-21-x.md", pats) is True
    assert ai.glob_match("Docs/Superpowers/Plans/2026-09-21-x.md", pats) is False
    assert ai.glob_match("docs\\superpowers\\plans\\a.md", pats) is True
    assert ai.glob_match("DOCS/a.md", ["docs/*.md"], case_sensitive=False) is True

def test_d14_glob_never_applies_normcase():
    assert ai.glob_match("a/B/C.md", ["a/B/*.md"]) is True
    assert ai.glob_match("a/b/c.md", ["a/B/*.md"]) is False
```

- [ ] **Step 2: Run it, confirm FAIL** (`AttributeError: ... 'glob_match'`).
Run: `python -m pytest tests/test_glob_match.py -o addopts="" -q`

- [ ] **Step 3: Implement parser + glob + git probes**

Add `import fnmatch`, `import hashlib` and confirm `import re` is present at the top of `ai_common.py` (it is not yet — add it), then append:

```python
SHA_HEX_LEN = 40
SHA256_HEX_LEN = 64
AUTHORIZATIONS_SUBDIR = "state/authorizations"

_GOVERNANCE_OPEN = "```governance"
_GOVERNANCE_CLOSE = "```"
_GOV_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_GOV_UNFILLED = re.compile(r"^<[^<>]*>$")  # ASCII angle brackets only


def parse_governance_block(text):
    """(fields, err) for a ```governance fenced block (spec §6).

    (None, None): no block (legacy) -> caller WARNs, never PASSes.
    ({}, why): a block that cannot be trusted.
    Sentinels n/a / NOT_REPORTED are the only sanctioned empty values; a value
    like `<placeholder>` is fatal, but only inside the fence, so Chinese 《》 survive.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.strip().lower().startswith(_GOVERNANCE_OPEN))
    except StopIteration:
        return None, None
    fields, seen, j = {}, set(), start + 1
    while j < len(lines) and not lines[j].strip().startswith(_GOVERNANCE_CLOSE):
        raw = lines[j]; j += 1
        if not raw.strip():
            continue
        key, sep, val = raw.partition(": ")
        if not sep:
            return {}, f"governance line has no ': ' separator: {raw!r}"
        key = key.strip(); val = val.strip()
        if not _GOV_KEY.match(key):
            return {}, f"governance key is not [a-z][a-z0-9_]*: {key!r}"
        if key in seen:
            return {}, f"governance key repeated (audit data, no last-wins): {key!r}"
        seen.add(key)
        if _GOV_UNFILLED.match(val):
            return {}, f"governance value is an unfilled placeholder: {key}: {val!r}"
        fields[key] = val
    if j >= len(lines):
        return {}, "governance block is never closed"
    return fields, None


def glob_match(rel_path, patterns, case_sensitive=True):
    norm = rel_path.replace("\\", "/")
    for pat in patterns:
        p = pat.replace("\\", "/")
        if case_sensitive:
            if fnmatch.fnmatchcase(norm, p):
                return True
        elif fnmatch.fnmatchcase(norm.lower(), p.lower()):
            return True
    return False


def _tri(res, yes_when):
    if res.timed_out or res.rc not in (0, 1):
        return "UNKNOWN"
    return "TRUE" if yes_when(res.rc) else "FALSE"


def git_ancestor(root, ancestor, descendant):
    res = run_git(root, ["merge-base", "--is-ancestor", ancestor, descendant], timeout=15)
    return _tri(res, lambda rc: rc == 0)


def commit_exists(root, sha):
    res = run_git(root, ["cat-file", "-e", f"{sha}^{{commit}}"], timeout=15)
    return _tri(res, lambda rc: rc == 0)


def is_shallow(root):
    res = run_git(root, ["rev-parse", "--is-shallow-repository"], timeout=15)
    if res.timed_out or res.rc != 0:
        return "UNKNOWN"
    return "TRUE" if res.out().strip() == "true" else "FALSE"


def log_paths(root, args, pathspec):
    """(paths, None) on a clean run else (None, why). `-z` => split bytes on NUL,
    never splitlines(); a non-zero / timed-out answer is a halt reason, not an
    empty set (spec §6: the walk is bounded by refs and fails closed)."""
    res = run_git(root, ["log", *args, "--name-only", "-z", "--", *pathspec], timeout=15)
    if res.timed_out:
        return None, "git log timed out"
    if res.rc != 0:
        detail = decode(res.stderr).strip().splitlines()
        return None, f"git log rc={res.rc}: {detail[-1][:160] if detail else 'no stderr'}"
    return [decode(b) for b in res.stdout.split(b"\x00") if b], None
```

- [ ] **Step 4: Run glob test to PASS.**
- [ ] **Step 5: Add `tests/test_governance_record.py` (absent-block → `(None,None)`; duplicate key fatal; `<placeholder>` fatal but `《作者>` survives; sentinels + unknown key forward-compatible) and `tests/test_tristate_history.py` (real 40-hex HEAD → `git_ancestor == "TRUE"`, `commit_exists == "TRUE"`; a well-formed-absent sha → `commit_exists == "FALSE"` and `git_ancestor == "UNKNOWN"` because is-ancestor rc 128 must not collapse to FALSE; `is_shallow` on a full clone → `"FALSE"`). Load `ai` by `_load("ai_common")`; build the repo with `make_repo(tmp_path)` + `git`.** Keep any shallow-clone end-to-end variant `@pytest.mark.posix`; unit-test `_tri` directly for the no-git/timeout branch (PATH fragility).
- [ ] **Step 6: Run B0 tests + regression pins:** `python -m pytest tests/test_glob_match.py tests/test_governance_record.py tests/test_tristate_history.py tests/test_required_files.py tests/test_version_and_naming.py -o addopts="" -q` → PASS (B0 changes no required-file list yet — that lands in B3).
- [ ] **Step 7: Commit** `git add scripts/ai_common.py tests/test_glob_match.py tests/test_governance_record.py tests/test_tristate_history.py` then commit with the D14 red line pasted. Measured counts only.

---

## Task B1: Governance checks in `sync_verify.py` (coverage walk, pin-violation, ROLE_POLICY, N1)

**Files:** Modify `scripts/sync_verify.py` and `tests/test_harness_smoke.py`; Test `tests/test_coverage_walk.py`, `tests/test_pin_violation.py`, `tests/test_role_policy_integrity.py`, `tests/test_swarm_boundary.py`.
**Interfaces:** Consumes B0 (`glob_match`, `git_ancestor`, `commit_exists`, `is_shallow`, `log_paths`, `parse_governance_block`, `AUTHORIZATIONS_SUBDIR`, `SHA_HEX_LEN`). Produces stable check names `path coverage`, `pin violation`, `role policy integrity`, `swarm boundary`.
**Config-key contract (B3's template MUST use exactly these):** `protected_paths: []`, `protected_paths_case: "case-sensitive"`, `authorizations_dir: ".ai/state/authorizations"`, `role_policy_sha256: ""` (empty → integrity SKIPs by name), `governance: {"window_start_commit": ""}` (`""`/`"NO_HISTORY"` → walk SKIPs by name).

- [ ] **Step 1: Failing coverage-walk tests.** Build config with a protected path + a real window SHA, touch the file, commit, seed authorizations, assert `[FAIL] path coverage` for an uncovered commit and `[PASS]` when an accepted authorization's `## Editable files` glob-matches it; empty `protected_paths` → `[SKIP] path coverage ... no-protected-paths`; `window_start_commit` absent → `[SKIP] ... no-window`. Use `res = run_python(sv, [], cwd=ai_repo)`; commit fixture state with `git(repo, ...)`.

```python
def _seed_auth(repo, editable, verdict="accepted"):
    p = repo / ".ai/state/authorizations/stage-x.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Authorization - stage-x\n\n## Editable files\n"
                 + "".join(f"- `{e}`\n" for e in editable)
                 + "\n## Governance\n```governance\ntier: T2\nverdict: "
                 + verdict + "\n```\n", encoding="utf-8")
```

- [ ] **Step 2: Failing pin-violation test** (seed an authorization pinning `CURRENT.md` → `[FAIL] pin violation`, spec §6.1's fully-intra-repo check).
- [ ] **Step 3: Failing ROLE_POLICY integrity + N1 swarm tests.** Empty `role_policy_sha256` → `[SKIP] role policy integrity`; matching sha → `[PASS]`; wrong sha → `[FAIL]`. Two non-expired `accepted` authorizations → `swarm boundary` is FAIL/WARN by name, never silent green (N1: SKILL.md declares concurrent swarms out of scope but the shipped code currently exits 0).
- [ ] **Step 4: Implement** config keys (into `DEFAULT_CONFIG` `:93`, `KEY_SHAPES`, `MERGE_POLICY`; `protected_paths` REPLACE + repo-relative validation via the existing `_is_repo_relative_path`; `governance` deep) and the four checks. `check_coverage_walk`: empty paths → SKIP(no-protected-paths); `window in ("", "NO_HISTORY")` → SKIP(no-window); `is_shallow == "TRUE"` → FAIL (halt); run both `log_paths` passes (`--no-merges --full-history --pretty=format:%H` since the window, and `--merges -m --first-parent`) — either returning `(None, why)` → `[FAIL] path coverage ... walk halted: {why}` (UNKNOWN halts); else an uncovered protected touch → FAIL naming the commits, covered → PASS. `check_pin_violation` scans each authorization's `Pinned baselines` for `CURRENT/TASK/BLOCKERS/LATEST`. `check_role_policy_integrity` uses `hashlib.sha256` of `.ai/state/ROLE_POLICY.md` vs the pinned sha. `check_swarm_boundary` counts non-expired accepted authorizations (>1 → FAIL by name). Wire all four into the `main()` loop at `:989`.
- [ ] **Step 5: Extend `tests/test_harness_smoke.py` `allowed_skip`** to name the new legitimate fresh-install SKIPs (see seam note). Do not weaken the surrounding assertions.
- [ ] **Step 6: Run:** `python -m pytest tests/test_coverage_walk.py tests/test_pin_violation.py tests/test_role_policy_integrity.py tests/test_swarm_boundary.py tests/test_harness_smoke.py tests/test_config_merge.py tests/test_config_errors.py -o addopts="" -q` → PASS (adding keys must not break the merge/error suite).
- [ ] **Step 7: Commit** (paste the coverage-walk red line; measured counts).

---

## Task B2: `checkpoint.py --review-prompt`

**Files:** Modify `scripts/checkpoint.py`; Test `tests/test_review_prompt.py`.
**Interfaces:** Consumes B0 `parse_governance_block`; uses `run_git`/`run_python`-equivalent for the verify subprocess and `git diff` for the window. Produces `--review-prompt` in the `main()` mutex group (`checkpoint.py:1147`).
- [ ] Step 1: failing test asserting the three sections appear (authorization / diff / verify output) and that the FULL suite was NOT re-run (a marker unique to running every `extra_checks` must be absent) — spec §6.4's point is making the honest review path cheap.
- [ ] Step 2: run to fail. Step 3: add `--review-prompt` flag + `cmd_review_prompt` (read the active authorization from `cfg["authorizations_dir"]` or the sole accepted one, `run_git(ROOT, ["diff", ...])` for the window, invoke `sync_verify.py` and embed its raw output; print exactly the three blocks). Step 4: run to pass. Step 5: commit.

## Task B3: `init_sync.py --migrate` + on-disk records (atomically with the INDEX required-file flip)

**Files:** Modify `scripts/init_sync.py`, `scripts/ai_common.py` (ONLY the one `DEFAULT_REQUIRED_FILES` entry at `:47`), `templates/sync_config.json`, `templates/AUTHORIZATION.md`, `tests/test_required_files.py`; Create `templates/authorizations/INDEX.md`. Test `tests/test_migrate.py`, `tests/test_authorization_records.py`.
**Runs after B0** (edits `ai_common.py`, single-owner rule). **Interfaces:** Consumes B0 `commit_exists`/`is_shallow`/`git_ancestor`; B1's config-key contract. Produces `.ai/protocol/MIGRATION.json`, config `governance.window_start_commit` (real 40-hex or `"NO_HISTORY"`), `role_policy_sha256`, `authorizations_dir`, `protected_paths: []`, and `.ai/state/authorizations/INDEX.md`.
- [ ] Step 1: red — `--migrate` on a repo with commits sets `window_start_commit` to the real HEAD 40-hex and writes a required INDEX; Step 2: red — zero commits / detached HEAD / unparseable VERSION → refuses, writes nothing, records `NO_HISTORY` (which yields B1 `[SKIP(no-history)]`, never PASS); Step 3: red — unstaged edits under `.ai/scripts/` abort the migrate; Step 4: red — a `.ai/scripts/*.py` whose HEAD blob differs from the embedded v2.0 hash produces a `.new` sidecar and does NOT clobber.
- [ ] Step 5: implement `run_migration`: acquire the writer lock (reuse the `checkpoint` lock contract, or a guarded local hold); `check_version_match` (`init_sync.py:96`) refuse unknown-major; create `authorizations/` + INDEX; edit `sync_config.json` **as text** (deep-merge new namespaces, preserve shape/comments, refuse on invalid JSON, using the `_splice_budget_line` byte-shape discipline in `init_sync.py`); compute and pin `role_policy_sha256`; write `.ai/protocol/MIGRATION.json` (`from`,`to`,`started`,`completed`,`files_touched[]`); a re-run is a verifying no-op; commit only `.ai/**` excluding `WRITER_LOCK.json` with a tagged message; journal the non-reversible appends (`.gitignore`, the `AGENTS.md` managed block). Fresh installs also create the INDEX (FILE_MAP path).
- [ ] Step 6: flip `tests/test_required_files.py:108` (`assert not any("authorizations" in rel ...)`) to REQUIRE `.ai/state/authorizations/INDEX.md` in `DEFAULT_REQUIRED_FILES`, in this same commit.
- [ ] Step 7: run `python -m pytest tests/test_migrate.py tests/test_authorization_records.py tests/test_required_files.py tests/test_second_machine.py tests/test_harness_smoke.py -o addopts="" -q` → PASS. `test_second_machine.py` already expects `.ai/state/authorizations/.gitkeep` (created at `init_sync.py:837`); confirm the fresh-install INDEX addition keeps it green (a second tracked file in that dir is fine).
- [ ] Step 8: commit. **B3 is atomic** (required-list gain + template + creation together) — do not split, or a fresh install goes red for a missing INDEX (the wave-1a T3 lesson).

## Task B4: Wave 1b closure — full run, count, docs, §10 evidence

**Files:** Modify `CHANGELOG.md`, `README.md`, `SKILL.md`, `reference.md`; Create `docs/superpowers/evidence/`. **Must not touch `test_harness_smoke.py` or `ai_common.py`** (owned by B1/B0).
- [ ] Step 1: `python -m pytest tests/ -n 8 -o addopts=""` **foreground**, generous timeout — record the true total (do not trust any earlier per-lane number).
- [ ] Step 2: fresh `init_sync` install AND a `--migrate` on a seeded v2.0-style tree; capture the new `== M/N checks passed, K skipped ==` line and hand-count `[PASS]` lines against the numerator (finding-F5 discipline). This is the wave's first end-to-end exercise of `--migrate` (wave 1a left it unexercised because the governance keys it seeds did not exist).
- [ ] Step 3: §10.C seeded-violation demo (a protected-path commit with no covering authorization, `tier: T1` claimed on a protected path, and a protected path absent from every accepted authorization's editable list — each with its FAIL line pasted) + a shallow-clone run showing `UNKNOWN → halt`, not green.
- [ ] Step 4: §10.D dogfood record (this wave run under a real `.ai/` install with a lock + a governance record naming executor and reviewer, described as "reviewed by a different model", NOT "cross-family verified").
- [ ] Step 5: restate the canonical count `27 found, 26 fixed in wave 1a, D14 fixed in wave 1b`; update the four docs that still call these items "wave 1b / refresh-not-migration / not enforced"; add the F7 self-referential-version-witness limitation to SKILL.md's "what this proves" list (spec §3 keeps attestation out of scope).
- [ ] Step 6: commit docs. **Do not push, open a PR, or sync `~/.agents/skills`** — the atomic skill-repo sync is a separate human-approved release step.

---

## Self-Review

**1. Spec coverage.** §6.1 pin-violation → B1 `check_pin_violation`. §6.2 ROLE_POLICY required + SHA → B1 `check_role_policy_integrity` (required-ness already in the floor from 1a; the SHA pin is added here) + B3 records the sha. §6.3 coverage walk → B1 `check_coverage_walk` + B0 `log_paths`/`glob_match`/tristate. §6.4 `--review-prompt` → B2. §6 record format + three-valued history → B0. §7 strictness/defaults/exit codes → B1 (empty `protected_paths` SKIP, one `record` per check, `UNKNOWN` halts). §8 migration → B3. D14 → B0 `glob_match`. N1 swarm gate → B1 `check_swarm_boundary`. §10 A/B/C/D/E → B4. **Gaps found and fixed during this review:** (i) the `authorizations/INDEX.md` required-file flip had no owner (wave-1a ruling removed it from T3) → now owned by B3 atomically; (ii) the `test_harness_smoke.py` `allowed_skip` seam would have gone red the moment B1 added legitimate fresh-install SKIPs → B1 now owns that extension (spec-4-honest, not a weakening); (iii) `--migrate` is ordered after the governance layer because it writes `window_start_commit`/`role_policy_sha256` and creates the records B1 reads. **Accepted, not built:** F7's self-referential version witness stays documentation-only (attestation is out of scope per §3); B4 names it.

**2. Placeholder scan.** B0 gives complete function bodies. B1/B2/B3 give complete test code plus the exact git command lists, branch conditions, and file ownership; prose "implement X" steps are always paired with the concrete algorithm and the named helper they call. No "add error handling" / "similar to Task N" placeholders.

**3. Type consistency.** `log_paths` returns `(paths | None, reason)` and B1 consumes exactly that two-tuple; `parse_governance_block` returns `(dict | None, err)` and B1/B2/B3 all treat `(None, None)` as WARN-not-PASS and `({}, err)` as fatal. Config-key names are one contract shared by B1 (`DEFAULT_CONFIG`), B3 (`templates/sync_config.json`), and both executors: `protected_paths`, `protected_paths_case`, `authorizations_dir`, `role_policy_sha256`, `governance.window_start_commit`. Test invocation matches `tests/helpers.py`/`conftest.py`: `run_python(sv, [], cwd=repo)` for scripts, `git(repo, ...)` for commits, `_load("ai_common")` for the new pure functions.
