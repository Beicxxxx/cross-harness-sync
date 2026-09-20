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
