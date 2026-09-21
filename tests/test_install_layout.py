"""Lane S1, handed over by `batch-B7a-report.md` §2: the verifier itself must
refuse a tree git cannot describe.

B7a owns `checkpoint.py` (where the lock refuses) and was forbidden to touch
`sync_verify.py`, so it handed the exact record over. Two of its corrections are
load-bearing and pinned here:

  * gate on `kind != "normal"`, not `kind == "symlinked"` — a
    `linked-worktree` or `outside-repo` run that falls through to the config
    checks can print PASS about a tree that is not the one the other writer
    sees, which is the fail-open spec 4 ends;
  * `return _summarise()`, not `return 1` — the run still prints its honest
    `== 0/1 checks passed ==` verdict line instead of looking like a crash, and
    the tally says out loud that nothing else was reached.

The limit this file used to state instead of testing — "checkout_layout(ROOT)
structurally cannot see an `.ai` that is *itself* the symlink this script was
invoked through, and no test here claims the symlinked half is covered" — is
closed by Task 7 step 1: the verifier now asks `ai_common.invocation_layout`
(r2 finding B7a-6), the same witness `checkpoint.py --lock` asks, so the
invoked-through case is named rather than resolved past. `test_the_verifier_sees
an_ai_it_was_invoked_through` below is that coverage; the residual limit it
names in the evidence line is an `.ai` reached only through an already-resolved
path, which no witness inside the process can recover.
"""
from __future__ import annotations

from pathlib import Path

from helpers import git, run_python


def _worktree_of(ai_repo: Path, tmp_path: Path) -> Path:
    """Commit the install, then add a linked worktree that carries the same bytes.

    Committing is what makes the case real: a linked worktree has its own
    `.ai/runtime/WRITER_LOCK.json` on disk, which is exactly the single-writer
    leak the record names.
    """
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "install committed for the worktree case")
    wt = tmp_path / "linked"
    git(ai_repo, "worktree", "add", "-q", "-b", "s1-layout-case", str(wt))
    return wt


def test_a_linked_worktree_is_named_and_the_run_stops_there(ai_repo, sv, tmp_path):
    wt = _worktree_of(ai_repo, tmp_path)
    res = run_python(wt / ".ai" / "scripts" / "sync_verify.py", cwd=wt)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] install layout: linked-worktree")
               for ln in res.lines), res.lines
    line = [ln for ln in res.lines if ln.startswith("[FAIL] install layout")][0]
    assert "/worktrees/" in line.replace("\\", "/"), line
    assert "common" in line, line
    # the honest summary the correction asked for, and nothing behind it
    assert "== 0/1 checks passed ==" in res.lines, res.lines
    assert "FAILED: install layout" in res.lines, res.lines
    assert not any(ln.startswith("[PASS] config readable") for ln in res.lines), \
        res.lines
    assert not any(ln.startswith("[PASS] required ") for ln in res.lines), res.lines


def test_the_record_names_the_coverage_it_does_not_have(ai_repo, sv, tmp_path):
    wt = _worktree_of(ai_repo, tmp_path)
    res = run_python(wt / ".ai" / "scripts" / "sync_verify.py", cwd=wt)
    line = [ln for ln in res.lines if ln.startswith("[FAIL] install layout")][0]
    assert "invoked THROUGH" in line or "invoked through" in line, line
    assert "resolve_roots" in line, line


def test_a_plain_install_is_not_reported_as_a_bad_layout(ai_repo, sv):
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert not any(ln.startswith("[FAIL] install layout") for ln in res.lines), \
        res.lines


def test_a_repository_git_cannot_place_is_not_reported_normal(tmp_path):
    """`outside-repo` covers "git would not answer" as well as "not a
    repository", and spec 4 forbids reading "cannot tell" as "clean". The
    install bytes are copied by hand here, because the point of the case is a
    tree git cannot locate at all."""
    from helpers import SCRIPTS, make_repo
    loose = make_repo(tmp_path)
    (loose / ".ai" / "scripts").mkdir(parents=True)
    for name in ("ai_common.py", "sync_verify.py"):
        (loose / ".ai" / "scripts" / name).write_text(
            (SCRIPTS / name).read_text("utf-8"), encoding="utf-8")
    (loose / ".ai" / "sync_config.json").write_text(
        (SCRIPTS / ".." / "templates" / "sync_config.json").read_text("utf-8"),
        encoding="utf-8")
    # detach the tree from its repository: git can no longer say where the work
    # tree is, which is the ERROR half of `outside-repo`.
    (loose / ".git").rename(tmp_path / "gone-git")
    res = run_python(loose / ".ai" / "scripts" / "sync_verify.py", cwd=loose)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] install layout: outside-repo")
               for ln in res.lines), res.lines
    assert "layout not determined" in " ".join(res.lines), res.lines


def test_the_verifier_sees_an_ai_it_was_invoked_through(ai_repo, tmp_path):
    """r2 finding B7a-6, wired: the verifier used to answer with
    `checkout_layout(ROOT)`, and `resolve_roots()` had already resolved PAST the
    link that got us here, so ROOT named the relocation target's parent — a tree
    that looked ordinary from inside. `invocation_layout` keeps the unresolved
    invocation path as the witness, which is the one thing that saw the link.

    Red before the wiring: the run reported `outside-repo`, i.e. the right
    severity about the wrong fact — the payload is relocated, and that is what
    the operator has to fix.
    """
    from test_worktree_refusal import (JUNCTION_WORD, drop_junction,
                                       make_junction, require_junction)
    require_junction(tmp_path)
    ai = ai_repo / ".ai"
    elsewhere = tmp_path / "relocated-ai"
    elsewhere.mkdir()
    moved = elsewhere / ".ai"
    ai.rename(moved)
    make_junction(ai, moved)
    try:
        res = run_python(ai / "scripts" / "sync_verify.py", cwd=ai_repo,
                         env={"GIT_CEILING_DIRECTORIES": str(tmp_path)})
        assert res.rc == 1, res.stdout + res.stderr
        layout = [ln for ln in res.lines if ln.startswith("[FAIL] install layout")]
        assert layout, res.lines
        line = layout[0]
        assert line.startswith("[FAIL] install layout: symlinked"), line
        assert JUNCTION_WORD in line.lower(), line
        assert "relocated" in line, line
        # The destination has to be IN the text: "somewhere else" is not
        # auditable. Comparing in the posix form because the witness prints the
        # junction target as git/Win32 reports it, with forward slashes.
        flat = lambda s: str(s).replace("\\", "/").lower()
        assert flat(moved) in flat(line), line
        # Nothing behind the gate ran, and the tally says so. The passed count is
        # zero whichever pre-flight line shares the run: the ceiling guard makes
        # ROOT itself a tree git cannot place, so `git repository` is named too.
        summary = [ln for ln in res.lines if "checks passed" in ln]
        assert len(summary) == 1, res.lines
        assert summary[0].startswith("== 0/"), summary[0]
        assert any(ln.startswith("FAILED:") and "install layout" in ln
                   for ln in res.lines), res.lines
        assert not any(ln.startswith("[PASS] required ") for ln in res.lines), \
            res.lines
    finally:
        drop_junction(ai)
        moved.rename(ai)
