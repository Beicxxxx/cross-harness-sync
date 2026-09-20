#!/usr/bin/env python3
"""Shared, stdlib-only primitives for cross-harness-sync scripts.

Copied next to checkpoint.py and sync_verify.py by init_sync.py. Three rules
make this module exist: (1) subprocess output is captured as BYTES and decoded
with surrogateescape, because text=True on a legacy-codepage console kills the
reader thread and leaves stdout=None with returncode 0; (2) the project root is
derived defensively, because a silently wrong root audits the wrong directory;
(3) every child environment is built here, because git's own GIT_DIR /
GIT_WORK_TREE exports answer for the outer repository no matter which directory
they were started in.

Scripts must not re-implement any of this. If this file is absent from
`.ai/scripts/` the install is broken and has to say so — a second copy of the
plumbing would be a second copy of the fail-open path this module removes.

PYTHON FLOOR IS 3.9: `from __future__ import annotations` below is load-bearing,
not cosmetic, because the PEP 604 unions in the signatures are otherwise
evaluated at def-creation time.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

AI_DIR_NAME = ".ai"

# git's own "which repository am I working on" variables. A git hook exports
# them, and any child git process that inherits one answers about the OUTER
# repository no matter which directory it was started in — the same
# "confidently wrong directory" class D19 exists to end, one level down. They
# are dropped from every child environment; the prompt/lock variables below are
# added, never removed.
GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                     "GIT_QUARANTINE_PATH", "GIT_NAMESPACE")


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
    """Return `(AI_DIR, ROOT)` for a script living at `<ROOT>/.ai/scripts/`.

    D19: `parent.parent` alone is enough to run a copy of this script from
    `scripts/` or `tools/` and audit that directory's parent with total
    confidence and no error, so the expected layout is asserted, not assumed.
    """
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
    """Run git in `root`, never raising: a timeout or a missing git is a result.

    `ok` stays False in both cases, so a caller cannot read a run it could not
    perform as a clean exit 0 (the D5 fail-open).

    The answer is always about `root`: the child environment is built by
    `os_environ_with_git_silence()`, which drops the ambient `GIT_LOCATION_VARS`
    a hook would have exported.
    """
    return run_argv(root, ["git", *args], timeout=timeout,
                    env=os_environ_with_git_silence())


def run_argv(root: Path, argv: list[str], timeout: int = 60,
             env: dict[str, str] | None = None) -> GitResult:
    """The one subprocess plumbing in the project. Everything else calls this.

    Output is captured as raw BYTES (`text=True` is the defect, not the
    convenience), and the two failure modes that used to escape — a hung
    command and an unlaunchable one — come back as `GitResult` values.

    The child environment is always explicit: without an `env` the silenced,
    scrubbed one is built here, and a caller-supplied `env` is still scrubbed,
    so constructing it from `os.environ` cannot re-open the leak.
    """
    child_env = os_environ_with_git_silence() if env is None \
        else scrub_git_location_vars(env)
    try:
        proc = subprocess.run(argv, cwd=str(root), timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=child_env)
    except subprocess.TimeoutExpired as exc:
        # `TimeoutExpired.__init__` sets `.output` and `.stderr`; `.stdout` has
        # been nothing but a transparent alias over `.output` since 3.5, so it
        # does exist on the 3.9 floor but is not the attribute that is defined.
        # Read the one the constructor sets.
        return GitResult(-1, exc.output or b"", exc.stderr or b"", True)
    except OSError as exc:
        return GitResult(-1, b"", str(exc).encode("utf-8", "replace"), False)
    return GitResult(proc.returncode, proc.stdout or b"", proc.stderr or b"", False)


def scrub_git_location_vars(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of `env` without git's per-invocation repository vars."""
    return {k: v for k, v in env.items() if k.upper() not in GIT_LOCATION_VARS}


def os_environ_with_git_silence() -> dict[str, str]:
    """The child environment: no prompts, no optional locks, no outer repo.

    `setdefault` so a caller who exported `GIT_TERMINAL_PROMPT` on purpose keeps
    its own value; the location variables go unconditionally, because the only
    thing they can do here is point git at a repository other than `root`.
    """
    base = scrub_git_location_vars(dict(os.environ))
    base.setdefault("GIT_TERMINAL_PROMPT", "0")
    base.setdefault("GIT_OPTIONAL_LOCKS", "0")
    base.setdefault("GCM_INTERACTIVE", "never")
    return base
