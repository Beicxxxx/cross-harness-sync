"""Task 1: shared primitives (`ai_common.py`) + defensive root resolution (D19).

D19 in one line: both scripts derived the project root as
`Path(__file__).resolve().parent.parent`, so a copy of `sync_verify.py` parked in
`scripts/` or `tools/` silently audited that directory's parent and reported a
confident, entirely wrong verdict. The fix is to refuse a script that does not
live under `.ai/scripts/`, and to give both scripts one shared copy of the
subprocess/encoding plumbing instead of two (D5/D13's home).

These tests therefore pin three things: the primitives' contract, the refusal
itself, and — because the refactor moves every module-level path global behind
`main()` — that each of the seven `checkpoint.py` entry points still behaves
through the CLI and still fails loudly when it is called unwired.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from helpers import SCRIPTS, run_python

spec = importlib.util.spec_from_file_location("ai_common", SCRIPTS / "ai_common.py")
ai_common = importlib.util.module_from_spec(spec)
sys.modules["ai_common"] = ai_common
spec.loader.exec_module(ai_common)


def _load(path: Path, name: str):
    """Import a script as a fresh module object.

    A fresh name per call matters: the un-wired-vs-wired tests below must not
    inherit module globals from another test that already ran `main()`.
    """
    module_spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = mod
    module_spec.loader.exec_module(mod)
    return mod


def _stray(ai_repo: Path, name: str) -> Path:
    """Copy a shipped script into `<repo>/tools/`, with its `ai_common.py`.

    The neighbour copy is what makes this a D19 test rather than an
    import-error test: without `ai_common.py` alongside it, the script would die
    in the `except ImportError` branch (also rc 2, also mentioning `.ai`) and the
    root-derivation refusal would never be reached.
    """
    tools = ai_repo / "tools"
    tools.mkdir(exist_ok=True)
    for src in (SCRIPTS / name, SCRIPTS / "ai_common.py"):
        (tools / src.name).write_bytes(src.read_bytes())
    return tools / name


# --------------------------------------------------------------------------
# resolve_roots: the D19 refusal


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


def test_verify_refuses_a_copy_outside_dot_ai(ai_repo):
    """D19: a script copied outside .ai/scripts/ used to silently audit the
    parent directory instead of the repo."""
    stray = _stray(ai_repo, "sync_verify.py")
    res = run_python(stray, cwd=ai_repo)
    assert res.rc == 2, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert "[FAIL] install layout" in out, out
    # The refusal must name the directory it resolved to — proof we reached
    # `resolve_roots` and not the missing-`ai_common` branch.
    assert str(ai_repo) in out, out


def test_checkpoint_refuses_a_copy_outside_dot_ai(ai_repo):
    stray = _stray(ai_repo, "checkpoint.py")
    res = run_python(stray, ["--status"], cwd=ai_repo)
    assert res.rc == 2, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert "[FAIL] install layout" in out, out
    assert str(ai_repo) in out, out


def test_a_real_install_still_verifies_green_after_the_refactor(ai_repo, sv):
    """The D19 guard must not reject the layout it exists to bless."""
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert f"== sync_verify: project root {ai_repo} ==" in res.stdout, res.stdout


# --------------------------------------------------------------------------
# ai_common.py must be installed, and its absence must be a hard failure


def test_scaffold_installs_ai_common_next_to_the_scripts(ai_repo):
    installed = ai_repo / ".ai" / "scripts" / "ai_common.py"
    assert installed.exists(), installed
    assert "def resolve_roots" in installed.read_text(encoding="utf-8"), installed
    res = run_python(SCRIPTS / "init_sync.py", [str(ai_repo)], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any("ai_common.py" in ln for ln in res.lines), res.lines


@pytest.mark.parametrize("script", ["checkpoint.py", "sync_verify.py"])
def test_missing_ai_common_is_a_hard_failure_not_an_inline_fallback(ai_repo, script):
    """No second copy of the plumbing may exist, so a missing module must speak.

    The paired negative assertion is the point: an inline fallback would print a
    full report (header + summary) and exit 0 or 1 instead of naming the layout
    problem.
    """
    (ai_repo / ".ai" / "scripts" / "ai_common.py").unlink()
    res = run_python(ai_repo / ".ai" / "scripts" / script, cwd=ai_repo)
    out = res.stdout + res.stderr
    assert res.rc == 2, out
    assert "ai_common.py is missing from .ai/scripts/" in out, out
    assert "checks passed" not in out, out


# --------------------------------------------------------------------------
# subprocess plumbing: bytes in, never an exception out


def test_run_git_never_raises_on_timeout(tmp_path):
    res = ai_common.run_git(tmp_path, ["config", "--get", "no.such.key"], timeout=60)
    assert isinstance(res.rc, int)
    assert res.timed_out is False


def test_run_git_turns_a_timeout_into_a_result(monkeypatch, tmp_path):
    """The `TimeoutExpired` branch, reached without waiting for a hang.

    `rc == 0` must never be readable as success by a caller, so the timed-out
    result carries a non-zero rc as well as the flag.
    """
    def fake_run(*args, **kwargs):
        raise ai_common.subprocess.TimeoutExpired(
            ["git", "status"], 1, output=b"partial", stderr=b"boom")

    monkeypatch.setattr(ai_common.subprocess, "run", fake_run)
    res = ai_common.run_git(tmp_path, ["status"], timeout=1)
    assert res.timed_out is True
    assert res.rc == -1
    assert res.ok is False
    assert res.out() == "partial"
    assert res.err() == "boom"


def test_run_git_turns_a_missing_executable_into_a_result(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise OSError(2, "The system cannot find the file specified")

    monkeypatch.setattr(ai_common.subprocess, "run", fake_run)
    res = ai_common.run_git(tmp_path, ["status"], timeout=1)
    assert res.rc == -1
    assert res.ok is False
    assert "cannot find the file specified" in res.err(), res.err()


def test_a_zero_return_code_that_could_not_be_read_is_never_ok():
    """D5's fail-open law, pinned structurally."""
    assert ai_common.GitResult(0, b"", b"", True).ok is False
    assert ai_common.GitResult(0, b"", b"", False).ok is True
    assert ai_common.decode(None) == ""
    # An undecodable byte survives as a lone surrogate instead of raising.
    assert ai_common.decode(b"/\xff") == "/\udcff"


def test_is_git_repo_answers_for_a_real_repo_and_a_plain_dir(ai_repo, tmp_path,
                                                            monkeypatch):
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_NAMESPACE",
                "GIT_QUARANTINE_PATH"):
        monkeypatch.delenv(key, raising=False)
    assert ai_common.is_git_repo(ai_repo) is True
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    assert ai_common.is_git_repo(plain) is False


# --------------------------------------------------------------------------
# checkpoint.py: its path globals now live behind main(), so prove both halves


def test_checkpoint_commands_refuse_to_run_before_paths_are_wired(ai_repo, cp):
    mod = _load(cp, "cp_unwired")
    assert mod.AI_DIR is None, mod.AI_DIR
    with pytest.raises(RuntimeError) as exc:
        mod.cmd_status(argparse.Namespace())
    assert "not initialised" in str(exc.value)


@pytest.mark.parametrize("cmd", ["cmd_checkpoint", "cmd_prime", "cmd_validate",
                                 "cmd_handoff", "cmd_unlock", "cmd_lock"])
def test_every_command_carries_the_same_guard(ai_repo, cp, cmd):
    mod = _load(cp, f"cp_unwired_{cmd}")
    with pytest.raises(RuntimeError):
        getattr(mod, cmd)(argparse.Namespace(agent=None, ttl=1, reason=None,
                                            force=False, task=None))


def test_wiring_the_paths_makes_the_same_command_run(ai_repo, cp, capsys):
    """The positive half of the guard test: wired -> real output, not silence."""
    mod = _load(cp, "cp_wired")
    mod._set_paths(ai_repo / ".ai")
    assert mod.LOCK_PATH == ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json"
    mod.cmd_status(argparse.Namespace())
    printed = capsys.readouterr().out
    assert "State files:" in printed, printed
    assert "[OK ] CURRENT.md" in printed, printed


# --------------------------------------------------------------------------
# the seven-entry-point sweep (the refactor's blast radius)


def test_status_sweep(ai_repo, cp):
    res = run_python(cp, ["--status"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert "Writer Lock      : none" in res.stdout, res.stdout
    assert "[OK ] CURRENT.md" in res.stdout, res.stdout
    assert "LATEST.md" in res.stdout, res.stdout


def test_prime_sweep(ai_repo, cp):
    res = run_python(cp, ["--prime"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert "== SESSION PRIME (cross-harness-sync v2.0.0) ==" in res.stdout, res.stdout
    assert "READ NOW (L0, in order, nothing else at startup):" in res.stdout, res.stdout


def test_lock_then_unlock_sweep(ai_repo, cp):
    locked = run_python(cp, ["--lock", "--agent", "sweep", "--reason", "T1",
                             "--ttl", "600"], cwd=ai_repo)
    assert locked.rc == 0, locked.stdout + locked.stderr
    assert "Writer lock acquired by sweep until" in locked.stdout, locked.stdout
    record = json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                        .read_text(encoding="utf-8"))
    assert record["agent"] == "sweep", record
    assert record["reason"] == "T1", record

    status = run_python(cp, ["--status"], cwd=ai_repo)
    assert "Writer Lock      : HELD by sweep until" in status.stdout, status.stdout

    unlocked = run_python(cp, ["--unlock", "--agent", "sweep"], cwd=ai_repo)
    assert unlocked.rc == 0, unlocked.stdout + unlocked.stderr
    assert "Writer lock released at" in unlocked.stdout, unlocked.stdout
    released = json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                          .read_text(encoding="utf-8"))
    assert released["released_at"], released


def test_handoff_sweep(ai_repo, cp):
    res = run_python(cp, ["--handoff", "--agent", "sweep"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert "Archived previous handoff ->" in res.stdout, res.stdout
    assert "Handoff prepared at" in res.stdout, res.stdout
    assert list((ai_repo / ".ai" / "handoff" / "archive").glob("*-HANDOFF.md"))
    status = json.loads((ai_repo / ".ai" / "runtime" / "STATUS.json")
                        .read_text(encoding="utf-8"))
    assert status["status"] == "handed-off", status


def test_validate_sweep(ai_repo, cp):
    res = run_python(cp, ["--validate"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    # `cmd_validate` prints `path.relative_to(AI_DIR)`, whose separator is the
    # host's, so match on the file names rather than a literal `state/` prefix.
    ok_lines = [ln for ln in res.lines if ln.strip().startswith("OK:")]
    for name in ("CURRENT.md", "TASK.md", "BLOCKERS.md", "DECISIONS.md",
                 "DECISIONS_INDEX.md", "LATEST.md", "VERSION"):
        assert any(name in ln for ln in ok_lines), res.lines
    assert "All state files present and non-empty." in res.stdout, res.stdout


def test_bare_checkpoint_sweep(ai_repo, cp):
    first = run_python(cp, ["--agent", "sweep", "--task", "T1"], cwd=ai_repo)
    assert first.rc == 0, first.stdout + first.stderr
    assert "Checkpoint #1 at" in first.stdout, first.stdout
    second = run_python(cp, cwd=ai_repo)
    assert "Checkpoint #2 at" in second.stdout, second.stdout
    status = json.loads((ai_repo / ".ai" / "runtime" / "STATUS.json")
                        .read_text(encoding="utf-8"))
    assert status["checkpoint_count"] == 2, status
    assert status["active_agent"] == "sweep", status
