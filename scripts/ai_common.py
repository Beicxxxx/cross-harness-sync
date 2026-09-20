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

# The files an install must have, in the order the verifier reports them: the
# three L0 startup reads, the governance and decision records, the handoff, and
# the protocol stamp.
#
# D23 was that THREE copies of this list had drifted apart — sync_verify's
# `REQUIRED_FILES`, checkpoint's `--validate`, and checkpoint's `--status` — and
# none of them required ROLE_POLICY.md, so the file that decides who may write
# state could simply be absent. It lives here, next to the other protocol
# constants, so every script imports the same object instead of copying it, and
# the shipped `.ai/sync_config.json` carries the identical list.
#
# Deliberately absent: `.ai/state/authorizations/INDEX.md`. Wave 1b's `--migrate`
# creates and populates it; requiring a file that nothing writes in 1a would make
# every fresh install red for a 1b reason.
DEFAULT_REQUIRED_FILES = [
    ".ai/state/CURRENT.md",
    ".ai/state/TASK.md",
    ".ai/state/BLOCKERS.md",
    ".ai/state/ROLE_POLICY.md",
    ".ai/state/DECISIONS.md",
    ".ai/state/DECISIONS_INDEX.md",
    ".ai/handoff/LATEST.md",
    ".ai/protocol/VERSION",
]

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


# D15: the pieces of the install whose BYTES are the protocol. A symlink at any
# of these paths means the state lives outside this checkout, so it neither
# travels by `git pull` nor is the file another harness or machine reads — the
# same "two writers, one name" failure the tracked WRITER_LOCK.json exists to
# prevent, reached without any git at all.
LAYOUT_PAYLOAD_PATHS = (
    "",                      # .ai itself
    "state",
    "runtime",
    "runtime/WRITER_LOCK.json",
    "scripts",
    "handoff",
    "protocol",
)

# `git rev-parse --absolute-git-dir` for a linked worktree is
# `<main>/.git/worktrees/<name>`, while the common dir stays `<main>/.git`.
_WORKTREE_MARKER = "/worktrees/"


def _symlink_label(path: Path, ai: Path) -> str:
    rel = path.relative_to(ai).as_posix()
    return AI_DIR_NAME if rel in ("", ".") else f"{AI_DIR_NAME}/{rel}"


def checkout_layout(root: Path) -> tuple[str, str]:
    """Classify the checkout `root` names: `(kind, detail)`, kind one of four.

    "normal" | "linked-worktree" | "symlinked" | "outside-repo".

    D15 has two halves and this is where both become visible:

    * A LINKED WORKTREE holds its own on-disk `.ai/runtime/WRITER_LOCK.json`.
      The lock is tracked so a second MACHINE sees the first machine's hold
      through `git pull`; two worktrees on one machine share no such thing, so
      R1's single-writer rule is broken locally, silently, with no git involved.
    * A SYMLINKED part of the install means the payload is not in this tree.
      `resolve_roots()` calls `Path.resolve()`, which follows symlinks, so a
      linked or relocated `.ai` can name a ROOT in a different repository and
      every read, write and report below it is then about the wrong tree.

    "outside-repo" carries "the layout could not be determined" as well as "not
    a repository": an rc 128 from either `rev-parse` is an ERROR state, and a
    caller must never read it as "normal" (spec §4 — a degradation is named, and
    "cannot tell" is not "clean"). `detail` says which of the two it was.

    Advisory by design: this classifies, it does not enforce. Callers refuse and
    offer the documented `--force` escape hatch.
    """
    ai = root / AI_DIR_NAME
    for rel in LAYOUT_PAYLOAD_PATHS:
        part = ai if not rel else ai / rel
        if part.is_symlink():
            try:
                dest = part.readlink().as_posix()
            except OSError as exc:
                dest = f"<target not readable: {type(exc).__name__}>"
            return "symlinked", f"{_symlink_label(part, ai)} is a symlink -> {dest}"

    inside = run_git(root, ["rev-parse", "--is-inside-work-tree"], timeout=15)
    git_dir = run_git(root, ["rev-parse", "--absolute-git-dir"], timeout=15)
    common = run_git(root, ["rev-parse", "--path-format=absolute",
                            "--git-common-dir"], timeout=15)
    if not inside.ok or not git_dir.ok:
        rc = inside.rc if not inside.ok else git_dir.rc
        return "outside-repo", (
            f"git could not locate a work tree for {root} (rev-parse rc {rc}); "
            "layout not determined")
    if not common.ok:
        return "outside-repo", (
            f"{root} is inside a work tree but git would not report its common "
            f"directory (rev-parse --git-common-dir rc {common.rc}); layout not "
            "determined")
    gd = git_dir.out().strip().replace("\\", "/").rstrip("/")
    cd = common.out().strip().replace("\\", "/").rstrip("/")
    if gd != cd and _WORKTREE_MARKER in gd:
        return "linked-worktree", f"{gd} (common {cd})"
    return "normal", str(root)


def worktree_listing(root: Path) -> tuple[list[str], str | None]:
    """`(paths, err)` for every checkout of this repository — the deciding form.

    `err` is set whenever git did not answer, so "no other worktree" and "no
    answer" cannot be confused: an empty list with an error attached is not
    evidence of anything.
    """
    res = run_git(root, ["worktree", "list", "--porcelain"], timeout=15)
    if not res.ok:
        return [], f"git worktree list did not answer (rc {res.rc})"
    return [ln.split(" ", 1)[1] for ln in decode(res.stdout).splitlines()
            if ln.startswith("worktree ")], None


def worktrees(root: Path) -> list[str]:
    """Every checkout path of this repository, for REPORTING only.

    Never branch on this: `[]` also means "git did not answer" (B7a correction
    3), which is exactly the fail-open shape D5 exists to end. A caller that has
    to decide, or that has to say why it cannot, calls `worktree_listing()`.
    """
    paths, _err = worktree_listing(root)
    return paths

