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
# Deliberately absent: every file the installer does not write. Wave 1b's
# `--migrate` creates `.ai/state/authorizations/INDEX.md` (and `init_sync.py`
# now writes it on a fresh install too, from `templates/authorizations/`), so it
# belongs on this list; requiring a file nothing writes would make every fresh
# install red. The flip and the template landed in ONE commit for that reason.
DEFAULT_REQUIRED_FILES = [
    ".ai/state/CURRENT.md",
    ".ai/state/TASK.md",
    ".ai/state/BLOCKERS.md",
    ".ai/state/ROLE_POLICY.md",
    ".ai/state/DECISIONS.md",
    ".ai/state/DECISIONS_INDEX.md",
    ".ai/handoff/LATEST.md",
    ".ai/protocol/VERSION",
    ".ai/state/authorizations/INDEX.md",
]

# The governance floor under the required-file list, living next to the list it
# protects. `required_files` merges by REPLACE — which is what lets a repo with
# no decision log say so — and that same replace is one key away from dropping,
# in one line of config, the files that carry the protocol's safety guarantees. Spec 4 lets a check be skipped only after proving
# necessity elsewhere. The reason this floor exists is NOT that the two commands
# miss these files — since `51944cf` both union this same object (`--validate`
# reads the config and the floor, `sync_verify.py` prints `protocol version
# readable`) — it is that a config edit must never be able to un-check a safety
# file. So the floor is unioned back in
# after the merge, and unlike the rest of that key it is NOT configurable: config
# may add requirements and may drop the optional tail (DECISIONS, DECISIONS_INDEX,
# LATEST), nothing more.
#
# It moved here from `sync_verify.py` with `with_required_file_floor()` below,
# because `checkpoint.py --validate` has to union the same floor over the same
# config key or the two commands answer different questions again (lane V's
# residual). `sync_verify.REQUIRED_FILE_FLOOR` still resolves.
REQUIRED_FILE_FLOOR = (
    ".ai/state/CURRENT.md",
    ".ai/state/TASK.md",
    ".ai/state/BLOCKERS.md",
    ".ai/state/ROLE_POLICY.md",
    ".ai/protocol/VERSION",
)


def with_required_file_floor(declared: list[str]) -> tuple[list[str], list[str]]:
    """`(to_walk, floor_only)` — the one place the floor is unioned in.

    Both enforcement commands walk `config["required_files"]` with
    `REQUIRED_FILE_FLOOR` restored after the replace policy, in the same order
    (declared entries first, restored floor entries second), so one deleted file
    cannot be a FAIL to one of them and an silence to the other. `floor_only` is
    returned separately because the verifier has to NAME the act of narrowing
    coverage, and a caller that only walks files can ignore it.
    """
    entries = list(declared)
    floor_only = [rel for rel in REQUIRED_FILE_FLOOR if rel not in entries]
    return entries + floor_only, floor_only


def parse_version(raw) -> tuple[int, int, int]:
    """`X.Y.Z` as an int tuple, or `ValueError`. Never `None`.

    D22 exists because there was no such thing: `PROTOCOL_VERSION` was a string
    nobody compared, and comparing version STRINGS gets `2.10.0` wrong by putting
    it below `2.9.0`. Returning an optional here would only move the bug — the
    caller would have to remember to check, which is the fail-open shape D5
    exists to end — so a stamp this tool cannot read raises and every caller has
    to say what it will do about it.
    """
    text = (raw or "").strip().lstrip("vV") if isinstance(raw, str) else ""
    parts = text.split(".")
    if len(parts) != 3:
        raise ValueError(f"not an X.Y.Z version: {raw!r}")
    out = []
    for part in parts:
        if not part.isdigit():
            raise ValueError(f"not an X.Y.Z version: {raw!r}")
        out.append(int(part))
    return out[0], out[1], out[2]


def compare_version(a, b) -> int:
    """-1 / 0 / 1 for `a` older / equal / newer than `b`, numerically."""
    left, right = parse_version(a), parse_version(b)
    return (left > right) - (left < right)


# Imported here rather than in the header because these are the module's only
# readers and they sit below: `_GOV_KEY = re.compile(...)` runs at IMPORT time,
# so an `import re` placed any lower than this would leave that line without a
# name and the whole module unloadable.
import fnmatch  # noqa: E402  (module-level, beside its only users by design)
import re  # noqa: E402  (module-level, beside its only users by design)


def parse_governance_block(text):
    """`(fields, None)` or `({}, why)`; `(None, None)` when there is no block.

    Spec §6's record-format contract, and the three shapes that make this parser
    worth having rather than a `split(":")` loop: the fence gives unambiguous
    start/end (so no nested-bullet, stray-line or continuation problem), a
    repeated key is FATAL because this is audit data and last-wins would let a
    second `verdict:` silently overrule the first, and an unfilled `<template>`
    value is fatal because a record shipped with its placeholders intact reads as
    a completed audit. An unknown key is kept: the schema must stay
    forward-compatible or a newer writer breaks every older reader.

    The absent block returns `(None, None)` — NOT a default dict — so the caller
    can name a WARN. A legacy document with no governance block is the one
    degradation here, and a degradation may never become a PASS (§6, §7).
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
    """D14: forward-slash patterns, matched case-sensitively and separators first.

    Both halves are load-bearing. `fnmatch.fnmatchcase` rather than
    `fnmatch.fnmatch` because the latter applies `os.path.normcase`, which on
    Windows lowercases BOTH sides — so the pattern `a/B/*.md` would match
    `a/b/c.md` there and the coverage walk would pass on the machine that wrote
    the config and fail on the one that did not. Backslashes are folded to `/`
    before matching because git prints `/` and `Path.as_posix()` prints `/` while
    a caller holding a Windows path hands over backslashes: same file, different
    answer. `*` is NOT per-segment: `fnmatch`'s `*` crosses `/`, so `docs/*.md` also
    matches `docs/a/b.md`. That direction is the fail-closed one — a nested file can
    never slip out of the governed set by sitting deeper than the pattern's author
    pictured — and B1 must not assume segment-wise globbing: per-segment semantics would
    be a different matcher, not a tweak of this one.
    """
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
    """Three-valued reduction of a git result: TRUE / FALSE / UNKNOWN.

    rc 0 and 1 are the only answers that MEAN anything; everything else (128 for
    a shallow clone or an absent object, a timeout, git missing) is "cannot
    determine" and must stay distinguishable from FALSE. Reducing it to a boolean
    is what turns an unverifiable history into a licence to clobber, so UNKNOWN
    propagates and the caller halts on it.
    """
    if res.timed_out or res.rc not in (0, 1):
        return "UNKNOWN"
    return "TRUE" if yes_when(res.rc) else "FALSE"


def git_ancestor(root, ancestor, descendant):
    """TRUE / FALSE / UNKNOWN; rc 128 (shallow, absent object) is UNKNOWN."""
    res = run_git(root, ["merge-base", "--is-ancestor", ancestor, descendant], timeout=15)
    return _tri(res, lambda rc: rc == 0)


def commit_exists(root, sha):
    """Existence by `cat-file -e`, not `rev-parse --verify`.

    Measured: `rev-parse --verify <absent>` exits 0 and echoes the string back, so
    as an existence probe it reports every absent SHA as present. `cat-file -e`
    refuses instead, and the `^{commit}` suffix pins the question to commits rather
    than "any object with this id" (a blob id must not pass as a commit).

    One correction to the shipped `_tri` shape, measured on git 2.x here: `cat-file
    -e <absent>^{commit}` exits **128**, not 1 — so a plain `_tri` reduction would
    answer UNKNOWN for every absent commit and existence would never be decidable,
    which is not what §6 asks of this probe either. rc 128 is therefore split by the
    one thing that makes "absent" and "not fetched yet" genuinely different: whether
    this repository's history is truncated. Shallow, timing out, or a git that
    cannot even answer (`is_shallow` -> UNKNOWN for a dubious-ownership or corrupt
    repo) stays UNKNOWN and halts the caller; a whole repository that has no such
    object says FALSE.
    """
    res = run_git(root, ["cat-file", "-e", f"{sha}^{{commit}}"], timeout=15)
    if res.timed_out:
        return "UNKNOWN"
    if res.rc in (0, 1):
        return _tri(res, lambda rc: rc == 0)
    if res.rc == 128 and is_shallow(root) == "FALSE":
        return "FALSE"
    return "UNKNOWN"


def is_shallow(root):
    """TRUE / FALSE / UNKNOWN — how much of the history the other two can be trusted for.

    §4: **rc == 0 is never sufficient.** `rev-parse --is-shallow-repository` answers with
    one of exactly two words, so the words are compared and nothing else is: `true` ->
    TRUE, `false` -> FALSE, any other stdout at rc 0 (empty, a warning that leaked onto
    stdout, a future git that says `unknown`) -> UNKNOWN. Collapsing an unrecognised
    answer to FALSE would be the one mistake this probe cannot make, because
    `commit_exists` reads FALSE here as licence to call an object it has never seen
    absent, and §6's whole three-valued rule is that a missing fact is named, not denied.
    """
    res = run_git(root, ["rev-parse", "--is-shallow-repository"], timeout=15)
    if res.timed_out or res.rc != 0:
        return "UNKNOWN"
    answer = res.out().strip()
    if answer == "true":
        return "TRUE"
    if answer == "false":
        return "FALSE"
    return "UNKNOWN"


def log_paths(root, args, pathspec):
    """NUL-split paths: `(paths, None)` or `(None, why)`.

    `(None, None)` never happens on the success path — an empty log is a real
    answer, [] is returned for it — so a `None` here is always a failure the
    caller has to name. `-z` is what makes that safe: it emits raw unquoted bytes,
    so a path with a space, a non-ASCII name, or a quote in it cannot forge a
    record or make one disappear the way `--name-only`'s C-style quoting would.
    Split on NUL, never `splitlines()`, for the same reason.

    WHAT EACH ELEMENT IS, measured, because it is not "one path per element": a
    record is one COMMIT's block, and with §6.3's `--pretty=format:%H` the block is
    `"<sha>\n<first path>"` followed by `"<path>"` records — the sha arrives glued to
    the first path of its own commit, since `-z` terminates blocks, not lines. A
    caller that treats this list as bare paths counts one path per commit and
    under-reports coverage; `record.partition("\n")` is the split that attributes a
    path to the commit that touched it.
    """
    res = run_git(root, ["log", *args, "--name-only", "-z", "--", *pathspec], timeout=15)
    if res.timed_out:
        return None, "git log timed out"
    if res.rc != 0:
        detail = decode(res.stderr).strip().splitlines()
        return None, f"git log rc={res.rc}: {detail[-1][:160] if detail else 'no stderr'}"
    return [decode(b) for b in res.stdout.split(b"\x00") if b], None


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


# The PROTOCOL version these scripts implement, and the number
# `.ai/protocol/VERSION` is stamped with. It lives HERE, in the one module the
# installer ships, because lane Z finding 7 is precisely the hole a constant
# that is NOT installed leaves: while it lived only in `init_sync.py` nothing in
# an installed tree could cross-check the stamp, so `99.99.99` printed a PASS in
# a tree whose own scripts refused to upgrade it. One copy, read by the
# installer, the verifier, and any companion record the wave-1b migration writes.
PROTOCOL_VERSION = "2.1.0"

# The canonical id lengths (§6): 40-hex for the SHA-1s this protocol stores, and
# 64-hex for the SHA-256 digest that pins ROLE_POLICY.md. They are constants, not
# literals scattered per script, because "is this a commit id" is a question three
# callers ask and a wrong answer there reads a garbage field as a verified sha.
SHA_HEX_LEN = 40
SHA256_HEX_LEN = 64

# Where an authorization lives (§6): the directory v2.0 mandated ("one stage = one
# authorization file") but gave no canonical home, so nothing could read it back.
AUTHORIZATIONS_SUBDIR = "state/authorizations"

_GOVERNANCE_OPEN = "```governance"
_GOVERNANCE_CLOSE = "```"
_GOV_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_GOV_UNFILLED = re.compile(r"^<[^<>]*>$")  # ASCII angle brackets only


def protect_stdio() -> None:
    """Force UTF-8 on both streams; consoles may not support what we print.

    Lane Z finding 5: the utf-8 fast path used to `continue`, leaving a stream
    at `errors="strict"`, so an evidence string carrying surrogate escapes from
    `decode(..., "surrogateescape")` raised on the way OUT and the verifier lost
    a whole check section. It is reconfigured to `backslashreplace` now: the
    bytes still reach the operator, as visible backslash escapes, rather
    than as the silent replacement character the old errors=replace path
    would have left behind.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        enc = (getattr(stream, "encoding", None) or "").lower()
        if stream is None:
            continue
        if enc.startswith("utf-8"):
            try:
                if getattr(stream, "errors", "") == "strict":
                    stream.reconfigure(errors="backslashreplace")
            except (AttributeError, ValueError, OSError):
                pass
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


def _canon(path: str) -> str:
    """Comparable form of a path git printed for a path this module built."""
    return os.path.normcase(path.replace("\\", "/").rstrip("/"))


def _strip_device_prefix(text: str) -> str:
    """Drop the extended Win32 device prefix a junction's target arrives with.

    A junction reports its target in the extended Win32 device form: a doubled
    backslash, a question mark, then the path. Printing that hands the user a
    string nobody else can paste, so it is dropped here.
    """
    for prefix in ("\\\\?\\", "\\??\\"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


# `stat` is imported here rather than in the header because the reparse attribute
# below is its only reader, and only on the one branch that needs it.
import stat  # noqa: E402  (module-level, beside its only user by design)


def _relocated(path: Path):
    """None for an ordinary path, else `(mechanism, target)`.

    "Is this a symlink?" is the wrong question, and r2 finding B7a-1 measured
    why: a Windows directory junction (`mklink /J`) answers False to
    `Path.is_symlink()` and True to `is_dir()`, and needs no
    SeCreateSymbolicLinkPrivilege and no Developer Mode. A predicate limited to
    symlinks therefore classifies a relocated `.ai` as "normal" on the exact
    host that was told it could not be tested. REPARSE_POINT is the
    mechanism-independent attribute — it is set for junctions and symlinks
    alike — and `getattr` keeps the 3.9 floor honest on platforms without it.
    """
    if path.is_symlink():
        return "a symlink", _read_target(path)
    rp = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not rp:
        return None
    try:
        attrs = path.stat(follow_symlinks=False).st_file_attributes
    except FileNotFoundError:
        return None
    except OSError as exc:
        # Not "clean": a payload path this process cannot probe is not a payload
        # path it may call ordinary (spec §4). The caller names the kind and why.
        return "undetermined", f"cannot probe {path}: {exc}"
    if not (attrs & rp):
        return None
    return "a directory junction (Windows reparse point)", _read_target(path)


def _read_target(path: Path) -> str:
    try:
        return Path(_strip_device_prefix(str(path.readlink()))).as_posix()
    except OSError as exc:
        return f"<target not readable: {type(exc).__name__}>"


def invocation_layout(root: Path, script_file: str) -> tuple[str, str]:
    """`(kind, detail)` for THIS invocation: the witness first, then the checkout.

    Exported so `checkpoint.py --lock` and `sync_verify.py`'s install-layout
    check answer with one function instead of one of them being blind (finding
    B7a-6). The next lane wires the verifier; this lane pins the signature.
    """
    kind, detail = _invocation_witness(root, script_file)
    if kind != "normal":
        return kind, detail
    return checkout_layout(root)


def _invocation_witness(root: Path, script_file: str) -> tuple[str, str]:
    """The unresolved invocation path, which is the only thing that saw the link.

    `resolve_roots()` calls `Path.resolve()`, which follows symlinks AND
    junctions, so an invoked `.ai` that is relocated leaves ROOT naming the
    target's parent — a tree that then looks perfectly ordinary from inside. The
    witness is trusted only in the shape it claims, `<root>/.ai/scripts/<script>`:
    invoked from `.ai/scripts/` itself the old code probed
    `<root>/.ai/scripts`'s `is_symlink()`, always False, and reported a linked
    install as normal (finding B7a-4). A shape this function cannot describe is
    undetermined, never clean.
    """
    script = Path(script_file)
    if not script.is_absolute():
        script = Path.cwd() / script
    parent, logical_ai = script.parent, script.parent.parent
    if parent.name != "scripts" or logical_ai.name != AI_DIR_NAME:
        return "outside-repo", (f"invocation layout not determined: {script} is "
                                "not under " + AI_DIR_NAME + "/scripts/")
    state = _relocated(logical_ai)
    if state is None:
        return "normal", str(root)
    mechanism, target = state
    if mechanism == "undetermined":
        return "outside-repo", f"invocation layout not determined: {target}"
    return "symlinked", (f"{logical_ai} is relocated by {mechanism} -> {target}, "
                         f"and ROOT resolved through it to {root}")


def checkout_layout(root: Path) -> tuple[str, str]:
    """Classify the checkout `root` names: `(kind, detail)`, kind one of five.

    "normal" | "linked-worktree" | "symlinked" | "not-repository-root" |
    "outside-repo".

    D15 has two halves and this is where both become visible:

    * A LINKED WORKTREE holds its own on-disk `.ai/runtime/WRITER_LOCK.json`.
      The lock is tracked so a second MACHINE sees the first machine's hold
      through `git pull`; two worktrees on one machine share no such thing, so
      R1's single-writer rule is broken locally, silently, with no git involved.
    * A RELOCATED part of the install means the payload is not in this tree.
      The kind keeps the name "symlinked" because that is the contract callers
      and `forced_layout` records already carry; `detail` says which mechanism was
      found — a symlink or, on Windows, a junction — because those are different
      things to fix (finding B7a-1).

    "not-repository-root" is the fifth kind: `--is-inside-work-tree` is true for
    EVERY descendant of a repository, so an install in a subdirectory used to
    print "normal" and advertise a tracked lock that travels by the OUTER
    repository's `git pull` (finding B7a-2).

    "outside-repo" carries "the layout could not be determined" as well as "not
    a repository": an rc 128 from any probe is an ERROR state, and a caller must
    never read it as "normal" (spec §4 — a degradation is named, and "cannot
    tell" is not "clean"). `detail` says which of the two it was.

    Advisory by design: this classifies, it does not enforce. Callers refuse and
    offer the documented `--force` escape hatch.
    """
    ai = root / AI_DIR_NAME
    for rel in LAYOUT_PAYLOAD_PATHS:
        part = ai if not rel else ai / rel
        state = _relocated(part)
        if state is None:
            continue
        mechanism, target = state
        if mechanism == "undetermined":
            return "outside-repo", (f"{_symlink_label(part, ai)}: {target}; "
                                    "layout not determined")
        return "symlinked", (f"{_symlink_label(part, ai)} is relocated by "
                             f"{mechanism} -> {target}")

    inside = run_git(root, ["rev-parse", "--is-inside-work-tree"], timeout=15)
    git_dir = run_git(root, ["rev-parse", "--absolute-git-dir"], timeout=15)
    if not inside.ok or not git_dir.ok:
        rc = inside.rc if not inside.ok else git_dir.rc
        return "outside-repo", (
            f"git could not locate a work tree for {root} (rev-parse rc {rc}); "
            "layout not determined")
    common = run_git(root, ["rev-parse", "--path-format=absolute",
                            "--git-common-dir"], timeout=15)
    probe = "--path-format=absolute --git-common-dir"
    cd = common.out().strip() if common.ok else ""
    if not common.ok:
        # `--path-format` needs git 2.31. On an older client the only failure
        # bucket here used to be "outside-repo", so EVERY legitimate main
        # checkout was refused with a message blaming the user's location
        # (finding B7a-5). Ask it the old way, resolve the answer against `root`,
        # and if git still will not say, name the version as the reason.
        fallback = run_git(root, ["rev-parse", "--git-common-dir"], timeout=15)
        probe = "--git-common-dir (older git)"
        if fallback.ok:
            raw = fallback.out().strip().replace("\\", "/").rstrip("/")
            cd = raw if Path(raw).is_absolute() else str((root / raw))
    if not cd:
        return "outside-repo", (
            f"{root} is inside a work tree but git would not report its common "
            f"directory (rev-parse {probe} rc {common.rc}, git 2.31 or older "
            "without a usable --git-common-dir answer); layout not determined")
    gd = _canon(git_dir.out().strip())
    cd = _canon(cd)
    # `os.path.normcase` rewrites forward slashes to backslashes on Windows, so
    # the marker has to be tested against the slash form again or every linked
    # worktree silently classifies as a main checkout.
    if gd != cd and _WORKTREE_MARKER in gd.replace("\\", "/"):
        return "linked-worktree", f"{gd} (common {cd})"
    top = run_git(root, ["rev-parse", "--show-toplevel"], timeout=15)
    if not top.ok:
        return "outside-repo", (
            f"git would not report the work tree top level for {root} (rev-parse "
            f"--show-toplevel rc {top.rc}); layout not determined")
    toplevel = _canon(top.out().strip())
    if toplevel != _canon(str(root)):
        return "not-repository-root", (
            f"{root} is not the root of the work tree git reports "
            f"(--show-toplevel {toplevel}): the tracked lock written here "
            "travels by the OUTER repository's git pull, not this install's")
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

