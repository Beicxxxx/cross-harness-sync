"""D15: one install root per checkout, and a linked worktree is refused.

`.ai/runtime/WRITER_LOCK.json` is deliberately git-TRACKED so the advisory
single-writer rule travels to another machine by `git pull`. Two linked git
worktrees on ONE machine break that rule with no git involved at all: each
worktree holds its own on-disk copy, so both print "Writer lock acquired" and
neither sees the other. A symlinked `.ai` is the same defect one level up —
`resolve_roots()` follows symlinks, so ROOT silently names a different tree and
the lock that gets written is not the file anyone pulls.

Design law (spec §4): a degradation may only be a named WARN/refusal, never a
pass, and "cannot determine the layout" is never "normal". The lock stays
ADVISORY — `--force --reason` remains the escape hatch; nothing here enforces.

Two notes on how these tests are built, because both deviate from the brief on
purpose:

* `ai_repo` does NOT commit the install (`init_sync.py` never runs git), so a
  fresh worktree checkout holds no `.ai/`. The brief's `git add -A` fallback is
  banned by the dispatch instructions, so the install is created the supported
  way — `scaffold()` into the worktree — and the fact is asserted, so this file
  tells us the day the fixture starts committing.
* Every refusal here is asserted against `checkpoint.py --lock`, the entry point
  this lane owns. The `sync_verify.py` "install layout" check is the sibling
  lane's file, so the symlink case is pinned at `checkout_layout` + `--lock`.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from helpers import SCRIPTS, git, run_python, scaffold, write_lock

# Loaded under a PRIVATE name for the reason tests/test_ai_common.py gives:
# registering it as `ai_common` would make an in-process load of an INSTALLED
# script resolve `from ai_common import ...` to this object instead of the file
# that ships. Purged after each use so no later lane inherits it.
_REPO_COMMON = "_worktree_refusal_ai_common"
_spec = importlib.util.spec_from_file_location(_REPO_COMMON,
                                               SCRIPTS / "ai_common.py")
ai_common = importlib.util.module_from_spec(_spec)
sys.modules[_REPO_COMMON] = ai_common
_spec.loader.exec_module(ai_common)


def _norm(p) -> Path:
    """Comparable form of a path git printed for one this test built."""
    return Path(str(p)).resolve()


def linked(ai_repo, tmp_path) -> Path:
    """A real linked worktree of the fixture repo (fresh checkout, own `.git` file)."""
    wt = tmp_path / "wt"
    git(ai_repo, "worktree", "add", "-q", "-b", "side", str(wt))
    assert (wt / ".git").is_file(), f"not a linked worktree: {wt}"
    return wt


def worktree_install(ai_repo, tmp_path) -> Path:
    """A linked worktree WITH its own install, i.e. the D15 shape on disk."""
    wt = linked(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    assert not cp.exists(), (
        "the ai_repo fixture now commits the install; scaffold() here is "
        "redundant — drop it rather than keep two installs of one tree")
    res = scaffold(wt)
    assert res.rc == 0, res.stdout + res.stderr
    assert cp.is_file(), "scaffold exited 0 but installed nothing into the worktree"
    return wt


def symlinks_usable(tmp_path) -> bool:
    target = tmp_path / "probe-target"
    target.mkdir(parents=True)
    try:
        (tmp_path / "probe-link").symlink_to(target, target_is_directory=True)
    except OSError as exc:
        print(f"\nD15 SYMLINK PROBE FAILED: {type(exc).__name__} "
              f"winerror={exc.winerror} errno={exc.errno} — os.symlink needs "
              "Developer Mode or elevation here.")
        return False
    return True


def require_symlink(tmp_path) -> None:
    """Skip ONLY when the host cannot make a symlink at all, and say so loudly."""
    if not symlinks_usable(tmp_path / "probe"):
        pytest.skip("os.symlink unusable on this host (WinError 1314: a privilege "
                    "hold, not a code result) — D15's symlink half is UNTESTED "
                    "here; see batch-B7a-report.md")


def lock_record(root: Path) -> dict:
    path = root / ".ai" / "runtime" / "WRITER_LOCK.json"
    assert path.is_file(), f"no lock record written at {path}"
    return json.loads(path.read_text("utf-8-sig"))


# --------------------------------------------------------------------------
# checkout_layout / worktrees: the interface Task 10 produces.
# --------------------------------------------------------------------------

def test_linked_worktree_is_named_as_one(ai_repo, tmp_path):
    """The worktree half of D15, at the classifier: kind, not a guess."""
    wt = linked(ai_repo, tmp_path)
    kind, detail = ai_common.checkout_layout(wt)
    assert kind == "linked-worktree", (kind, detail)
    assert "worktrees" in detail, detail


def test_main_checkout_is_classified_normal(ai_repo, tmp_path):
    """The other half of the same call: the main checkout must NOT be refused.

    Pin, not a new behaviour: `("normal", ...)` at HEAD is what the gate must
    keep returning once a refusal exists, or the fix would refuse every install.
    """
    linked(ai_repo, tmp_path)
    kind, detail = ai_common.checkout_layout(ai_repo)
    assert kind == "normal", (kind, detail)


def test_layout_without_a_git_repository_is_not_reported_normal(tmp_path):
    """Correction 3: rc 128 from `rev-parse` is 'undetermined', never 'clean'.

    The four named kinds give "cannot determine" one place to live; the caller
    treats it as an error state, which is what makes it not fail-open.
    """
    loose = tmp_path / "loose"
    loose.mkdir()
    kind, detail = ai_common.checkout_layout(loose)
    assert kind == "outside-repo", (kind, detail)
    assert "not determined" in detail or "repository" in detail, detail


def test_worktrees_lists_every_checkout_of_the_repository(ai_repo, tmp_path):
    """The reporting function the refusal message prints."""
    wt = linked(ai_repo, tmp_path)
    listed = {_norm(p) for p in ai_common.worktrees(ai_repo)}
    assert _norm(ai_repo) in listed, listed
    assert _norm(wt) in listed, listed


def test_a_worktree_that_cannot_be_answered_is_not_reported_as_none(tmp_path):
    """`worktrees()` returning [] must not read as 'no other worktree' (B7a/3).

    The bare list stays in the interface for callers that only print it; the
    pair is what a deciding caller uses.
    """
    loose = tmp_path / "loose"
    loose.mkdir()
    paths, err = ai_common.worktree_listing(loose)
    assert paths == [], paths
    assert err, "git refused to answer and nothing says so"


# --------------------------------------------------------------------------
# checkpoint.py --lock: the refusal, before a single byte is written.
# --------------------------------------------------------------------------

def test_lock_in_a_linked_worktree_is_refused(ai_repo, tmp_path):
    """D15: two worktrees each holding their own lock file is two writers."""
    wt = worktree_install(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    res = run_python(cp, ["--lock", "--agent", "codex"], cwd=wt)
    assert res.rc == 1, res.stdout
    assert "worktree" in res.stdout.lower(), res.stdout
    assert not (wt / ".ai" / "runtime" / "WRITER_LOCK.json").exists(), (
        "refused the layout and wrote the lock anyway")


def test_main_checkout_is_unaffected(ai_repo, cp):
    """The gate is for linked worktrees and bad layouts, not for every install.

    Pin: this command already exited 0 at HEAD, so it proves the refusal did not
    swallow the common case.
    """
    res = run_python(cp, ["--lock", "--agent", "codex"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert "Writer lock acquired by codex" in res.stdout, res.stdout


def test_force_over_a_linked_worktree_needs_a_reason(ai_repo, tmp_path):
    """`--force` remains the advisory escape hatch, and must name why."""
    wt = worktree_install(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    bare = run_python(cp, ["--lock", "--agent", "codex", "--force"], cwd=wt)
    assert bare.rc == 1, bare.stdout
    assert "--reason" in bare.stdout, bare.stdout
    forced = run_python(cp, ["--lock", "--agent", "codex", "--force",
                             "--reason", "split checkout; recorded in the handoff"],
                        cwd=wt)
    assert forced.rc == 0, forced.stdout
    record = lock_record(wt)
    assert record["agent"] == "codex", record
    assert record["reason"] == "split checkout; recorded in the handoff", record
    assert record["forced_layout"] == "linked-worktree", record


def test_lock_where_git_cannot_answer_is_refused(tmp_path):
    """An install outside any repository cannot honour a git-travelled lock."""
    root = tmp_path / "loose"
    root.mkdir()
    res = scaffold(root)
    assert res.rc == 0, res.stdout + res.stderr
    cp = root / ".ai" / "scripts" / "checkpoint.py"
    assert cp.is_file(), cp
    locked = run_python(cp, ["--lock", "--agent", "codex"], cwd=root)
    assert locked.rc == 1, locked.stdout
    assert "REFUSED" in locked.stdout, locked.stdout
    assert not (root / ".ai" / "runtime" / "WRITER_LOCK.json").exists()


def test_force_records_the_displaced_holder_and_bumps_the_epoch(ai_repo, cp):
    """Takeover must be visible in git history, not just on stderr.

    `epoch` is 1b's schema; starting to write it here is additive, and an
    existing test in tests/test_lock_state.py reads only `record["agent"]`.
    """
    write_lock(ai_repo, json.dumps({
        "agent": "codex", "reason": "T7", "epoch": 4,
        "acquired_at": "2026-09-21T10:00:00+10:00",
        "expires_at": "2099-01-01T10:00:00+10:00", "released_at": None}))
    res = run_python(cp, ["--lock", "--agent", "claude-code", "--force",
                          "--reason", "T12 takeover, recorded in the handoff"],
                     cwd=ai_repo)
    assert res.rc == 0, res.stdout
    record = lock_record(ai_repo)
    assert record["agent"] == "claude-code", record
    assert record["epoch"] == 5, record
    assert record["forced_over"] == {"agent": "codex", "epoch": 4,
                                    "acquired_at": "2026-09-21T10:00:00+10:00"}, record


# --------------------------------------------------------------------------
# The symlinked half. On this host the probe below fails, so these SKIP: that
# is a coverage hole for D15, not D15 coverage. (batch-B7a correction 2)
# --------------------------------------------------------------------------

def test_symlinked_state_dir_is_named_before_any_write(ai_repo, tmp_path):
    """`.ai/state` -> elsewhere: ROOT is unchanged, the payload is not in git."""
    require_symlink(tmp_path)
    real = tmp_path / "elsewhere"
    real.mkdir()
    (ai_repo / ".ai" / "state").rename(real / "state")
    (ai_repo / ".ai" / "state").symlink_to(real / "state", target_is_directory=True)
    kind, detail = ai_common.checkout_layout(ai_repo)
    assert kind == "symlinked", (kind, detail)
    assert "state" in detail, detail


def test_lock_with_a_symlinked_install_is_refused(ai_repo, tmp_path, cp):
    """The same shape end-to-end: the lock written is not the one pulled."""
    require_symlink(tmp_path)
    real = tmp_path / "elsewhere"
    real.mkdir()
    (ai_repo / ".ai" / "runtime").rename(real / "runtime")
    (ai_repo / ".ai" / "runtime").symlink_to(real / "runtime",
                                             target_is_directory=True)
    res = run_python(cp, ["--lock", "--agent", "codex"], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "symlink" in res.stdout.lower(), res.stdout
    assert not (real / "runtime" / "WRITER_LOCK.json").exists(), (
        "refused the layout and wrote the lock into the symlinked target anyway")
