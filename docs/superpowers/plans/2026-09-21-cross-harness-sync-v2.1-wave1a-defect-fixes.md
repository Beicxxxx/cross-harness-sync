# cross-harness-sync v2.1 Wave 1a — Defect Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 25 wave-1a defects in the three `scripts/*.py` files so that a second machine or a second harness can actually take over a repo, and lock every fix with a regression test that is proven to fail against v2.0.0 first.

**Architecture:** Introduce one shared stdlib-only primitives module (`ai_common.py`) copied into every install alongside the two existing scripts, so subprocess/encoding/root/config behaviour exists once instead of twice; harden the lock into an explicit state machine whose unparseable state means HELD; make unreadable configuration a hard failure; make the verifier incapable of reporting PASS for a check that could not run.

**Tech Stack:** Python 3.9+ stdlib only, pytest (dev dependency only, never shipped), git CLI via subprocess.

**Spec:** `docs/superpowers/specs/2026-09-21-cross-harness-sync-v2.1-design.md` — read §4 (design law), §5 (the defect table this plan implements), §10 (acceptance). Executors must read both files.

## Global Constraints

Applies to every task. Values are copied from the spec.

- stdlib only in anything shipped under `scripts/`. `pytest` may appear in `tests/` and `requirements-dev.txt` only.
- Python floor 3.9. Do not rely on `datetime.fromisoformat` accepting a trailing `Z` (that needs 3.11); normalize it explicitly.
- **Never treat `returncode == 0` as sufficient.** `proc.stdout is None` after rc 0 is the D5 fail-open class and must be surfaced as a non-pass.
- **A degradation may produce only a named `WARN` or `SKIP`, never `PASS`.** "File absent so skip" is legal only if that file is proven covered by a necessity check elsewhere (spec §4).
- Keep every existing check `name`, CLI flag, and command string byte-identical except D25 and D26, the two documented renames. `reference.md` documents hook command strings that live in `.claude/settings.json`, outside `.ai/`, invisible to migration.
- Capture subprocess output as **bytes**; decode with `.decode("utf-8", "surrogateescape")`.
- Do not add any path under `.ai/` other than the three files `ai_common.py` replaces or extends. `authorizations/` belongs to 1b.
- **D14 is not fixable in this plan.** There is no glob matching in v2.0.0; `protected_paths` matching arrives in 1b. Carry the constraint there: use `fnmatch.fnmatchcase()` on forward-slash paths — `fnmatch.fnmatch()` calls `os.path.normcase()`, which lowercases and rewrites `/` to `\` on Windows, so one config would match different file sets on the two machines.
- Every task ends with the R4 evidence step: paste the actual failing-output line from Step 2 into the commit message.

---

## Task 0: Test harness (prerequisite for every other task)

The repo has no tests, no `tests/`, no `pytest.ini`. Nothing below can be TDD'd until a temp-repo fixture and a **byte-safe** subprocess runner exist. Build the runner bytes-safe from the first line, because Task 5 would otherwise be testing through the very defect it fixes.

**Files:**
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `tests/conftest.py`
- Create: `tests/helpers.py`
- Create: `tests/test_harness_smoke.py`

**Interfaces:**
- Produces: `helpers.Result(rc, stdout, stderr, stdout_raw)`; `helpers.run_python(script: Path, args: Sequence[str], cwd: Path, env: dict | None = None) -> Result`; `helpers.git(cwd: Path, *args: str) -> str`; `helpers.make_repo(tmp_path: Path) -> Path`; `helpers.scaffold(repo: Path, *flags: str) -> Result`; `helpers.write_lock(repo: Path, raw: str) -> Path`; pytest fixtures `repo`, `SCRIPTS` (Path to `scripts/`), `TEMPLATES_DIR` (Path to `templates/`).

- [ ] **Step 1: Add dev requirements and pytest config**

`requirements-dev.txt`:

```
pytest>=7,<10
```

`pytest.ini`:

```ini
[pytest]
testpaths = tests
addopts = -q --strict-markers
markers =
    posix: skipped on Windows
    windows: skipped off Windows
```

- [ ] **Step 2: Write the byte-safe runner**

`tests/helpers.py` — note `capture_output` is done manually with `PIPE` and no `text=`, which is the whole point:

```python
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
TEMPLATES_DIR = REPO_ROOT / "templates"


def decode(raw: bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", "surrogateescape")


@dataclass
class Result:
    rc: int
    stdout: str
    stderr: str
    stdout_raw: bytes | None

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.stdout.splitlines() if ln.strip()]


def run_python(script: Path, args: Sequence[str] = (), cwd: Path = REPO_ROOT,
               env: dict | None = None) -> Result:
    proc = subprocess.run(
        [sys.executable, str(script), *args], cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return Result(proc.returncode, decode(proc.stdout), decode(proc.stderr),
                  proc.stdout)


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="surrogateescape")
    assert proc.returncode == 0, f"git {' '.join(args)} -> {proc.stderr}"
    return proc.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "Test Human")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    return repo


def scaffold(repo: Path, *flags: str) -> Result:
    return run_python(SCRIPTS / "init_sync.py", [str(repo), *flags], cwd=repo)


def write_lock(repo: Path, raw: str) -> Path:
    lock = repo / ".ai" / "runtime" / "WRITER_LOCK.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(raw, encoding="utf-8")
    return lock
```

- [ ] **Step 3: Fixtures**

`tests/conftest.py`:

```python
import pytest
from helpers import SCRIPTS, TEMPLATES_DIR, make_repo, scaffold


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one commit, not yet scaffolded."""
    return make_repo(tmp_path)


@pytest.fixture
def ai_repo(repo):
    """A freshly scaffolded repo. Asserts the v2.0 green-scaffold baseline."""
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    return repo


@pytest.fixture
def cp(repo):
    """Path to the copied-in checkpoint.py inside this repo's install."""
    return repo / ".ai" / "scripts" / "checkpoint.py"


@pytest.fixture
def sv(repo):
    return repo / ".ai" / "scripts" / "sync_verify.py"
```

- [ ] **Step 4: Write the smoke test that pins the baseline other tasks rely on**

`tests/test_harness_smoke.py`:

```python
from pathlib import Path

from helpers import SCRIPTS, run_python, scaffold


def test_scripts_dir_exists_and_is_stdlib_only():
    names = {p.name for p in SCRIPTS.glob("*.py")}
    assert {"checkpoint.py", "sync_verify.py", "init_sync.py"} <= names


def test_scaffold_into_git_repo_exits_zero(ai_repo):
    assert (ai_repo / ".ai" / "protocol" / "VERSION").exists()


def test_fresh_scaffold_verifies_all_green(ai_repo):
    """Baseline for later tasks: every check that ran passed, and none were
    skipped. Deliberately NOT a literal count — Tasks 3, 6 and 7 each change the
    check set, and a hard-coded number turns every legitimate change into a
    re-edit of this test. The final count is pinned once, in Task 12."""
    res = run_python(ai_repo / ".ai" / "scripts" / "sync_verify.py", cwd=ai_repo)
    assert res.rc == 0, res.stdout
    checks = [ln for ln in res.lines if ln.startswith("[")]
    assert checks, res.lines
    assert not any(ln.startswith("[FAIL]") for ln in checks), checks
    assert not any(ln.startswith("[SKIP]") for ln in checks), checks
    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1, res.lines


def test_scaffold_is_idempotent(ai_repo):
    first = (ai_repo / ".ai" / "state" / "CURRENT.md").read_text(encoding="utf-8")
    res = scaffold(ai_repo)
    assert res.rc == 0
    assert (ai_repo / ".ai" / "state" / "CURRENT.md").read_text(
        encoding="utf-8") == first
    assert not any("wrote:" in ln and "CURRENT" in ln for ln in res.lines), res.lines
```

- [ ] **Step 5: Run it**

Run: `python -m pytest tests/test_harness_smoke.py -v`
Expected: PASS, 4 tests. Record the actual `N/N` from the summary line in the commit message — that number is the baseline later tasks are expected to move, and the assertion here is deliberately count-free so it cannot go stale.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt pytest.ini tests/
git commit -m "test: add byte-safe temp-repo harness for sync scripts

sync_verify.py used text=True, which on a cp936 console silently yields
stdout=None with rc=0 (D5). The harness captures bytes and decodes with
surrogateescape so no future test can pass by not seeing output."
```

---

## Task 1: Shared primitives module + root resolution (D19, and the home for D5/D13 plumbing)

Both scripts derive the project root as `Path(__file__).resolve().parent.parent` and both need a UTF-8 stdio guard, but only `checkpoint.py` has one. Put the primitives in one copied module so this class of defect cannot be duplicated again.

**Files:**
- Create: `scripts/ai_common.py`
- Modify: `scripts/checkpoint.py:32-37` (drop its local guard and ROOT math), `scripts/sync_verify.py:29-31,77-78`
- Modify: `scripts/init_sync.py:67-70` (add the new file to `SCRIPT_MAP`)
- Test: `tests/test_ai_common.py`

**Interfaces:**
- Produces: `ai_common.RepoError(Exception)`; `ai_common.resolve_roots(script_file: str) -> tuple[Path, Path]` returning `(AI_DIR, ROOT)`; `ai_common.protect_stdio() -> None`; `ai_common.decode(raw: bytes | None) -> str`; `ai_common.git_available() -> bool`; `ai_common.is_git_repo(root: Path) -> bool`; `ai_common.GitResult(rc, stdout: bytes, stderr: bytes, timed_out: bool)`; `ai_common.run_git(root, args, timeout=60) -> GitResult`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

`tests/test_ai_common.py`:

```python
import importlib.util
import sys
from pathlib import Path

import pytest
from helpers import SCRIPTS, run_python

spec = importlib.util.spec_from_file_location("ai_common", SCRIPTS / "ai_common.py")
ai_common = importlib.util.module_from_spec(spec)
sys.modules["ai_common"] = ai_common
spec.loader.exec_module(ai_common)


def test_resolve_roots_refuses_a_script_outside_dot_ai(tmp_path):
    bad = tmp_path / "scripts" / "sync_verify.py"
    bad.parent.mkdir(parents=True)
    bad.write_text("", encoding="utf-8")
    with pytest.raises(ai_common.RepoError) as exc:
        ai_common.resolve_roots(str(bad))
    assert ".ai" in str(exc.value)


def test_resolve_roots_accepts_a_real_install(ai_repo):
    ai_dir, root = ai_common.resolve_roots(
        str(ai_repo / ".ai" / "scripts" / "sync_verify.py"))
    assert ai_dir == ai_repo / ".ai"
    assert root == ai_repo


def test_run_git_never_raises_on_timeout(tmp_path):
    res = ai_common.run_git(tmp_path, ["config", "--get", "no.such.key"], timeout=60)
    assert isinstance(res.rc, int)
    assert res.timed_out is False


def test_verify_and_checkpoint_agree_on_root(ai_repo):
    """D19: a script copied outside .ai/scripts/ used to silently audit the
    parent directory instead of the repo."""
    stray = ai_repo / "tools" / "sync_verify.py"
    stray.parent.mkdir()
    stray.write_bytes((SCRIPTS / "sync_verify.py").read_bytes())
    res = run_python(stray, cwd=ai_repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert ".ai" in (res.stdout + res.stderr)
```

- [ ] **Step 2: Run them to confirm they fail**

Run: `python -m pytest tests/test_ai_common.py -v`
Expected: collection error — `ai_common.py` does not exist yet. Record that line for the commit message.

- [ ] **Step 3: Write `scripts/ai_common.py`**

```python
#!/usr/bin/env python3
"""Shared, stdlib-only primitives for cross-harness-sync scripts.

Copied next to checkpoint.py and sync_verify.py by init_sync.py. Two rules make
this module exist: (1) subprocess output is captured as BYTES and decoded with
surrogateescape, because text=True on a legacy-codepage console kills the reader
thread and leaves stdout=None with returncode 0; (2) the project root is derived
defensively, because a silently wrong root audits the wrong directory.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

AI_DIR_NAME = ".ai"


class RepoError(Exception):
    """The install is not where this script believes it is."""


@dataclass
class GitResult:
    rc: int
    stdout: bytes
    stderr: bytes
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.timed_out

    def out(self) -> str:
        return decode(self.stdout)

    def err(self) -> str:
        return decode(self.stderr)


def decode(raw: bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", "surrogateescape")


def protect_stdio() -> None:
    """Force UTF-8 on both streams; consoles may not support what we print."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        enc = (getattr(stream, "encoding", None) or "").lower()
        if stream is None or enc.startswith("utf-8"):
            continue
        buf = getattr(stream, "buffer", None)
        if buf is None:
            continue
        setattr(sys, name, io.TextIOWrapper(buf, encoding="utf-8",
                                            errors="replace", line_buffering=True))


def resolve_roots(script_file: str) -> tuple[Path, Path]:
    ai_dir = Path(script_file).resolve().parent.parent
    if ai_dir.name != AI_DIR_NAME:
        raise RepoError(
            f"this script must live at {AI_DIR_NAME}/scripts/ ; resolved {ai_dir}")
    return ai_dir, ai_dir.parent


def git_available() -> bool:
    return shutil.which("git") is not None


def is_git_repo(root: Path) -> bool:
    res = run_git(root, ["rev-parse", "--is-inside-work-tree"], timeout=15)
    return res.ok and res.out().strip().lower() == "true"


def run_git(root: Path, args: list[str], timeout: int = 60) -> GitResult:
    env = dict(os_environ_with_git_silence())
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env)
    except subprocess.TimeoutExpired as exc:
        return GitResult(-1, exc.stdout or b"", exc.stderr or b"", True)
    except OSError as exc:
        return GitResult(-1, b"", str(exc).encode("utf-8", "replace"), False)
    return GitResult(proc.returncode, proc.stdout or b"", proc.stderr or b"", False)


def os_environ_with_git_silence() -> dict[str, str]:
    """Never let git open a credential prompt or block on an index.lock."""
    import os
    base = dict(os.environ)
    base.setdefault("GIT_TERMINAL_PROMPT", "0")
    base.setdefault("GIT_OPTIONAL_LOCKS", "0")
    base.setdefault("GCM_INTERACTIVE", "never")
    return base
```

- [ ] **Step 4: Rewire both scripts**

In `scripts/sync_verify.py`, replace lines 29–31 and the local `run()`:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from ai_common import RepoError, decode, is_git_repo, protect_stdio, \
        resolve_roots, run_git
except ImportError:
    print("[FAIL] install layout: ai_common.py is missing from .ai/scripts/ — "
          "re-run init_sync.py so the shared primitives are copied in")
    sys.exit(2)
```

There is deliberately **no** inline fallback re-implementing `run_git`/`decode`. A second copy of the subprocess plumbing would be a second copy of the fail-open path this task exists to remove, and duplicated logic is a review defect on its own. If `ai_common.py` is absent, the install is broken and must say so.

Then in `main()` the first lines become:

```python
def main() -> int:
    protect_stdio()
    try:
        global AI_DIR, ROOT, CONFIG_PATH
        AI_DIR, ROOT = resolve_roots(__file__)
        CONFIG_PATH = AI_DIR / "sync_config.json"
    except RepoError as exc:
        print(f"[FAIL] install layout: {exc}")
        return 2
```

Delete the module-level `AI_DIR`/`ROOT`/`CONFIG_PATH` assignments at lines 29–31 and the `run()` helper at 77–78; call sites that used `run([...])` now use `run_git(ROOT, [...])`. In `scripts/checkpoint.py` delete lines 32–37 (its private UTF-8 wrapper and `SCRIPT_DIR`/`AI_DIR` derivation) and replace with the same `sys.path.insert` + `resolve_roots` + `protect_stdio()` pattern, keeping `STATE_DIR`/`HANDOFF_DIR`/`RUNTIME_DIR`/`PROTOCOL_DIR`/`LOCK_PATH` derived from `AI_DIR` after `main()` runs — introduce a module-level `def _set_paths(ai_dir)` that assigns them, called from `main()` right after `resolve_roots`, and have every command function use the globals.

- [ ] **Step 5: Add it to the install map**

`scripts/init_sync.py:67-70`:

```python
SCRIPT_MAP = [
    ("ai_common.py", ".ai/scripts/ai_common.py"),
    ("checkpoint.py", ".ai/scripts/checkpoint.py"),
    ("sync_verify.py", ".ai/scripts/sync_verify.py"),
]
```

- [ ] **Step 6: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS including the 4 smoke tests, which is how you know the refactor did not break the green baseline.

- [ ] **Step 7: Commit with the D19 red-before-green line from Step 2**

```bash
git add scripts/ tests/test_ai_common.py
git commit -m "fix: derive project root defensively, share subprocess plumbing

A copy of sync_verify.py outside .ai/scripts/ silently audited the parent
directory (D19). Red-before-green evidence:
<paste Step 2 line>"
```

---

## Task 2: Configuration must not fail open (D3, D4)

`load_config()` does `merged.update(cfg)` — shallow, so one user `budgets` key replaces all five default caps — and swallows a missing or malformed file into defaults while still exiting 0. Both mean the checker can certify a repo it is not actually checking.

**Files:**
- Modify: `scripts/sync_verify.py` (`DEFAULT_CONFIG`, `load_config`, `main`)
- Modify: `templates/sync_config.json`
- Test: `tests/test_config_merge.py`, `tests/test_config_errors.py`

**Interfaces:**
- Produces: `sync_verify.DEEP_MERGE_KEYS: tuple[str, ...]` = `("budgets",)`; `sync_verify.ConfigError(Exception)` with `str(e).startswith(("unreadable:", "malformed:", "not-object:"))`; `sync_verify.load_config() -> dict` that raises `ConfigError`; `sync_verify.merge_config(defaults: dict, user: dict) -> dict`.
- Consumes: `AI_DIR`/`ROOT`/`CONFIG_PATH` from Task 1.

- [ ] **Step 1: Write the failing tests**

`tests/test_config_merge.py`:

```python
import json

from helpers import run_python


def write_cfg(repo, data):
    (repo / ".ai" / "sync_config.json").write_text(
        json.dumps(data), encoding="utf-8")


def test_user_budget_entry_does_not_erase_other_caps(ai_repo, sv):
    """D3: one custom cap used to replace all five defaults."""
    (ai_repo / ".ai" / "state" / "CURRENT.md").write_text(
        "\n".join(f"line {i}" for i in range(90)), encoding="utf-8")
    write_cfg(ai_repo, {"budgets": {".ai/handoff/LATEST.md": 5}})
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any(ln.startswith("[FAIL] budget .ai/state/CURRENT.md")
               for ln in res.lines), res.lines


def test_user_secret_files_still_covers_env(ai_repo, sv):
    """The deep merge must ADD prod.env to the list, not replace it. `.env` itself
    PASSES because init_sync writes it into .gitignore, so git check-ignore
    succeeds — asserting FAIL here would demand the opposite of correct."""
    write_cfg(ai_repo, {"secret_files": ["prod.env"]})
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[PASS] secret ignored: .env")
               for ln in res.lines), res.lines
    assert any(ln.startswith("[FAIL] secret ignored: prod.env")
               for ln in res.lines), res.lines
```

`tests/test_config_errors.py`:

```python
from helpers import run_python


def test_malformed_json_is_a_failure_not_a_default(ai_repo, sv):
    (ai_repo / ".ai" / "sync_config.json").write_text(
        '{"budgets": ', encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[FAIL] config readable")
               for ln in res.lines), res.lines


def test_missing_config_is_a_failure(ai_repo, sv):
    (ai_repo / ".ai" / "sync_config.json").unlink()
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any("unreadable" in ln for ln in res.lines), res.lines


def test_top_level_array_is_rejected(ai_repo, sv):
    (ai_repo / ".ai" / "sync_config.json").write_text("[]", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert any(ln.startswith("[FAIL] config readable") for ln in res.lines), res.lines
```

- [ ] **Step 2: Run them to confirm failure**

Run: `python -m pytest tests/test_config_merge.py tests/test_config_errors.py -v`
Expected: FAIL — `test_user_budget_entry_does_not_erase_other_caps` shows CURRENT.md unmonitored and the config-error tests show rc 0.

- [ ] **Step 3: Implement deep merge and hard failure**

In `scripts/sync_verify.py`:

```python
DEEP_MERGE_KEYS = ("budgets",)


class ConfigError(Exception):
    pass


def merge_config(defaults: dict, user: dict) -> dict:
    merged = dict(defaults)
    for key, val in user.items():
        if key in DEEP_MERGE_KEYS and isinstance(val, dict):
            inner = dict(defaults.get(key, {}))
            inner.update(val)
            merged[key] = inner
        else:
            merged[key] = val
    return merged


def load_config() -> dict:
    try:
        raw = CONFIG_PATH.read_bytes()
    except FileNotFoundError:
        raise ConfigError(f"unreadable: {CONFIG_PATH} is missing")
    try:
        cfg = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"malformed: {CONFIG_PATH}: {exc}")
    if not isinstance(cfg, dict):
        raise ConfigError(f"not-object: {CONFIG_PATH} must hold a JSON object")
    return merge_config(DEFAULT_CONFIG, cfg)
```

In `main()`, after the root resolution and before any check:

```python
    try:
        cfg = load_config()
        record("config readable", True, str(CONFIG_PATH.relative_to(ROOT)))
    except ConfigError as exc:
        print(f"[FAIL] config readable: {exc}")
        print("== 0/1 checks passed ==")
        print("FAILED: config readable")
        return 1
```

Note the explicit `0/1`: an unreadable config must not print a bare-looking summary. Then replace `utf-8` with `utf-8-sig` in every file read inside the secret checks (D20 lands here, same code path).

- [ ] **Step 4: Read secrets with BOM tolerance**

In `check_secret_mirrors`, the `keys()` helper becomes:

```python
    def keys(p: Path) -> set[str]:
        return {ln.split("=", 1)[0].strip().lstrip("\ufeff")
                for ln in p.read_text(encoding="utf-8-sig").splitlines()
                if "=" in ln and not ln.lstrip().startswith("#")}
```

- [ ] **Step 5: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/sync_verify.py tests/test_config_merge.py tests/test_config_errors.py
git commit -m "fix: deep-merge budgets and fail hard on unreadable config

One custom budgets cap replaced all five defaults, and malformed JSON fell
back to defaults with exit 0 (D3, D4) — the checker certified repos it had
stopped checking. Also read secrets as utf-8-sig (D20). Red-before-green:
<paste Step 2 lines>"
```

---

## Task 3: Required files become one config-backed list (D23)

Three divergent copies exist: `sync_verify.REQUIRED_FILES`, `checkpoint.cmd_validate`, and `cmd_status`'s inline list (which adds `ROLE_POLICY.md`/`NEXT_PROMPT.md` and drops `VERSION`). Single source, in config — which is only safe because Task 2 made unreadable config a hard failure rather than a silent default.

**Files:**
- Modify: `scripts/sync_verify.py` (delete `REQUIRED_FILES`, read `cfg["required_files"]`)
- Modify: `scripts/checkpoint.py` (`cmd_validate`, `cmd_status`)
- Modify: `templates/sync_config.json`
- Test: `tests/test_required_files.py`

**Interfaces:**
- Consumes: `load_config`, `ConfigError`, `DEFAULT_CONFIG` from Task 2.
- Produces: config key `"required_files": [...]`; `checkpoint.load_runtime_config() -> dict` (reads `.ai/sync_config.json`, tolerating absence by using the built-in default, since `--validate` may run before config exists); `ai_common.DEFAULT_REQUIRED_FILES: list[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_required_files.py`:

```python
import json

from helpers import run_python


def test_all_three_views_agree(ai_repo, sv, cp):
    v = run_python(sv, cwd=ai_repo)
    val = run_python(cp, ["--validate"], cwd=ai_repo)
    st = run_python(cp, ["--status"], cwd=ai_repo)
    sv_names = [ln.split("] ")[1].split(":")[0]
                for ln in v.lines if ln.startswith("[PASS] required ")]
    val_names = [ln.split("OK:      ")[1].split(" (")[0]
                 for ln in val.lines if ln.startswith("  OK:")]
    st_names = [ln.split("] ")[1].strip(" :") for ln in st.lines
                if ln.strip().startswith("[OK ]")]
    assert set(val_names) <= set(sv_names), (sv_names, val_names)
    assert not any("VERSION" in n for n in st_names), st_names


def test_dropping_a_required_file_is_caught_everywhere(ai_repo, sv, cp):
    (ai_repo / ".ai" / "state" / "BLOCKERS.md").unlink()
    assert run_python(sv, cwd=ai_repo).rc == 1
    assert run_python(cp, ["--validate"], cwd=ai_repo).rc == 1


def test_role_policy_is_required(ai_repo, sv):
    """v2.0 copied ROLE_POLICY.md in but never required it, so the governance
    document could simply be absent. Spec §6 item 2."""
    (ai_repo / ".ai" / "state" / "ROLE_POLICY.md").unlink()
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any("ROLE_POLICY" in ln and ln.startswith("[FAIL]")
               for ln in res.lines), res.lines


def test_required_files_is_config_overridable(ai_repo, sv):
    cfg = json.loads((ai_repo / ".ai" / "sync_config.json").read_text("utf-8"))
    cfg["required_files"] = [".ai/state/CURRENT.md"]
    (ai_repo / ".ai" / "sync_config.json").write_text(json.dumps(cfg), "utf-8")
    (ai_repo / ".ai" / "handoff" / "LATEST.md").unlink()
    res = run_python(sv, cwd=ai_repo)
    assert not any("LATEST" in ln for ln in res.lines), res.lines
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_required_files.py -v`
Expected: FAIL on the `ROLE_POLICY` and agreement assertions.

- [ ] **Step 3: Implement**

`ai_common.py` gains the single list, so both scripts import rather than copy:

```python
DEFAULT_REQUIRED_FILES = [
    ".ai/state/CURRENT.md",
    ".ai/state/TASK.md",
    ".ai/state/BLOCKERS.md",
    ".ai/state/ROLE_POLICY.md",
    ".ai/state/DECISIONS.md",
    ".ai/state/DECISIONS_INDEX.md",
    ".ai/state/authorizations/INDEX.md",
    ".ai/handoff/LATEST.md",
    ".ai/protocol/VERSION",
]
```

`authorizations/INDEX.md` is included now so 1b does not have to reopen this file; **for 1a it must be created by `init_sync.py`** (Step 4) so fresh installs stay green, and `--migrate` in 1b will create it for existing installs.

In `sync_verify.py` delete `REQUIRED_FILES`, add `"required_files": list(DEFAULT_REQUIRED_FILES)` to `DEFAULT_CONFIG`, and in `main()` pass `cfg["required_files"]` into `check_required_files(...)`. In `checkpoint.py` replace `cmd_validate`'s local list and `cmd_status`'s inline names with the config list, mapping each `required` entry to the state/handoff display groups by path prefix, and drop `VERSION` from the status listing since it is a protocol file, not state:

```python
def load_runtime_config() -> dict:
    path = AI_DIR / "sync_config.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        cfg = {}
    required = cfg.get("required_files")
    return {"required_files": list(required) if isinstance(required, list)
            else list(DEFAULT_REQUIRED_FILES)}
```

`cmd_validate` exits 1 if any required path is missing or empty and prints the path, not a basename.

- [ ] **Step 4: Keep fresh installs green**

`init_sync.py`: create the authorizations index so a new install is complete. Add to `FILE_MAP` a new template, and create it if absent:

Create `templates/authorizations/INDEX.md`:

```markdown
# Authorization Index (retrieval entry point — never read the archive in full)

> One row per authorization file. New stage = one row here + one file in this
> directory. Before reversing a stage decision: locate the row, read ONLY that
> file.

| Stage | File | Verdict |
|---|---|---|
| <stage name> | `<file>.md` | <accepted|pending> |
```

and extend `FILE_MAP` with `("authorizations/INDEX.md", ".ai/state/authorizations/INDEX.md")`.

- [ ] **Step 5: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS. This task adds two required files, so the verifier's check count rises by two; the smoke test's assertion is count-free by design, so it needs no edit here — state the new `N/N` in the commit message instead.

- [ ] **Step 6: Commit**

```bash
git add scripts/ templates/ tests/
git commit -m "fix: one config-backed required-file list shared by both scripts

Three lists had drifted apart and none of them required ROLE_POLICY.md (D23).
Check count 14 -> 16: ROLE_POLICY.md and authorizations/INDEX.md added."
```

---

## Task 4: Lock parsing is a state machine whose error state is HELD (D1, D10)

`read_json` swallows `JSONDecodeError` into `{}`, and `{}` means "no lock". Since `WRITER_LOCK.json` is deliberately tracked, two machines locking it is a *guaranteed* merge conflict — so the single-writer guarantee breaks precisely when contention is highest. Separately, an unparseable or missing `expires_at` makes a lock never expire.

**Files:**
- Modify: `scripts/checkpoint.py` (`read_json`, `lock_state`, `cmd_status`, `cmd_prime`, `cmd_lock`)
- Test: `tests/test_lock_state.py`

**Interfaces:**
- Consumes: `protect_stdio`, `resolve_roots` from Task 1.
- Produces: `checkpoint.LockStatus` — `NamedTuple(state: str, holder: str | None, detail: str)` with `state` in `{"free", "held", "expired", "error"}`; `checkpoint.lock_state() -> LockStatus` (replaces the old `(lock, holder, expired)` triple); `checkpoint.parse_ts(raw) -> datetime | None`; `checkpoint.read_json_or_error(path) -> tuple[dict, str | None]` where the second item is an error string.
- Consumed later: Task 5 and Task 1b's lineage check.

- [ ] **Step 1: Write the failing tests**

`tests/test_lock_state.py`:

```python
import json

from helpers import run_python, write_lock


def live(agent="codex", **over):
    rec = {"agent": agent, "reason": "t", "acquired_at": "2026-09-21T10:00:00+10:00",
           "expires_at": "2099-01-01T00:00:00+10:00", "released_at": None}
    rec.update(over)
    return json.dumps(rec)


def test_merge_conflict_lock_is_reported_as_held(ai_repo, cp):
    write_lock(ai_repo, "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other\n")
    res = run_python(cp, ["--status"], cwd=ai_repo)
    assert "CONFLICT" in res.stdout.upper(), res.stdout
    assert "none" not in res.stdout.split("Writer Lock")[1].split("\n")[0]


def test_corrupt_lock_blocks_acquisition(ai_repo, cp):
    write_lock(ai_repo, "not json at all")
    res = run_python(cp, ["--lock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "cannot parse" in res.stdout.lower(), res.stdout


def test_missing_expires_at_does_not_last_forever(ai_repo, cp):
    write_lock(ai_repo, json.dumps({"agent": "codex", "released_at": None}))
    res = run_python(cp, ["--prime"], cwd=ai_repo)
    assert res.rc == 0
    line = [ln for ln in res.lines if ln.startswith("Writer lock")][0]
    assert "no expiry" in line, line


def test_z_suffix_expires_at_parses(ai_repo, cp):
    write_lock(ai_repo, live(expires_at="2099-01-01T00:00:00Z"))
    res = run_python(cp, ["--lock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1, res.stdout


def test_naive_expires_at_is_treated_as_local(ai_repo, cp):
    write_lock(ai_repo, live(expires_at="2099-01-01 00:00:00"))
    res = run_python(cp, ["--status"], cwd=ai_repo)
    assert "HELD" in res.stdout, res.stdout


def test_valid_held_lock_still_refuses(ai_repo, cp):
    write_lock(ai_repo, live())
    res = run_python(cp, ["--lock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1 and "LOCK CONFLICT" in res.stdout
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_lock_state.py -v`
Expected: FAIL — the corrupt-lock test prints "Writer Lock : none".

- [ ] **Step 3: Implement**

```python
from typing import NamedTuple


class LockStatus(NamedTuple):
    state: str           # free | held | expired | error
    holder: str | None
    detail: str


def read_json_or_error(path):
    if not path.exists():
        return {}, None
    raw = path.read_bytes()
    if b"<<<<<<<" in raw or b">>>>>>>" in raw:
        return {}, "merge conflict markers"
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {}, f"cannot parse: {exc}"
    if not isinstance(data, dict):
        return {}, "cannot parse: expected a JSON object"
    return data, None


def parse_ts(raw):
    """Tolerant of Z suffixes (pre-3.11 fromisoformat is not) and naive stamps."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.astimezone()
    return stamp


def lock_state():
    lock, err = read_json_or_error(LOCK_PATH)
    if err:
        return LockStatus("error", None, err)
    if not lock:
        return LockStatus("free", None, "no lock file")
    if lock.get("released_at"):
        return LockStatus("free", None, f"released {lock['released_at']}")
    holder = lock.get("agent") or "?"
    expires = parse_ts(lock.get("expires_at"))
    if expires is None:
        return LockStatus("held", holder,
                          "no expiry (malformed or absent expires_at) — do not "
                          "rely on the TTL; release with --unlock --force")
    if now_dt() > expires:
        return LockStatus("expired", holder, f"expired {lock['expires_at']}")
    return LockStatus("held", holder, f"until {lock['expires_at']}")
```

Rewrite the three consumers on the new state name — `cmd_status` prints `Writer Lock      : CONFLICT/ERROR (<detail>)` or `HELD by <h> (<detail>)`; `cmd_prime` prints `Writer lock: <state> — <detail>` and, for `"error"`, appends `— do NOT write state files; resolve the conflict first`; `cmd_lock` refuses when `state in {"held", "error"}` unless `--force`, and for `"error"` also refuses `--force` unless a new `--discard-lock` flag is passed, printing that the discarded record is being kept in git history. Keep the existing exit codes (1 conflict, 2 usage).

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: an unparseable writer lock now means HELD, not free

WRITER_LOCK.json is tracked on purpose, so two machines locking it guarantees a
merge conflict; the conflict made read_json return {} and --prime told both
agents the pen was free (D1). Unparseable/absent expires_at no longer means
never-expiring (D10). Red-before-green: <paste Step 2 lines>"
```

---

## Task 5: Atomic writes and you cannot release someone else's pen (D8, D9, D2)

`shutil.move` is not atomic on Windows and every writer shares one `.tmp` name. Worse, `cmd_unlock` only checks the holder when `--agent` was passed — while `--prime`'s own output and `--handoff`'s instructions both tell you to run bare `--unlock`.

**Files:**
- Modify: `scripts/checkpoint.py` (`write_json`, `cmd_unlock`, `cmd_prime`, `cmd_handoff`)
- Test: `tests/test_unlock_authority.py`, `tests/test_write_atomicity.py`

**Interfaces:**
- Consumes: `LockStatus` and `lock_state()` from Task 4.
- Produces: `checkpoint.write_json(path, data)` unchanged in signature but now atomic and conflict-free; `cmd_unlock` exit code 2 when `--agent` is missing against a live lock.

- [ ] **Step 1: Write the failing tests**

`tests/test_unlock_authority.py`:

```python
import json

from helpers import run_python, write_lock


def held(agent="codex"):
    return json.dumps({"agent": agent, "reason": "x",
                       "acquired_at": "2026-09-21T10:00:00+10:00",
                       "expires_at": "2099-01-01T00:00:00+10:00",
                       "released_at": None})


def test_bare_unlock_refused_against_live_lock(ai_repo, cp):
    """D2: --prime told users to run exactly this command."""
    write_lock(ai_repo, held())
    res = run_python(cp, ["--unlock"], cwd=ai_repo)
    assert res.rc == 2, res.stdout
    assert "--agent" in res.stdout, res.stdout
    assert json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                      .read_text("utf-8-sig"))["released_at"] is None


def test_owner_may_unlock(ai_repo, cp):
    write_lock(ai_repo, held())
    res = run_python(cp, ["--unlock", "--agent", "codex"], cwd=ai_repo)
    assert res.rc == 0
    assert json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                      .read_text("utf-8-sig"))["released_at"]


def test_non_owner_may_not_unlock(ai_repo, cp):
    write_lock(ai_repo, held())
    res = run_python(cp, ["--unlock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1 and "not claude-code" in res.stdout


def test_prime_and_handoff_advertise_the_safe_form(ai_repo, cp):
    for args in ([], ["--handoff", "--agent", "codex"]):
        res = run_python(cp, args, cwd=ai_repo) if args else \
            run_python(cp, ["--prime"], cwd=ai_repo)
        assert res.rc == 0, res.stdout
        assert "--unlock --agent" in res.stdout, (args, res.stdout)
        assert "release the lock (--unlock)" not in res.stdout
```

`tests/test_write_atomicity.py`:

```python
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from helpers import SCRIPTS

CHECKPOINT = SCRIPTS / "checkpoint.py"


def _tmp_names_used_by_the_repo_source():
    text = CHECKPOINT.read_text(encoding="utf-8")
    return "with_suffix(\".tmp\")" in text or "with_suffix('.tmp')" in text


def test_write_json_no_longer_shares_one_tmp_name():
    assert not _tmp_names_used_by_the_repo_source()


def test_os_replace_is_used_for_the_tracked_lock():
    text = CHECKPOINT.read_text(encoding="utf-8")
    assert "os.replace" in text and "shutil.move" not in text


def test_concurrent_status_writes_leave_valid_json(tmp_path):
    """D9: two local writers used to clobber each other's single .tmp file."""
    ai = tmp_path / ".ai" / "scripts"
    ai.mkdir(parents=True)
    for name in ("checkpoint.py", "ai_common.py"):
        shutil_copy(name, ai)
    target = tmp_path / ".ai" / "runtime" / "STATUS.json"
    target.parent.mkdir()

    def one(i):
        subprocess.run([sys.executable, str(ai / "checkpoint.py"),
                        "--agent", f"a{i}"], cwd=str(tmp_path),
                       capture_output=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, range(8)))
    data = json.loads(target.read_text("utf-8-sig"))
    assert data["checkpoint_count"] >= 1, data
```

Add to that file, above the tests:

```python
import shutil


def shutil_copy(name, dest_dir):
    shutil.copy2(str(SCRIPTS / name), str(dest_dir / name))
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_unlock_authority.py tests/test_write_atomicity.py -v`
Expected: FAIL — bare `--unlock` succeeds (rc 0) and the source-text assertions fail.

- [ ] **Step 3: Implement**

```python
def write_json(path, data):
    """Atomic on every platform: os.rename raises on Windows when the target
    exists and shutil.move then degrades to copy+unlink; os.replace is the
    atomic form on both, and a unique temp name keeps two local writers from
    clobbering each other's partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
```

Add imports `os`, `tempfile`; drop `shutil` if now unused. `cmd_unlock` head becomes:

```python
def cmd_unlock(args):
    status = lock_state()
    if status.state == "error":
        print(f"Lock record is unreadable ({status.detail}); refusing to release "
              "it blind. Resolve the git conflict, then --unlock --agent <name>.")
        sys.exit(2)
    if status.state in ("free", "expired") and not status.holder:
        print("Writer lock: " + ("none" if status.state == "free"
                                 else f"already expired ({status.holder})"))
        return
    if not args.agent:
        print(f"--unlock requires --agent <name>: the lock is held by "
              f"{status.holder} ({status.detail}).")
        sys.exit(2)
    if status.holder != args.agent and not args.force:
        print(f"Lock is held by {status.holder}, not {args.agent}. "
              "Use --force to override.")
        sys.exit(1)
    lock, _err = read_json_or_error(LOCK_PATH)
    lock["released_at"] = now_iso()
    lock["released_by"] = args.agent
    write_json(LOCK_PATH, lock)   # never deleted: the record is the audit trail
    print(f"Writer lock released at {now_display()}")
```

Update the two instruction strings: in `cmd_prime` the close-out lines become `At close-out: python .ai/scripts/sync_verify.py must be all green,` / `then --unlock --agent <your-name>, commit, and push.` In `cmd_handoff`, `Then run sync_verify.py, release the lock (--unlock --agent <name>), commit, and push.`

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS. `--prime`'s text assertion in earlier tests may need the matching update — fix the test only if the spec's byte-identical-flag rule allows it; flags do not change here, only prose.

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: lock writes are atomic and releasing another agent's pen is refused

shutil.move degraded to copy+unlink on Windows and all writers shared one .tmp
name (D8, D9); bare --unlock silently dropped a live holder while --prime's own
output told users to run it (D2). Red-before-green: <paste Step 2 lines>"
```

---

## Task 6: The verifier cannot crash, and cannot go green while blind (D5, D11, D12, D13)

`text=True` plus a cp936 console kills the reader thread, leaving `stdout=None` with rc 0; `check_secrets_ignored` calls `run()` unguarded so a timeout or a missing git aborts the whole run with a traceback; a non-git tree produces seven confusing `rc=128` failures.

**Files:**
- Modify: `scripts/sync_verify.py` (`check_secrets_ignored`, `check_extra`, `main`)
- Test: `tests/test_subprocess_hardening.py`

**Interfaces:**
- Consumes: `run_git`, `GitResult`, `git_available`, `is_git_repo` from Task 1.
- Produces: check names `git usable`, `git repository`, and existing `secret ignored: <path>` / `<extra_check name>` names unchanged.

- [ ] **Step 1: Write the failing tests**

`tests/test_subprocess_hardening.py`:

```python
import os
import shutil

from helpers import run_python


def test_no_git_on_path_is_one_clean_failure(ai_repo, sv, tmp_path):
    fake = tmp_path / "empty-bin"
    fake.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PATH"}
    env["PATH"] = str(fake)
    res = run_python(sv, cwd=ai_repo, env=env)
    assert res.rc == 1, res.stdout
    assert "Traceback" not in res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] git usable") for ln in res.lines), res.lines


def test_non_git_tree_reports_repository_once(ai_repo, sv):
    shutil.rmtree(ai_repo / ".git")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any(ln.startswith("[FAIL] git repository") for ln in res.lines), res.lines
    assert not any("rc=128" in ln for ln in res.lines), res.lines


def test_hung_extra_check_becomes_a_fail_not_a_traceback(ai_repo, sv):
    import json
    slow = "import time; time.sleep(30)"
    (ai_repo / "slow.py").write_text(slow, encoding="utf-8")
    cfg = json.loads((ai_repo / ".ai" / "sync_config.json").read_text("utf-8"))
    cfg["extra_checks"] = [{"name": "slow check",
                            "cmd": ["python", "slow.py"]}]
    cfg["check_timeout"] = 1
    (ai_repo / ".ai" / "sync_config.json").write_text(json.dumps(cfg), "utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any(ln.startswith("[FAIL] slow check") and "timed out" in ln
               for ln in res.lines), res.lines


def test_non_ascii_paths_survive_a_piped_cp936_console(ai_repo, sv, monkeypatch):
    """D5: under text=True the reader thread died on raw UTF-8 bytes and left
    stdout=None with rc 0, which the governance walk read as 'nothing touched'."""
    (ai_repo / "文档").mkdir()
    (ai_repo / "文档" / "冻结.py").write_text("x = 1\n", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="cp936:strict")
    res = run_python(sv, cwd=ai_repo, env=env)
    assert res.rc in (0, 1), res.stdout
    assert "Traceback" not in res.stderr, res.stderr
    assert "[PASS]" in res.stdout or "[FAIL]" in res.stdout
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_subprocess_hardening.py -v`
Expected: FAIL — today you get a traceback and, for the cp936 case, an empty `stdout`.

- [ ] **Step 3: Implement**

In `sync_verify.py` add `"check_timeout": 60` to `DEFAULT_CONFIG`, and near the top of `main()`:

```python
    if not git_available():
        record("git usable", False, "git not found on PATH")
        print("== 0/1 checks passed ==")
        print("FAILED: git usable")
        return 1
    in_repo = is_git_repo(ROOT)
    record("git repository", in_repo,
           "yes" if in_repo else f"{ROOT} is not a git work tree")
```

`check_secrets_ignored` and `check_extra` route through `run_git` and never raise:

```python
def check_secrets_ignored(cfg: dict) -> None:
    if not is_git_repo(ROOT):
        record("secret ignored", False, "skipped: no git repository to ask")
        return
    for target in cfg["secret_files"]:
        res = run_git(ROOT, ["check-ignore", "-v", target],
                      timeout=cfg["check_timeout"])
        if res.timed_out:
            record(f"secret ignored: {target}", False, "git check-ignore timed out")
        elif res.rc == 0:
            record(f"secret ignored: {target}", True, decode(res.stdout).strip())
        else:
            detail = decode(res.stderr).strip().splitlines()
            record(f"secret ignored: {target}", False,
                   f"rc={res.rc}; {detail[-1] if detail else 'no stderr'}")


def check_extra(cfg: dict) -> None:
    for chk in cfg["extra_checks"]:
        name, cmd = chk["name"], chk["cmd"]
        if isinstance(cmd, str):
            record(name, False, "extra_checks.cmd must be a JSON array; got a string")
            continue
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT), timeout=cfg["check_timeout"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.TimeoutExpired:
            record(name, False, f"timed out after {cfg['check_timeout']}s: {cmd}")
            continue
        except OSError as exc:
            record(name, False, f"could not run {cmd}: {exc}")
            continue
        tail = (decode(proc.stdout) + decode(proc.stderr)).strip().splitlines()
        record(name, proc.returncode == 0,
               f"rc={proc.returncode}; {tail[-1][:160] if tail else '(no output)'}")
```

Call `protect_stdio()` first in `main()` (Task 1 wired it; assert it here). D21's string-vs-list coercion is the `isinstance(cmd, str)` guard above.

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: verifier reports failures instead of dying or going blind

text=True on a cp936 console killed subprocess's reader thread, leaving
stdout=None with rc=0 (D5) — a governance walk would have read that as 'no
protected paths touched'. Also: unguarded TimeoutExpired / missing-git tracebacks
(D11), misleading rc=128 in a non-git tree (D12), missing UTF-8 guard (D13),
string-typed extra_checks commands succeeding on Windows and failing on macOS
(D21). Red-before-green: <paste Step 2 lines>"
```

---

## Task 7: A fresh clone on a second machine verifies green and can hand off (D6, D16, and spec §10.B)

`secret_mirrors` FAILs when either side is missing — but mirrored secrets are git-ignored by design, so machine two can never pass close-out. And empty directories do not survive a clone while `cmd_handoff` never `mkdir`s `RUNTIME_DIR`, unlike its sibling commands.

**Files:**
- Modify: `scripts/sync_verify.py` (`check_secret_mirrors`)
- Modify: `scripts/init_sync.py` (`.gitkeep` for tracked-empty dirs)
- Modify: `scripts/checkpoint.py` (`cmd_handoff`)
- Test: `tests/test_second_machine.py`

**Interfaces:**
- Consumes: `scaffold`, `run_python` from Task 0.
- Produces: check name `secret mirror <a> vs <b>` with evidence `SKIP(no mirrored secrets on this machine)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_second_machine.py`:

```python
import json

from helpers import git, run_python, scaffold


def test_handoff_works_on_a_fresh_clone(ai_repo, tmp_path):
    """Empty dirs are not tracked by git, so a clone used to crash here."""
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "install")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(ai_repo), str(clone))
    cp = clone / ".ai" / "scripts" / "checkpoint.py"
    res = run_python(cp, ["--handoff", "--agent", "codex"], cwd=clone)
    assert res.rc == 0, res.stdout + res.stderr
    assert (clone / ".ai" / "runtime").is_dir()


def test_mirror_check_skips_when_neither_side_exists(ai_repo, sv):
    cfg = json.loads((ai_repo / ".ai" / "sync_config.json").read_text("utf-8"))
    cfg["secret_mirrors"] = [[".env", ".claude/.env"]]
    (ai_repo / ".ai" / "sync_config.json").write_text(json.dumps(cfg), "utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert not any(ln.startswith("[FAIL] secret mirror") for ln in res.lines), res.lines
    assert any("SKIP" in ln for ln in res.lines), res.lines


def test_mirror_check_still_fails_when_both_exist_differing(ai_repo, sv):
    cfg = json.loads((ai_repo / ".ai" / "sync_config.json").read_text("utf-8"))
    cfg["secret_mirrors"] = [[".env", ".claude/.env"]]
    cfg["secret_files"] = []
    (ai_repo / ".ai" / "sync_config.json").write_text(json.dumps(cfg), "utf-8")
    (ai_repo / ".env").write_text("A=1\n", encoding="utf-8")
    (ai_repo / ".claude").mkdir()
    (ai_repo / ".claude" / ".env").write_text("B=2\n", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any(ln.startswith("[FAIL] secret mirror") for ln in res.lines), res.lines


def test_second_machine_full_closeout_cycle(ai_repo, tmp_path):
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "install")
    clone = tmp_path / "clone2"
    git(tmp_path, "clone", "-q", str(ai_repo), str(clone))
    cp = clone / ".ai" / "scripts" / "checkpoint.py"
    sv = clone / ".ai" / "scripts" / "sync_verify.py"
    assert run_python(cp, ["--lock", "--agent", "claude-code",
                           "--reason", "wave1"], cwd=clone).rc == 0
    assert run_python(sv, cwd=clone).rc == 0
    assert run_python(cp, ["--handoff", "--agent", "claude-code"],
                      cwd=clone).rc == 0
    assert run_python(cp, ["--unlock", "--agent", "claude-code"],
                      cwd=clone).rc == 0
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "handoff from claude-code")
    git(clone, "-c", "user.name=Test Human", "-c", "user.email=t@example.invalid",
        "push", "-q", "origin", "main")
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_second_machine.py -v`
Expected: FAIL — the clone crashes inside `write_json`, and the mirror check reports FAIL.

- [ ] **Step 3: Implement**

`check_secret_mirrors` per pair:

```python
    for pair in cfg["secret_mirrors"]:
        a, b = ROOT / pair[0], ROOT / pair[1]
        if not (a.exists() or b.exists()):
            record(f"secret mirror {pair[0]} vs {pair[1]}", None,
                   "SKIP(no mirrored secrets on this machine)")
            continue
        if not (a.exists() and b.exists()):
            missing = pair[0] if not a.exists() else pair[1]
            record(f"secret mirror {pair[0]} vs {pair[1]}", None,
                   f"SKIP(present on this machine: "
                   f"{pair[0] if a.exists() else pair[1]}; absent: {missing})")
            continue
        ka, kb = keys(a), keys(b)
        record(f"secret mirror {pair[0]} vs {pair[1]}", ka == kb,
               f"{pair[0]}-only={sorted(ka - kb)}, "
               f"{pair[1]}-only={sorted(kb - ka)}")
```

`record()` gains a third state — change its signature and keep the summary honest, since a SKIP is not a pass (spec §4):

```python
RESULTS: list[tuple[str, "bool | None", str]] = []


def record(name: str, ok, evidence: str) -> None:
    RESULTS.append((name, ok, evidence))
    tag = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
    print(f"[{tag}] {name}: {evidence}")


# in main():
    passed = sum(1 for _, ok, _ in RESULTS if ok is True)
    skipped = sum(1 for _, ok, _ in RESULTS if ok is None)
    failed = [n for n, ok, _ in RESULTS if ok is False]
    print(f"== {passed}/{len(RESULTS)} checks passed, {skipped} skipped ==")
```

The smoke test's summary matcher must be updated to assert `"checks passed"` plus a separate `assert "skipped" in line` — the SKIP count is deliberately in the same line so it cannot be ignored. Note the check-count change in the commit message (16 → 17: `git usable` and `git repository` from Task 6 land first, so recount from the actual output). `init_sync.py` creates the tracked placeholders after the mkdir block:

```python
    for keep in (".ai/handoff/archive/.gitkeep", ".ai/state/archive/.gitkeep",
                 ".ai/state/authorizations/.gitkeep", ".ai/runtime/.gitkeep"):
        path = root / keep
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
            print(f"wrote: {path}")
```

`.gitignore` gains `!.ai/*/.gitkeep` lines alongside the existing runtime entries. `cmd_handoff` calls `RUNTIME_DIR.mkdir(parents=True, exist_ok=True)` and `ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)` before touching either.

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: a second machine can clone, verify, hand off and push

secret_mirrors could never pass on a fresh clone because mirrored secrets are
git-ignored by design (D6), and the first --handoff crashed on the runtime dir
git had not tracked (D16). Skips are now reported as SKIP and counted apart from
passes, never as PASS. Red-before-green: <paste Step 2 lines>"
```

---

## Task 8: Scaffolding cannot destroy state (D7, D24)

`--force` overwrites `CURRENT.md`, `TASK.md`, `DECISIONS.md` and the config with empty templates while refreshing the scripts — in a tool where `.ai/state` *is* the work state. And `copy_file` does not check that its source exists, so a missing template aborts mid-install with a traceback and leaves a half-built tree.

**Files:**
- Modify: `scripts/init_sync.py` (`copy_file`, `main`, new `--scripts-only`)
- Test: `tests/test_init_safety.py`

**Interfaces:**
- Produces: CLI flags `--scripts-only`, `--force` scoped to template-shaped files; `init_sync.is_template_shaped(text: str) -> bool` (true when every `<...>` line is unfilled placeholder text, i.e. the file was never edited).
- Consumes: `DEFAULT_REQUIRED_FILES` from Task 3 (used to refuse clobbering anything required).

- [ ] **Step 1: Write the failing tests**

`tests/test_init_safety.py`:

```python
from pathlib import Path

from helpers import SCRIPTS, run_python, scaffold


def edited(repo, rel, text):
    path = repo / rel
    path.write_text(text, encoding="utf-8")
    return path


def test_force_does_not_overwrite_edited_state(ai_repo):
    """D7: --force used to replace live CURRENT.md with an empty template."""
    keep = "# Current state\n\nReal work in progress, 47 lines of it.\n"
    edited(ai_repo, ".ai/state/CURRENT.md", keep)
    res = scaffold(ai_repo, "--force")
    assert res.rc == 0, res.stdout
    assert (ai_repo / ".ai" / "state" / "CURRENT.md").read_text(
        "utf-8") == keep
    assert any(ln.startswith("KEEP (edited)") for ln in res.lines), res.lines


def test_force_still_refreshes_untouched_templates(ai_repo):
    res = scaffold(ai_repo, "--force")
    assert any(ln.startswith("wrote:") and "TASK.md" in ln
               for ln in res.lines), res.lines


def test_scripts_only_leaves_state_alone(ai_repo):
    keep = "# Current state\n\nwork\n"
    edited(ai_repo, ".ai/state/CURRENT.md", keep)
    edited(ai_repo, ".ai/sync_config.json", '{"budgets": {"x": 1}}')
    res = scaffold(ai_repo, "--scripts-only")
    assert res.rc == 0, res.stdout
    assert (ai_repo / ".ai" / "state" / "CURRENT.md").read_text("utf-8") == keep
    assert (ai_repo / ".ai" / "sync_config.json").read_text("utf-8") \
        == '{"budgets": {"x": 1}}'
    assert any("scripts" in ln for ln in res.lines), res.lines


def test_missing_template_is_a_named_error_not_a_traceback(ai_repo, tmp_path):
    res = run_python(SCRIPTS / "init_sync.py", [str(tmp_path / "new"),
                                                "--no-agents-block"],
                     cwd=tmp_path)
    assert "Traceback" not in res.stderr, res.stderr
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_init_safety.py -v`
Expected: FAIL — `CURRENT.md` is silently replaced by the template.

- [ ] **Step 3: Implement**

```python
def is_template_shaped(text: str) -> bool:
    """An untouched copy of one of our templates: every placeholder still
    present, and none of the caller's own content lines added."""
    import re
    if "<" not in text:
        return False
    body = [ln for ln in text.splitlines() if ln.strip()
            and not ln.lstrip().startswith(("#", ">", "-", "*", "|"))]
    return all(re.search(r"<[^<>]*>", ln) or "<!--" in ln for ln in body)


def copy_file(src: Path, dst: Path, force: bool, protected: bool = False) -> str:
    if not src.exists():
        return f"ERROR (missing source template): {src}"
    if dst.exists():
        if not force:
            return f"SKIP (exists): {dst}"
        if protected:
            try:
                existing = dst.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                existing = ""
            if not is_template_shaped(existing):
                return f"KEEP (edited): {dst} — pass --clobber to overwrite"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    return f"wrote: {dst}"
```

In `main()` build the protected set from the state/handoff/config destinations and pass `protected=True` for them, add `--scripts-only` which skips every `FILE_MAP` entry and writes only `SCRIPT_MAP` + `protocol/VERSION`, and add `--clobber` as the explicit escape hatch whose printed warning tells the user to commit first. Make `copy_file` failures set `rc = 1`.

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: --force no longer overwrites edited state; add --scripts-only

init_sync --force replaced live CURRENT/TASK/DECISIONS with empty templates
(D7), and a missing source template aborted the install midway (D24).
Red-before-green: <paste Step 2 lines>"
```

---

## Task 9: Install flags and gitignore are honest (D17, D18)

`update_gitignore` appends all five lines whenever any one is absent, duplicating entries and printing a count it did not write. `--no-agents-block` skips creating `AGENTS.md` yet still writes a `CLAUDE.md` pointer to it and leaves `"AGENTS.md": 65` in the config, so verify exits 1 forever — contradicting init's own closing "should be all green".

**Files:**
- Modify: `scripts/init_sync.py` (`update_gitignore`, `main`, `write_claude_pointer`)
- Modify: `templates/sync_config.json`
- Test: `tests/test_init_flags.py`

**Interfaces:**
- Produces: `init_sync.update_gitignore(root, wanted: list[str]) -> str` returning `".gitignore: appended N entries"` where N equals lines actually added.

- [ ] **Step 1: Write the failing tests**

`tests/test_init_flags.py`:

```python
import json

from helpers import git, run_python, scaffold


def test_gitignore_appends_only_absent_lines(ai_repo):
    (ai_repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    res = scaffold(ai_repo)
    assert res.rc == 0, res.stdout
    text = (ai_repo / ".gitignore").read_text("utf-8")
    assert text.count(".env\n") == 1, repr(text)
    assert text.count("# cross-harness-sync") == 1, repr(text)
    line = [ln for ln in res.lines if ln.startswith(".gitignore:")][0]
    n = int(line.split("appended ")[1].split(" ")[0])
    assert n == len(text.splitlines()) - 1, (line, text)


def test_gitignore_message_is_a_noop_when_complete(ai_repo):
    scaffold(ai_repo)
    before = (ai_repo / ".gitignore").read_text("utf-8")
    res = scaffold(ai_repo)
    assert "already up to date" in res.stdout
    assert (ai_repo / ".gitignore").read_text("utf-8") == before


def test_no_agents_block_installs_cleanly(repo):
    """D18: verify used to be permanently red after this flag."""
    res = scaffold(repo, "--no-agents-block")
    assert res.rc == 0, res.stdout
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / "CLAUDE.md").exists()
    cfg = json.loads((repo / ".ai" / "sync_config.json").read_text("utf-8"))
    assert "AGENTS.md" not in cfg.get("budgets", {}), cfg
    verify = run_python(repo / ".ai" / "scripts" / "sync_verify.py", cwd=repo)
    assert verify.rc == 0, verify.stdout


def test_default_install_still_budgets_agents_md(ai_repo):
    cfg = json.loads((ai_repo / ".ai" / "sync_config.json").read_text("utf-8"))
    assert cfg["budgets"]["AGENTS.md"] == 65, cfg
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_init_flags.py -v`
Expected: FAIL — duplicated `.env`, a lying count, and the permanent red.

- [ ] **Step 3: Implement**

```python
def update_gitignore(root: Path, wanted: list[str] | None = None) -> str:
    lines = wanted if wanted is not None else GITIGNORE_LINES
    gi = root / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    have = set(existing.splitlines())
    missing = [ln for ln in lines if ln not in have]
    if not missing:
        return ".gitignore: already up to date"
    with open(gi, "a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write("\n".join(missing) + "\n")
    return f".gitignore: appended {len(missing)} entries"
```

In `main()`, when `args.no_agents_block` is set: skip `write_claude_pointer` entirely and prune the key before writing the config — after the `FILE_MAP` loop add

```python
    if args.no_agents_block:
        cfg_path = root / ".ai" / "sync_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        removed = cfg.get("budgets", {}).pop("AGENTS.md", None)
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        print(f"sync_config.json: dropped AGENTS.md budget (was {removed}) "
              "because --no-agents-block did not create the file")
```

and guard the CLAUDE.md pointer with `if not args.no_agents_block:`. Note the spec rule being honoured: the fix is *not* "missing budgets file becomes a WARN", because `AGENTS.md` would then be monitored by nothing.

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: gitignore appends only what it reports; --no-agents-block installs green

update_gitignore re-appended all five lines whenever one was missing and
reported len(missing) rather than what it wrote (D17); --no-agents-block left
verify permanently red and pointed CLAUDE.md at a file that did not exist (D18).
Red-before-green: <paste Step 2 lines>"
```

---

## Task 10: One install root, and worktrees are refused (D15)

Two linked worktrees on one machine each hold their own on-disk `WRITER_LOCK.json`, so the single-writer rule is violated locally with no git involved. `resolve()` also follows symlinks, so a relocated or linked checkout can silently point ROOT at another repo.

**Files:**
- Modify: `scripts/ai_common.py` (worktree/symlink detection), `scripts/checkpoint.py` (`cmd_lock`)
- Test: `tests/test_worktree_refusal.py`

**Interfaces:**
- Produces: `ai_common.checkout_layout(root: Path) -> tuple[str, str]` returning `(kind, detail)` where `kind` is `"normal" | "linked-worktree" | "symlinked" | "outside-repo"`; `ai_common.worktrees(root: Path) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_worktree_refusal.py`:

```python
from pathlib import Path

from helpers import git, run_python


def linked(ai_repo, tmp_path):
    wt = tmp_path / "wt"
    git(ai_repo, "worktree", "add", "-q", "-b", "side", str(wt))
    return wt


def test_lock_in_a_linked_worktree_is_refused(ai_repo, tmp_path):
    wt = linked(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    if not cp.exists():
        # the worktree copy is a fresh checkout of the installed files
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "install in worktree")
    res = run_python(cp, ["--lock", "--agent", "codex"], cwd=wt)
    assert res.rc == 1, res.stdout
    assert "worktree" in res.stdout.lower(), res.stdout


def test_main_checkout_is_unaffected(ai_repo, cp):
    res = run_python(cp, ["--lock", "--agent", "codex"], cwd=ai_repo)
    assert res.rc == 0, res.stdout


def test_symlinked_dot_ai_is_refused(ai_repo, tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (ai_repo / ".ai" / "state").rename(real / "state")
    (ai_repo / ".ai" / "state").symlink_to(real / "state", target_is_directory=True)
    res = run_python(ai_repo / ".ai" / "scripts" / "sync_verify.py", cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[FAIL] install layout") for ln in res.lines), res.lines
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_worktree_refusal.py -v`
Expected: FAIL — both commands currently succeed, and the lock in one worktree is invisible to the other.

- [ ] **Step 3: Implement**

```python
def checkout_layout(root: Path) -> tuple[str, str]:
    ai = root / AI_DIR_NAME
    if ai.is_symlink():
        return "symlinked", f"{ai} is a symlink -> {ai.readlink()}"
    git_dir = run_git(root, ["rev-parse", "--absolute-git-dir"], timeout=15)
    common = run_git(root, ["rev-parse", "--path-format=absolute",
                            "--git-common-dir"], timeout=15)
    if git_dir.ok and common.ok:
        gd = git_dir.out().strip().rstrip("/")
        cd = common.out().strip().rstrip("/")
        if "/worktrees/" in gd and gd != cd:
            return "linked-worktree", f"{gd} (common {cd})"
    return "normal", str(root)


def worktrees(root: Path) -> list[str]:
    res = run_git(root, ["worktree", "list", "--porcelain"], timeout=15)
    if not res.ok:
        return []
    return [ln.split(" ", 1)[1] for ln in decode(res.stdout).splitlines()
            if ln.startswith("worktree ")]
```

In `sync_verify.main()` add after the root resolution, using the existing `record` so a bad layout can never be a pass:

```python
    kind, detail = checkout_layout(ROOT)
    if kind == "symlinked":
        record("install layout", False, f".ai is a symlink: {detail}")
        return 1
```

In `checkpoint.cmd_lock`, before writing anything:

```python
    kind, detail = checkout_layout(ROOT)
    if kind == "linked-worktree":
        print(f"REFUSED: this checkout is a linked git worktree ({detail}).\n"
              "WRITER_LOCK.json lives on disk per worktree, so locking here does "
              "not stop another worktree from writing.\n"
              "Work in the main checkout, or run "
              "  python .ai/scripts/checkpoint.py --lock --agent <name> --force "
              "only after recording the split in the handoff.")
        sys.exit(1)
```

Also require `--force` to name an explicit `--reason` (currently optional) and record `forced_over: {agent, epoch, acquired_at}` copied from the displaced record, so takeover is visible in git history. `epoch` is new in 1b's schema but harmless to start writing here: `record["epoch"] = int(prev.get("epoch", 0)) + 1`.

- [ ] **Step 4: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: refuse to lock from a linked worktree or a symlinked .ai

Each worktree holds its own on-disk WRITER_LOCK.json, so R1 single-writer was
violated locally with no git involved (D15). --force now requires --reason and
records the displaced holder. Red-before-green: <paste Step 2 lines>"
```

---

## Task 11: Version skew, and the two documented renames (D22, D25, D26)

`PROTOCOL_VERSION` in `init_sync.py` is never compared with the installed `.ai/protocol/VERSION`, so installed-script/protocol skew is invisible — and migration cannot detect skew it never recorded. Plus: `MILESTONES.md` is referenced in four places but never created, and the "token budgets" name counts lines.

**Files:**
- Modify: `scripts/init_sync.py`, `scripts/checkpoint.py`, `scripts/sync_verify.py`, `scripts/ai_common.py`
- Modify: `templates/AGENTS.md`, `templates/SYNC_PROMPT.md`, `SKILL.md`, `README.md`, `reference.md`
- Test: `tests/test_version_and_naming.py`

**Interfaces:**
- Produces: `ai_common.parse_version(raw: str) -> tuple[int, int, int] | None` (raises `ValueError` on unparseable, returns tuple for `X.Y.Z`); `ai_common.compare_version(a, b) -> int`; `init_sync.check_version_match(root: Path) -> tuple[bool, str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_version_and_naming.py`:

```python
import importlib.util
import subprocess
import sys
from pathlib import Path

from helpers import SCRIPTS, run_python, scaffold

spec = importlib.util.spec_from_file_location("ai_common", SCRIPTS / "ai_common.py")
ai_common = importlib.util.module_from_spec(spec)
sys.modules["ai_common"] = ai_common
spec.loader.exec_module(ai_common)

REPO = SCRIPTS.parent


def test_parse_version_semver_tuple_not_string():
    assert ai_common.parse_version("2.10.0") > ai_common.parse_version("2.9.0")
    assert ai_common.compare_version("2.1.0", "2.1.0") == 0
    assert ai_common.compare_version("2.1.0", "2.0.0") == 1


def test_unparseable_version_is_refused():
    try:
        ai_common.parse_version("v2.0")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_install_reports_newer_local_scripts(ai_repo):
    (ai_repo / ".ai" / "protocol" / "VERSION").write_text("9.9.9\n", "utf-8")
    res = run_python(SCRIPTS / "init_sync.py", [str(ai_repo)], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("VERSION MISMATCH") for ln in res.lines), res.lines
    assert "9.9.9" in res.stdout


def test_downgrade_is_refused(ai_repo):
    res = run_python(SCRIPTS / "init_sync.py", [str(ai_repo)], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    (ai_repo / ".ai" / "protocol" / "VERSION").write_text("99.0.0\n", "utf-8")
    res = run_python(SCRIPTS / "init_sync.py", [str(ai_repo), "--force"],
                     cwd=ai_repo)
    assert res.rc == 1 and "downgrade" in res.stdout.lower(), res.stdout


def test_no_milestones_references_remain():
    """docs/superpowers is excluded on purpose: the spec and this plan discuss the
    D25 removal by name, so a bare git grep could never pass."""
    out = subprocess.run(["git", "grep", "-l", "MILESTONES", "--",
                          ":!docs/superpowers"], cwd=str(REPO),
                         capture_output=True, text=True).stdout
    assert out.strip() == "", out


def test_no_token_budget_wording_remains():
    hits = [str(p.relative_to(REPO)) for p in REPO.rglob("*")
            if p.is_file() and p.suffix in {".md", ".py", ".json"}
            and "docs/superpowers" not in str(p)
            and "token budget" in p.read_text(encoding="utf-8",
                                              errors="ignore").lower()]
    assert hits == [], hits
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_version_and_naming.py -v`
Expected: FAIL — no version comparison exists, and both grep assertions find hits.

- [ ] **Step 3: Implement version handling**

`ai_common.py`:

```python
def parse_version(raw: str) -> tuple[int, int, int]:
    text = (raw or "").strip().lstrip("vV")
    parts = text.split(".")
    if len(parts) != 3:
        raise ValueError(f"not an X.Y.Z version: {raw!r}")
    out = []
    for part in parts:
        if not part.isdigit():
            raise ValueError(f"not an X.Y.Z version: {raw!r}")
        out.append(int(part))
    return out[0], out[1], out[2]


def compare_version(a: str, b: str) -> int:
    left, right = parse_version(a), parse_version(b)
    return (left > right) - (left < right)
```

`init_sync.py` before any write, and `main()` returning `1` on failure:

```python
def check_version_match(root: Path) -> tuple[bool, str]:
    path = root / ".ai" / "protocol" / "VERSION"
    if not path.exists():
        return True, "no existing install"
    try:
        installed = path.read_text(encoding="utf-8-sig").strip()
        delta = compare_version(installed, PROTOCOL_VERSION)
    except ValueError as exc:
        return False, f"unparseable: {exc}"
    if delta > 0:
        return False, (f"{installed} is NEWER than these scripts "
                       f"({PROTOCOL_VERSION}); refuse to downgrade. Run "
                       "git pull in the skill repo, or install with --force "
                       "only if you are sure.")
    if delta < 0:
        return True, f"{installed} -> {PROTOCOL_VERSION} (upgrade)"
    return True, f"{installed} (unchanged)"
```

Print the returned detail as `VERSION MISMATCH: <detail>` when not ok. Also import `compare_version` in `sync_verify.py` and add a `protocol version readable` check asserting `.ai/protocol/VERSION` parses, so a hand-edited junk value is caught by verification too.

- [ ] **Step 4: Do the two renames**

Delete every `MILESTONES.md` mention in `scripts/init_sync.py` (`MANAGED_BLOCK`), `scripts/checkpoint.py` (`cmd_prime`'s "Do NOT read in full" line), `templates/AGENTS.md`, `templates/SYNC_PROMPT.md`. In `cmd_prime` that line becomes `Do NOT read in full: DECISIONS.md, handoff/archive/, state/archive/ — retrieve single entries via DECISIONS_INDEX.md or grep.`

Rename the budget wording in exactly these places and nothing else: `sync_verify.py` docstring check list, the function name `check_token_budgets` → `check_line_budgets`, its call site, `SKILL.md` frontmatter description and body, `README.md` (both the English and the 中文说明 sections), `reference.md`'s "Token budgets" heading → "Line budgets" plus one added sentence: `A line is a weak proxy for tokens in CJK state files, which this protocol permits; real token accounting is a wave-2 measurement, not a wave-1 claim.` Keep every printed check name (`budget <path>`) byte-identical.

- [ ] **Step 5: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git commit -am "fix: compare protocol versions instead of assuming them; rename token->line budgets

PROTOCOL_VERSION was never compared with the installed VERSION, so skew was
invisible and unrecorded (D22). MILESTONES.md was referenced in four places but
never created (D25); budgets counted lines while called tokens (D26).
Red-before-green: <paste Step 2 lines>"
```

---

## Task 12: Wave 1a closure — full run, evidence, docs

No new behaviour. This task is the gate that makes the wave auditable.

**Files:**
- Modify: `README.md`, `SKILL.md`, `reference.md`, `CHANGELOG.md` (created here)
- Test: `tests/test_acceptance_wave1a.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the acceptance test for the central promise**

`tests/test_acceptance_wave1a.py`:

```python
"""Spec §10.B: a second machine can take over. Two independent installs, one
shared remote, lock held on one side must block the other."""

from helpers import git, run_python, scaffold


def test_two_machines_one_remote_one_pen(tmp_path):
    remote = tmp_path / "origin.git"
    git(tmp_path, "clone", "--quiet", "--bare", str(remote), "bare.git")
    a = tmp_path / "machineA"
    git(tmp_path, "clone", "--quiet", str(remote), str(a))
    (a / "README.md").write_text("# a\n", "utf-8")
    git(a, "add", "-A")
    git(a, "-c", "user.name=A", "-c", "user.email=a@example.invalid",
        "commit", "-q", "-m", "seed")
    git(a, "push", "-q", "origin", "HEAD:main")

    b = tmp_path / "machineB"
    git(tmp_path, "clone", "--quiet", "--branch", "main", str(remote), str(b))
    for box in (a, b):
        res = scaffold(box)
        assert res.rc == 0, box.name
        git(box, "add", "-A")
        git(box, "-c", "user.name=Owner", "-c", "user.email=o@example.invalid",
            "commit", "-q", "-m", "install cross-harness-sync")
        git(box, "push", "-q", "origin", "HEAD:main")

    cp_a = a / ".ai" / "scripts" / "checkpoint.py"
    cp_b = b / ".ai" / "scripts" / "checkpoint.py"
    assert run_python(cp_a, ["--lock", "--agent", "claude-code",
                             "--reason", "wave1a"], cwd=a).rc == 0
    git(a, "add", "-A")
    git(a, "-c", "user.name=Owner", "-c", "user.email=o@example.invalid",
        "commit", "-q", "-m", "lock: claude-code")
    git(a, "push", "-q", "origin", "HEAD:main")

    git(b, "pull", "--ff-only", "-q", "origin", "main")
    res = run_python(cp_b, ["--lock", "--agent", "codex"], cwd=b)
    assert res.rc == 1, res.stdout
    assert "claude-code" in res.stdout

    assert run_python(cp_a, ["--unlock", "--agent", "claude-code"],
                      cwd=a).rc == 0
    git(a, "add", "-A")
    git(a, "-c", "user.name=Owner", "-c", "user.email=o@example.invalid",
        "commit", "-q", "-m", "unlock")
    git(a, "push", "-q", "origin", "HEAD:main")
    git(b, "pull", "--ff-only", "-q", "origin", "main")
    assert run_python(cp_b, ["--lock", "--agent", "codex"], cwd=b).rc == 0
```

- [ ] **Step 2: Run the whole suite on this machine, then record the platform matrix**

Run: `python -m pytest tests/ -q -rs`
Expected: all PASS on Windows (the real target of D5/D8/D13/D14). Then confirm the POSIX-only reasoning by reading `helpers.make_repo`'s `git init -b main` (needs git ≥ 2.28) and, if a POSIX shell is available, run the suite there too. If POSIX cannot be exercised here, say so in the commit message — do **not** mark the matrix as verified.

- [ ] **Step 3: Write `CHANGELOG.md`**

```markdown
# Changelog

## v2.1.0 (unreleased — wave 1a)

Fixed (each with a regression test proven to fail on v2.0.0):

- A merge-conflicted or corrupt `WRITER_LOCK.json` read as "no lock", so two
  machines both writing state was the *expected* outcome of contention, not an
  accident. It is now reported as HELD. (D1)
- `--unlock` released another agent's lock, and `--prime`/`--handoff` told users
  to run it that way. (D2)
- One custom `budgets` entry replaced all default caps; malformed config fell
  back to defaults with exit 0. The checker could certify repos it had stopped
  checking. (D3, D4)
- `text=True` on a cp936 console silently produced `stdout=None` with rc 0. (D5)
- `secret_mirrors` could never pass on a fresh clone; first `--handoff` crashed
  on directories git does not track. (D6, D16)
- Lock writes non-atomic on Windows; all writers shared one temp name. (D8, D9)
- `expires_at` absent or malformed meant a lock that never expires. (D10)
- Timeouts and a missing git aborted verification with a traceback; non-git trees
  reported misleading rc=128. (D11, D12, D13)
- `fnmatch` case-folding on Windows would make one config match different file
  sets per machine — recorded as a 1b constraint, not yet applicable. (D14)
- Linked worktrees each held their own lock; symlinked `.ai` redirected writes. (D15)
- `--force` overwrote live state; `copy_file` could abort mid-install. (D7, D24)
- `.gitignore` re-appended lines it already had and misreported the count;
  `--no-agents-block` left verification permanently red. (D17, D18)
- A script copied outside `.ai/scripts/` silently audited the parent directory. (D19)
- Protocol version skew was never compared; `.env` BOMs and string-typed
  `extra_checks` commands were mishandled. (D20, D21, D22)
- Three divergent required-file lists, none of which required `ROLE_POLICY.md`. (D23)
- Removed `MILESTONES.md` references; renamed "token budgets" to "line budgets". (D25, D26)

Skips are now reported as `SKIP` and counted apart from passes: a check that could
not run is never a green line.
```

- [ ] **Step 4: Update the user-facing docs to match what actually changed**

In `SKILL.md`: the close-out sequence becomes `sync_verify.py all green → --unlock --agent <name> → commit → push`; add one line under Scripts — `scripts/ai_common.py` — shared primitives (subprocess bytes, root resolution, stdio guard), copied alongside the other two. In `reference.md`: add the `error` lock state and the never-auto-expires rule to "Advisory writer lock"; note that linked worktrees are refused because the lock is per-worktree; add `required_files`, `check_timeout` to the config reference. In `README.md`: add the same two lines in English and the 中文说明 section, and one sentence stating that skips are distinct from passes.

- [ ] **Step 5: Run everything once more and confirm the documented check count matches**

Run: `python -m pytest tests/ -q && python -c "import pathlib,re;t=pathlib.Path('README.md').read_text(encoding='utf-8');print('docs mention check counts:', re.findall(r'\d+ checks', t))"`
Expected: tests all pass; if the docs quote a count, it equals the number the suite prints.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: wave 1a changelog, doc sync, and the two-machine acceptance test

Adds the spec §10.B end-to-end check: two clones of one remote, a lock taken on
one blocks the other, releasing it lets the second proceed. Red-before-green
evidence for all 25 fixes is in the individual task commits."
```

- [ ] **Step 7: Stop and report**

Report: suite pass counts on each platform exercised, the tripwire check count, and the three deferred items (D14 constraint carried to 1b; real token measurement deferred to wave 2; `--migrate` unexercised until 1b because the governance keys it seeds do not exist yet). Do not push. Do not open a PR. Do not start 1b.

---

## Self-Review (performed by the plan author before handoff)

**Spec coverage.** §5 defects D1–D13 and D15–D26 all map to a task: D1/D10 → T4, D2 → T5, D3/D4 → T2, D5/D11/D12/D13 → T6, D6/D16 → T7, D7/D24 → T8, D8/D9 → T5, D15 → T10, D17/D18 → T9, D19 → T1, D20/D21 → T6, D22/D25/D26 → T11, D23 → T3. D14 is deliberately not in 1a and appears as a Global Constraint instead. §6 governance and §8 migration have no tasks here by design — they are 1b. §10.A R4 evidence is a step in every task; §10.B is T12 Step 1; §10.E greps are T11 Step 1. §10.C and §10.D belong to 1b.

**Placeholders.** None: every code step carries its code, and every run step carries an expected result. The `<paste Step 2 lines>` markers are instructions for the implementer to insert real captured output, which is the point of R4, not missing content.

**Type consistency.** `LockStatus(state, holder, detail)` is defined once in T4 and consumed by T5 and T10 under the same field names. `record(name, ok, evidence)` gains its third `None` state in T7 and T1's `RepoError` path in T6 relies on it already existing — both are the same function in `sync_verify.py`, so T7 must land after T6 (the task order above honours that). `ai_common` exports are named identically in T1, T3, T6, T10, T11. `resolve_roots` returns `(AI_DIR, ROOT)` everywhere. `helpers.Result` field names are used unchanged in every test.

**Known ordering constraint worth stating to executors:** Task 3 writes `authorizations/INDEX.md` into `DEFAULT_REQUIRED_FILES`, which forces `init_sync.py` to create it in the same task; if T3 is executed alone, fresh installs go red until T3 Step 4 lands. Do not split T3.
