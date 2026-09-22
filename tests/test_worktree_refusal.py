"""D15: one install root per checkout, and a relocated or linked worktree is refused.

`.ai/runtime/WRITER_LOCK.json` is deliberately git-TRACKED so the advisory
single-writer rule travels to another machine by `git pull`. Two linked git
worktrees on ONE machine break that rule with no git involved at all: each
worktree holds its own on-disk copy, so both print "Writer lock acquired" and
neither sees the other. A relocated `.ai` is the same defect one level up —
`resolve_roots()` follows links, so ROOT silently names a different tree and the
lock that gets written is not the file anyone pulls.

R2 finding B7a-1 is why this file grew a junction probe: `Path.is_symlink()` is
False for a Windows directory junction, and `mklink /J` needs NO privilege on
this host (measured: rc 0, `is_symlink` False, `is_dir` True). So the old
"cannot symlink here, therefore UNTESTED" disclosure was not a coverage gap, it
was a bypass — the exact shape D15 exists to refuse classified as `normal`. A
junction is detected by its REPARSE_POINT attribute, so the half that used to
skip now executes here, on every run, with no elevation.

Design law (spec §4): a degradation may only be a named WARN/refusal, never a
pass, and "cannot determine the layout" is never "normal" — which is also why an
invocation this process cannot describe comes back as undetermined rather than
clean. The lock stays ADVISORY — `--force --reason` remains the escape hatch;
nothing here enforces.

Two notes on how these tests are built, because both deviate from the brief on
purpose:

* `ai_repo` does NOT commit the install (`init_sync.py` never runs git), so a
  fresh worktree checkout holds no `.ai/`. The brief's `git add -A` fallback is
  banned by the dispatch instructions, so the install is created the supported
  way — `scaffold()` into the worktree — and the fact is asserted, so this file
  tells us the day the fixture starts committing.
* Every refusal here is asserted against `checkpoint.py --lock`, the entry point
  this lane owns. The `sync_verify.py` "install layout" check is the sibling
  lane's file, so `invocation_layout()` is exported and pinned here and left
  unwired.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from helpers import SCRIPTS, git, load_ai_common, load_module, run_python, scaffold, write_lock

# Loaded under a PRIVATE name for the reason tests/test_ai_common.py gives:
# registering it as `ai_common` would make an in-process load of an INSTALLED
# script resolve `from ai_common import ...` to this object instead of the file
# that ships. Kept registered so later pins can still find the module object.
ai_common = load_ai_common("_worktree_refusal_ai_common", keep=True)

# The words a refusal must use for each relocated mechanism, so a junction never
# prints as a symlink and a symlink never prints as a junction.
JUNCTION_WORD = "junction"


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


def reparse_point(path: Path) -> bool:
    """Host truth for a relocated directory, measured WITHOUT `is_symlink()`.

    This is the assertion the reviewer's probe forced: a junction answers False
    to `is_symlink()`, so a test that trusted that predicate would certify the
    bypass instead of the fix.
    """
    rp = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    try:
        attrs = path.stat(follow_symlinks=False).st_file_attributes
    except OSError:
        return False
    return bool(rp) and bool(attrs & rp)


def make_junction(link: Path, target: Path) -> None:
    """`mklink /J` — a directory junction, needs no privilege on this host.

    `link` and `target` are absolute paths under the caller's `tmp_path`, i.e.
    outside this checkout, so nothing here can point a link into the repository
    under test.
    """
    assert link.is_absolute() and target.is_absolute(), (link, target)
    res = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert res.returncode == 0 and reparse_point(link), (
        res.stdout.decode("utf-8", "replace"), str(link))


def drop_junction(link: Path) -> None:
    """Remove the link ALONE: `shutil.rmtree` would follow a junction and delete
    the target's contents, because `os.path.islink()` is False for one."""
    if reparse_point(link) or link.is_symlink():
        os.rmdir(str(link))


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
                    "hold, not a code result) — the symlink-spelled case is "
                    "covered by the boundary pin below and end-to-end by the "
                    "junction tests, so no relocated path goes unexecuted.")


def junctions_usable(tmp_path) -> bool:
    probe = tmp_path / "jprobe"
    probe.mkdir(parents=True)
    try:
        make_junction(probe / "link", probe)
    except (AssertionError, OSError) as exc:
        print(f"\nD15 JUNCTION PROBE FAILED: {exc}")
        return False
    return True


def require_junction(tmp_path) -> None:
    if not junctions_usable(tmp_path / "jrequire"):
        pytest.skip("mklink /J unavailable on this host — the relocated-payload "
                    "path is then covered only by the boundary pin below.")


def lock_record(root: Path) -> dict:
    path = root / ".ai" / "runtime" / "WRITER_LOCK.json"
    assert path.is_file(), f"no lock record written at {path}"
    return json.loads(path.read_text("utf-8-sig"))


# --------------------------------------------------------------------------
# The capability floor. REGRESSION GUARD, not a fix pin: B7a disclosed the
# symlink hole by skipping; the only thing worse than a disclosed hole is one
# that quietly stops being disclosed because both probes went away. If neither
# mechanism can be built, this file has NO executed relocation coverage, and it
# must say so in red.
# --------------------------------------------------------------------------

def test_at_least_one_relocation_mechanism_is_buildable_here(tmp_path):
    can_symlink = symlinks_usable(tmp_path / "p1")
    can_junction = junctions_usable(tmp_path / "p2")
    assert can_symlink or can_junction, (
        "neither os.symlink nor mklink /J works on this host, so D15's relocated "
        "payload has zero executed coverage; the skips below are no longer a "
        "named hole, they are a hole")
    if not can_symlink:
        assert can_junction, (
            "os.symlink is privilege-gated on this host and mklink /J did not "
            "replace it, so the junction tests are skipping too")


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


def test_an_install_in_a_subdirectory_of_a_repo_is_not_normal(ai_repo, tmp_path):
    """B7a-2: "normal" used to mean "somewhere below SOME work tree".

    An install in `pkg/.ai` of an unrelated repository prints a lock hint whose
    "travels by git pull" claim is about the OUTER repo — the one-install-root
    defect, unnamed. The fifth kind names it; a git that cannot answer stays in
    "outside-repo" (ruling: failure is never the new kind).
    """
    nested = ai_repo / "pkg" / ".ai"
    nested.mkdir(parents=True)
    kind, detail = ai_common.checkout_layout(ai_repo / "pkg")
    assert kind == "not-repository-root", (kind, detail)
    assert "toplevel" in detail or str(ai_repo) in detail, detail


def test_layout_without_a_git_repository_is_not_reported_normal(tmp_path,
                                                                monkeypatch):
    """Correction 3: rc 128 from `rev-parse` is 'undetermined', never 'clean'.

    The named kinds give "cannot determine" one place to live; the caller treats
    it as an error state, which is what makes it not fail-open.

    GIT_CEILING_DIRECTORIES is the host guard B7a-8 asked for: without it this
    test asserts a property of the temp directory (nothing above it is a repo),
    and on a host whose temp lives inside a working copy it goes red for a
    reason that has nothing to do with the classifier.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
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


def test_a_worktree_that_cannot_be_answered_is_not_reported_as_none(tmp_path,
                                                                    monkeypatch):
    """`worktrees()` returning [] must not read as 'no other worktree' (B7a/3).

    The bare list stays in the interface for callers that only print it; the
    pair is what a deciding caller uses. Same ceiling guard as above: "no
    worktree" here depends on git not finding a repo above the temp dir.
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    loose = tmp_path / "loose"
    loose.mkdir()
    paths, err = ai_common.worktree_listing(loose)
    assert paths == [], paths
    assert err, "git refused to answer and nothing says so"


# --------------------------------------------------------------------------
# B7a-1: the relocated payload, built with a junction so it EXECUTES here.
# --------------------------------------------------------------------------

def test_a_junction_in_the_install_is_not_classified_normal(ai_repo, tmp_path):
    """`mklink /J .ai\\state` is relocated state that `is_symlink()` cannot see.

    Red at HEAD: `checkout_layout` returned `("normal", ...)`, i.e. the bypass
    named in r2-review-report B7a-1.
    """
    require_junction(tmp_path)
    ai = ai_repo / ".ai"
    state = ai / "state"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    moved = elsewhere / "state"
    state.rename(moved)
    make_junction(state, moved)
    try:
        assert not state.is_symlink(), (
            "this host now reports a junction as a symlink — the reparse-point "
            "branch is untested by this case, adjust the probe rather than relax "
            "the assertion")
        kind, detail = ai_common.checkout_layout(ai_repo)
        assert kind == "symlinked", (kind, detail)
        assert JUNCTION_WORD in detail, detail
        assert "state" in detail, detail
    finally:
        drop_junction(state)
        moved.rename(state)


def test_the_relocated_target_is_named_not_invented(ai_repo, tmp_path):
    """The detail must carry the destination: 'somewhere else' is not auditable.

    A junction's `readlink()` answer comes back in the extended Win32 device
    form, so the assertion is that that prefix does not survive into the
    printed detail: handing the user a path that is not a path is its own bug.
    """
    require_junction(tmp_path)
    runtime = ai_repo / ".ai" / "runtime"
    elsewhere = tmp_path / "payload"
    elsewhere.mkdir()
    moved = elsewhere / "runtime"
    runtime.rename(moved)
    make_junction(runtime, moved)
    try:
        _kind, detail = ai_common.checkout_layout(ai_repo)
        assert "-> " in detail, detail
        assert "runtime" in detail, detail
        assert "?" not in detail, detail
        assert moved.name in detail, detail
    finally:
        drop_junction(runtime)
        moved.rename(runtime)


# --------------------------------------------------------------------------
# invocation_layout: the second direction, exported for the verifier lane.
# --------------------------------------------------------------------------

def test_invocation_layout_sees_a_junctioned_install_the_root_cannot(ai_repo, cp,
                                                                     tmp_path):
    """B7a-1 + B7a-4 end-to-end: ROOT resolves THROUGH the link, so the only
    witness left is the unresolved path this process was invoked by.

    Without the witness the install reads as `outside-repo` (not clean, but the
    wrong truth: the payload is relocated, and that is what the user has to
    fix). Pinned at `checkpoint.install_layout`, the entry point that writes.
    """
    require_junction(tmp_path)
    ai = ai_repo / ".ai"
    elsewhere = tmp_path / "relocated"
    elsewhere.mkdir()
    moved = elsewhere / ".ai"
    ai.rename(moved)
    make_junction(ai, moved)
    try:
        res = run_python(cp, ["--lock", "--agent", "codex"], cwd=ai_repo)
        assert res.rc == 1, res.stdout
        assert JUNCTION_WORD in res.stdout.lower(), res.stdout
        assert "REFUSED" in res.stdout, res.stdout
        for tree in (ai_repo, elsewhere):
            assert not (tree / ".ai" / "runtime" / "WRITER_LOCK.json").exists(), (
                f"refused the layout and wrote a lock into {tree} anyway")
    finally:
        drop_junction(ai)
        moved.rename(ai)


def test_invocation_layout_is_exported_and_names_what_it_cannot_describe(tmp_path,
                                                                         ai_repo,
                                                                         cp):
    """B7a-6: the helper moves to `ai_common` so the verifier can use the SAME
    answer, and an invocation whose shape does not match `<root>/.ai/scripts/`
    returns undetermined rather than `normal` (B7a-4's law).

    REGRESSION GUARD for the next lane: it pins the signature
    `invocation_layout(root, script_file)` and the normal-install answer, so a
    refactor that renames or re-orders the parameters goes red here instead of
    at the verifier's call site.
    """
    assert hasattr(ai_common, "invocation_layout"), (
        "ai_common must export invocation_layout for the sync_verify consumer")
    stranger = tmp_path / "tools" / "checkpoint.py"
    stranger.parent.mkdir(parents=True)
    stranger.write_text("# not an install\n", encoding="utf-8")
    kind, detail = ai_common.invocation_layout(ai_repo, str(stranger))
    assert kind == "outside-repo", (kind, detail)
    assert "not determined" in detail, detail
    kind, detail = ai_common.invocation_layout(ai_repo, str(cp))
    assert kind == "normal", (kind, detail)


# --------------------------------------------------------------------------
# checkpoint.py --lock: the refusal, before a single byte is written.
# --------------------------------------------------------------------------

def test_lock_in_a_linked_worktree_is_refused(ai_repo, tmp_path):
    """D15: two worktrees each holding their own lock file is two writers."""
    wt = worktree_install(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    res = run_python(cp, ["--lock", "--agent", "codex"], cwd=wt)
    assert res.rc == 1, res.stdout
    # B7a-7: `"worktree" in stdout` also matched the outside-repo refusal, which
    # prints "worktrees of this repository: ..." while classifying the layout as
    # UNDETERMINED — the test stayed green as the classifier degraded.
    assert "REFUSED: this checkout is a linked git worktree" in res.stdout, res.stdout
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
    """`--force` remains the advisory escape hatch, and must name why.

    rc 2, not 1: R2 adjudication 4 overturns C1's choice. A missing required
    companion argument is a USAGE error in this CLI, which exits 2 for
    `--lock requires --agent`, for `--unlock requires --agent`, and via argparse;
    rc 1 is reserved for refusals reached after a verdict was possible (LOCK
    CONFLICT, LAYOUT REFUSED, CHECKPOINT REFUSED).
    """
    wt = worktree_install(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    bare = run_python(cp, ["--lock", "--agent", "codex", "--force"], cwd=wt)
    assert bare.rc == 2, bare.stdout
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
    """An install outside any repository cannot honour a git-travelled lock.

    The ceiling is passed to the CHILD (B7a-8): without it this asserts that
    nothing above the temp directory is a repository, which is a property of the
    host, not of the code.
    """
    root = tmp_path / "loose"
    root.mkdir()
    res = scaffold(root)
    assert res.rc == 0, res.stdout + res.stderr
    cp = root / ".ai" / "scripts" / "checkpoint.py"
    assert cp.is_file(), cp
    locked = run_python(cp, ["--lock", "--agent", "codex"], cwd=root,
                        env={"GIT_CEILING_DIRECTORIES": str(tmp_path)})
    assert locked.rc == 1, locked.stdout
    assert "REFUSED" in locked.stdout, locked.stdout
    assert not (root / ".ai" / "runtime" / "WRITER_LOCK.json").exists()


def test_force_records_the_displaced_holder_and_bumps_the_epoch(ai_repo, cp):
    """Takeover must be visible in git history, not just on stderr.

    `epoch` is 1b's schema; starting to write it here is additive, and an
    existing test in tests/test_lock_state.py reads only `record["agent"]`.

    Three acquisitions in one uncommitted session, because r2 findings C1-4 and
    B7a-3 are both about the SECOND and THIRD writes:

    * a takeover the record does not carry is a takeover nobody saw, so the
      chain survives as `prior_forced` (C1-4);
    * an `epoch` that cannot be read is not `epoch: 1` — the gap gets a WARN and
      a named reason instead of a confident small number (B7a-3, spec §4);
    * a hold that EXPIRED mid-task is the most common split and the least
      audited one, so it is now recorded without `--force` (C1-5).
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
    assert "prior_forced" not in record, record

    # Second takeover: the displaced record's own epoch is not a number, and it
    # already carries one takeover that nobody may lose.
    write_lock(ai_repo, json.dumps({
        "agent": "kimi", "reason": "T12", "epoch": "abc",
        "acquired_at": "2026-09-21T12:00:00+10:00",
        "expires_at": "2099-01-01T10:00:00+10:00", "released_at": None,
        "forced_over": {"agent": "claude-code", "epoch": 5,
                        "acquired_at": "2026-09-21T11:00:00+10:00"}}))
    second = run_python(cp, ["--lock", "--agent", "qoder", "--force",
                             "--reason", "T13 second takeover"], cwd=ai_repo)
    assert second.rc == 0, second.stdout
    assert "epoch is not recorded" in second.stdout, second.stdout
    assert "abc" in second.stdout, second.stdout
    again = lock_record(ai_repo)
    assert "epoch" not in again, again
    assert "abc" in again["epoch_unreadable"], again
    assert again["forced_over"] == {"agent": "kimi", "epoch": "abc",
                                   "acquired_at": "2026-09-21T12:00:00+10:00"}, again
    assert again["prior_forced"] == [{"agent": "claude-code", "epoch": 5,
                                      "acquired_at": "2026-09-21T11:00:00+10:00"}], again

    # Third acquisition, no --force at all: somebody's TTL ran out mid-task.
    write_lock(ai_repo, json.dumps({
        "agent": "deepseek", "reason": "T9", "epoch": 9,
        "acquired_at": "2026-09-20T10:00:00+10:00",
        "expires_at": "2026-09-20T14:00:00+10:00", "released_at": None}))
    expired = run_python(cp, ["--lock", "--agent", "qoder"], cwd=ai_repo)
    assert expired.rc == 0, expired.stdout
    third = lock_record(ai_repo)
    assert third["agent"] == "qoder", third
    assert third["over_expired_hold"] == {
        "agent": "deepseek",
        "acquired_at": "2026-09-20T10:00:00+10:00"}, third
    assert "forced_over" not in third, third


def test_the_lock_is_not_written_twice_over_a_record_that_changed(ai_repo, cp,
                                                                  monkeypatch,
                                                                  capsys):
    """C1-3: `cmd_unlock` got compare-and-write in B6/8; `cmd_lock` did not.

    `cmd_lock` read the tracked record a third time and replaced it with no byte
    comparison, so a merge that landed mid-command was destroyed while
    `forced_over` and `epoch` described bytes nobody had validated. Same bounded
    fix, same advisory shape: an ABORT is a re-run, not enforcement.
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")
    lock = ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json"
    mine = json.dumps({"agent": "codex", "reason": "T7", "epoch": 2,
                       "acquired_at": "2026-09-21T10:00:00+10:00",
                       "expires_at": "2099-01-01T10:00:00+10:00",
                       "released_at": None}).encode()
    theirs = json.dumps({"agent": "kimi", "reason": "T8", "epoch": 3,
                         "acquired_at": "2026-09-21T11:00:00+10:00",
                         "expires_at": "2099-01-01T10:00:00+10:00",
                         "released_at": None}).encode()
    real_read = Path.read_bytes
    reads = []

    def merge_lands(self):
        if Path(str(self)) != Path(str(lock)):
            return real_read(self)
        reads.append(self.name)
        if len(reads) > 2:
            lock.write_bytes(theirs)
            return theirs
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", merge_lands)
    args = _LockArgs(agent="claude-code")
    with pytest.raises(SystemExit) as exc:
        mod.cmd_lock(args)
    out = capsys.readouterr().out
    assert exc.value.code, "cmd_lock exited 0 over a record it no longer held"
    assert "LOCK ABORTED" in out, out
    assert real_read(lock) == theirs, (
        "the acquisition replaced the record that landed mid-command")


def load(cp_path):
    """Import the `checkpoint.py` that was copied INTO this fixture repo."""
    return load_module("_worktree_refusal_checkpoint", cp_path, keep=True)


class _LockArgs:
    """The namespace `cmd_lock` reads, built by hand like tests/test_lock_state.py."""

    def __init__(self, agent):
        self.agent = agent
        self.ttl = 100
        self.force = True
        self.discard_lock = False
        self.reason = "T13 takeover while a merge landed"



# --------------------------------------------------------------------------
# The symlinked spelling of the same defect. On this host `os.symlink` is
# privilege-gated, so these two SKIP — and they no longer stand alone: the
# junction tests above execute the same relocated-payload code paths end to
# end, and `test_at_least_one_relocation_mechanism_is_buildable_here` fails if
# both mechanisms ever go missing. (r2 B7a-9)
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


def test_the_relocated_predicate_is_pinned_at_its_boundary(ai_repo, monkeypatch):
    """B7a-9: the `is_symlink()` branch executes WITHOUT a symlink.

    Monkeypatched at the function boundary against the shipped classifier — the
    same portable trick tests/test_lock_state.py uses for F1 — so the link half
    of the predicate is not left to the two tests that skip on this host.
    """
    target = ai_repo / ".ai" / "handoff"
    real_is_symlink = Path.is_symlink

    def lies_as_symlink(self):
        return True if Path(str(self)) == Path(str(target)) else real_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", lies_as_symlink)
    kind, detail = ai_common.checkout_layout(ai_repo)
    assert kind == "symlinked", (kind, detail)
    assert "handoff" in detail, detail
