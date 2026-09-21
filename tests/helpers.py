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
Such an `env=` is MERGED onto `hermetic_env`'s scrubbed base (caller's
deliberate keys win), so pinning an encoding cannot reintroduce git state.
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


def is_inside_repo(path: Path | str) -> bool:
    """True if `path` is this checkout or anything below it.

    Compares resolved path PARTS rather than a string prefix, so a sibling
    directory named `<repo>-sibling` is not "inside" the repository.
    """
    resolved = Path(path).resolve()
    return resolved == REPO_ROOT or REPO_ROOT in resolved.parents


# Fixed identity for every child git process (see `hermetic_env`). The address is
# on `.invalid`, which RFC 2606 reserves so it can never route to a real person,
# and it deliberately matches the repo-local identity `make_repo` writes so a
# test sees one identity whichever way git obtains it.
GIT_IDENTITY = "Test Human"
GIT_IDENTITY_EMAIL = "t@example.invalid"


def decode(raw: bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", "surrogateescape")


def _is_git_var(key: str) -> bool:
    return key.upper().startswith("GIT_")


def hermetic_env(home: Path | str,
                 overrides: dict[str, str] | None = None) -> dict[str, str]:
    """os.environ minus every GIT_* variable, with config/home pointed at `home`.

    A pytest run launched from a git hook (or a plain terminal inside someone's
    real repository) inherits GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE /
    GIT_NAMESPACE / GIT_QUARANTINE_PATH / GIT_CONFIG_GLOBAL. Without this scrub
    those leak into every child, so `make_repo` can operate on — and
    `git config user.email` can write into — the developer's outer repository.
    `home` is always a throwaway directory, and both config files are pinned to
    the null device.

    Hermetic alone is not usable: with no readable config file a `git commit`
    inside a `git clone` fails rc 128 "Author identity unknown", because a clone
    inherits no repo-local `[user]` block (only `make_repo` sets one, which is
    why it never showed up there). Tasks 7 and 12 commit inside clones, so the
    identity is supplied through the environment instead — the fixture identity,
    never the developer's own.

    `overrides`, when given, is merged ON TOP so a caller can pin one deliberate
    key (PYTHONIOENCODING for a non-ASCII assertion, an emptied PATH). A GIT_*
    override whose value merely repeats the ambient one — which is what
    `dict(os.environ, ...)` produces for all of them — is dropped, so building an
    env from os.environ can never re-open the leak this function closes.
    """
    h = str(home)
    env = {k: v for k, v in os.environ.items() if not _is_git_var(k)}
    env["HOME"] = h
    env["USERPROFILE"] = h
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_AUTHOR_NAME"] = GIT_IDENTITY
    env["GIT_AUTHOR_EMAIL"] = GIT_IDENTITY_EMAIL
    env["GIT_COMMITTER_NAME"] = GIT_IDENTITY
    env["GIT_COMMITTER_EMAIL"] = GIT_IDENTITY_EMAIL
    for k, v in (overrides or {}).items():
        if _is_git_var(k) and os.environ.get(k) == v:
            continue
        env[k] = v
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


def run_python(script: Path, args: Sequence[str] = (), *,
               cwd: Path | str, env: dict | None = None) -> Result:
    """Run a python script with stdout/stderr as RAW BYTES (never `text=`).

    `cwd` is a REQUIRED keyword argument. It used to default to `REPO_ROOT`, so
    a call that simply forgot it ran a shipped script with this live checkout as
    its working directory — the same class of accident this file exists to
    prevent, one argument wide. Passing `REPO_ROOT` explicitly is still allowed
    (a `--help` smoke test does exactly that); silently landing there is not.

    rc 0 with empty output is a test failure, not a pass: callers assert on
    `stdout_raw`/`lines`, and `Result` is built from the bytes the child wrote.
    `env=None` means the ambient env with git state scrubbed (see
    `hermetic_env`); an explicitly passed env is MERGED onto that scrubbed base,
    so a caller can pin the child's encoding — required for any non-ASCII
    assertion — without re-importing GIT_DIR or a missing identity.
    """
    proc = subprocess.run(
        [sys.executable, str(script), *args], cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=hermetic_env(cwd, env))
    return Result(proc.returncode, decode(proc.stdout), decode(proc.stderr),
                  proc.stdout)


def git(cwd: Path, *args: str) -> str:
    """Run git in `cwd` and assert it succeeded.

    Refuses any target inside this checkout (`is_inside_repo`). Every helper
    here is meant to operate on a throwaway repository; a `git add` / `commit`
    aimed at the repository under test does not just pollute a fixture, it
    rewrites the branch the whole wave is working on.
    """
    if is_inside_repo(cwd):
        raise RuntimeError(
            f"refusing to run git inside the repository under test: {cwd} "
            f"(cross-harness-sync checkout, REPO_ROOT={REPO_ROOT}); "
            "use make_repo(tmp_path) for a git target")
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="surrogateescape",
                          env=hermetic_env(cwd))
    assert proc.returncode == 0, f"git {' '.join(args)} -> {proc.stderr}"
    return proc.stdout.strip()



def make_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one commit, under `tmp_path`."""
    if is_inside_repo(tmp_path):
        # Checked before anything is created: `git init` inside this checkout
        # would nest a repository the caller's `git add` can pick up.
        raise RuntimeError(
            f"refusing to build a fixture repo inside the repository under "
            f"test: {tmp_path} (cross-harness-sync checkout)")
    repo = tmp_path / "project"
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", GIT_IDENTITY_EMAIL)
    git(repo, "config", "user.name", GIT_IDENTITY)
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
