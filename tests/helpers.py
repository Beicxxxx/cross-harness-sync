"""Test-harness primitives: byte-safe subprocess runner + throwaway git repos.

PYTHON FLOOR IS 3.9. The `from __future__ import annotations` below is not
cosmetic: PEP 604 unions (`bytes | None`) in parameter/attribute annotations are
evaluated at def- and class-creation time, which 3.9 cannot do, so without the
future import `import helpers` raises TypeError and every test errors during
collection. The shipped scripts carry the same import for the same reason
(`scripts/sync_verify.py`, `scripts/init_sync.py`).

NON-ASCII ASSERTIONS MUST SET THE CHILD ENCODING EXPLICITLY. `run_python`
captures raw bytes and decodes them as UTF-8 with `surrogateescape`, and the
default env deliberately does NOT set PYTHONUTF8/PYTHONIOENCODING: the child
then writes in the host's preferred encoding (on a cp936 console,
`init_sync.py`'s U+2192 arrives as the byte pair A1 FA, which surrogateescape
turns into the lone surrogates \\udca1\\udcfa). That never raises — it silently
compares unequal to the literal text — so any test asserting on non-ASCII
evidence must pass `env=dict(os.environ, PYTHONIOENCODING="utf-8")` itself.
`tests/test_harness_smoke.py` pins this behaviour; Task 6's D5 test relies on
the mismatch staying reachable, which is why it is not "fixed" harness-wide.
"""
from __future__ import annotations

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


def hermetic_env(home: Path | str) -> dict[str, str]:
    """os.environ minus every GIT_* variable, with config/home pointed at `home`.

    A pytest run launched from a git hook (or a plain terminal inside someone's
    real repository) inherits GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE /
    GIT_CONFIG_GLOBAL. Without this scrub those leak into every child, so
    `make_repo` can operate on — and `git config user.email` can write into —
    the developer's outer repository. `home` is always a throwaway directory,
    and both config files are pinned to the null device.
    """
    h = str(home)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env["HOME"] = h
    env["USERPROFILE"] = h
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


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
    """Run a python script with stdout/stderr as RAW BYTES (never `text=`).

    rc 0 with empty output is a test failure, not a pass: callers assert on
    `stdout_raw`/`lines`, and `Result` is built from the bytes the child wrote.
    `env=None` means the ambient env with git state scrubbed (see
    `hermetic_env`); an explicitly passed env is used verbatim so a caller can
    pin the child's encoding — required for any non-ASCII assertion.
    """
    proc = subprocess.run(
        [sys.executable, str(script), *args], cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env if env is not None else hermetic_env(cwd))
    return Result(proc.returncode, decode(proc.stdout), decode(proc.stderr),
                  proc.stdout)


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="surrogateescape",
                          env=hermetic_env(cwd))
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
