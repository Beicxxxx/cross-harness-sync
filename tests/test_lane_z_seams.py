"""Lane Z/Z2: the seven seams the whole-branch adversarial review reproduced.

Every script here is invoked as the copy that is INSTALLED in the fixture tree
(`.ai/scripts/…`), never as `scripts/…` in this checkout: `install_layout()`
refuses a `sync_verify.py` that does not live under `.ai/scripts/`, so running
the source copy asks a different question than "what does an installed tree
say?". `scripts/init_sync.py` is the exception because the installer is
deliberately not installed (`SCRIPT_MAP` ships three scripts).

Provenance, measured rather than claimed: this file run against base HEAD
`e8e78c0` (that tree's own scripts, installed by that tree's `init_sync.py`)
gives **13 failed, 3 passed**. The 3 passes are exactly the tests whose docstring
says CONTROL — they guard the relaxation side of a fix (a healthy install must
stay green), were already green at base, and are regression pins, not
reproductions. Everything else here is RED-AT-BASE, including
`test_f7_stamp_and_installed_scripts_agree`, whose tree total was green at base
but whose evidence wording is new.

  F1  `decisions_file` and `budgets` KEYS accepted repo-escaping paths, so one
      config line measured a file outside the checkout and booked a PASS while
      the repo's real 500-entry decision log went uncapped.
  F2  `--unlock` was the one lock-touching command with no D15 layout gate, so a
      linked worktree forged a release the other machine would pull as truth.
  F3  `--no-agents-block` skipped the cap arithmetic, so `--clobber` restored cap
      65 under a 66-line AGENTS.md and promised "no FAILED line" at rc 0.
  F4  caps were shape-checked, never magnitude-checked: six `999999999`s
      un-measured the whole budget layer and printed six PASSes.
  F5  `record()` appended before it printed, so an unprintable PASS was still
      arithmetic: 18 printed `[PASS]` lines against `== 19/21 ==`.
  F6  an unusable config exited 1 while SKILL.md's exit-code table says rc 2
      means "no verdict", so a run that verified nothing read as a verdict.
  F7  `protocol version readable` asked only whether the stamp parsed, so
      `99.99.99` printed PASS in a tree every later `--scripts-only` refuses.

Design law unchanged: a degradation is a named WARN/SKIP, never PASS; "cannot
determine" is never clean; rc 0 is never sufficient.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from helpers import SCRIPTS, git, run_python, scaffold

INIT = SCRIPTS / "init_sync.py"

# `reference.md` documents `decisions_file` and every `budgets` KEY as a
# repo-relative path, so the escape is a contract violation, not a design choice.
ESCAPING = "../outside/DECISIONS.md"


def cfg_of(repo: Path) -> dict:
    return json.loads((repo / ".ai" / "sync_config.json").read_text("utf-8"))


def set_config(repo: Path, **keys) -> None:
    path = repo / ".ai" / "sync_config.json"
    cfg = cfg_of(repo)
    cfg.update(keys)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def verify(repo: Path, *args: str):
    """Run THIS TREE's installed verifier, i.e. what an operator actually runs."""
    return run_python(repo / ".ai" / "scripts" / "sync_verify.py", list(args),
                      cwd=repo)


def checkpoint(tree: Path, *args: str):
    return run_python(tree / ".ai" / "scripts" / "checkpoint.py", list(args),
                      cwd=tree)


def passed_and_total(res) -> tuple[int, int]:
    line = [ln for ln in res.lines if "checks passed" in ln][-1]
    body = line.split("==")[1].strip().split(" ")[0]
    passed, total = body.split("/")
    return int(passed), int(total)


# ---------------------------------------------------------------- F1 --------
@pytest.mark.parametrize("bad", [ESCAPING, "D:/somewhere/outside/DECISIONS.md",
                                 "/etc/DECISIONS.md"])
def test_f1_decisions_file_cannot_leave_the_checkout(ai_repo, bad):
    """RED-AT-BASE: `[PASS] budget DECISIONS active entries: 3 entries (cap 20)`
    at rc 0 while the repo's own decision log sat uncapped (F1)."""
    set_config(ai_repo, decisions_file=bad)
    res = verify(ai_repo)
    assert "[FAIL] config readable: malformed: config key 'decisions_file' " \
        "must be a repo-relative path inside the checkout" in res.stdout, res.stdout
    assert "budget DECISIONS" not in res.stdout, res.stdout
    assert res.rc == 2, res.stdout


def test_f1_budget_keys_cannot_leave_the_checkout(ai_repo):
    """RED-AT-BASE: `[PASS] budget ../outside/DECISIONS.md: 3 lines
    (cap 99999)` (F1's second surface)."""
    cfg = cfg_of(ai_repo)
    cfg["budgets"][ESCAPING] = 99999
    (ai_repo / ".ai" / "sync_config.json").write_text(json.dumps(cfg, indent=2),
                                                      encoding="utf-8")
    res = verify(ai_repo)
    assert "malformed: config key 'budgets' keys must be repo-relative paths " \
        f"inside the checkout, not ['{ESCAPING}']" in res.stdout, res.stdout
    assert "budget ../outside" not in res.stdout, res.stdout
    assert res.rc == 2, res.stdout


def test_f1_control_repo_relative_paths_still_pass(ai_repo):
    """CONTROL (green at base): the same tree with untouched repo-relative keys
    is still a clean run — F1 must not reject what a healthy install does."""
    assert "[PASS] config readable" in verify(ai_repo).stdout


# ---------------------------------------------------------------- F2 --------
def test_f2_unlock_refuses_a_linked_worktree_and_keeps_the_hold(ai_repo,
                                                                tmp_path):
    """RED-AT-BASE: `--unlock` in a linked worktree exited 0 and wrote
    `released_at` into the worktree's tracked copy (F2)."""
    repo = ai_repo
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "install")
    got = checkpoint(repo, "--lock", "--agent", "claude-code",
                     "--reason", "holding the pen")
    assert got.rc == 0, got.stdout
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "lock")
    wt = tmp_path / "wt1"
    git(repo, "worktree", "add", "-q", str(wt), "-b", "wt")
    refused = checkpoint(wt, "--lock", "--agent", "codex", "--reason", "try")
    assert refused.rc == 1, refused.stdout
    # The red this pins: at base HEAD this exited 0 and wrote `released_at` into
    # the worktree's tracked copy while the main checkout stayed HELD.
    unlocked = checkpoint(wt, "--unlock", "--agent", "claude-code")
    assert unlocked.rc == 1, unlocked.stdout
    assert "REFUSED" in unlocked.stdout, unlocked.stdout
    assert "released_at" not in unlocked.stdout, unlocked.stdout
    # R4 finding 4 (MINOR): the refusal reused `--lock`'s remedy verbatim, so the
    # command that releases a pen told the operator to run the command that TAKES
    # one (`--lock --agent <name> --force --reason "<why>"`). The override is the
    # same flag on the command actually typed, and `--reason` is `--lock`'s
    # alone -- it is the only one that records a reason in WRITER_LOCK.json.
    assert "--unlock --agent <name> --force" in unlocked.stdout, unlocked.stdout
    assert "--lock --agent" not in unlocked.stdout, unlocked.stdout
    assert '--reason "<why>"' not in unlocked.stdout, unlocked.stdout
    main_lock = repo / ".ai/runtime/WRITER_LOCK.json"
    wt_lock = wt / ".ai/runtime/WRITER_LOCK.json"
    assert json.loads(main_lock.read_text("utf-8"))["released_at"] is None
    assert json.loads(main_lock.read_text("utf-8"))["agent"] == "claude-code"
    assert json.loads(wt_lock.read_text("utf-8"))["released_at"] is None
    assert not git(wt, "status", "--porcelain"), "a refusal must write nothing"
    # --force stays the documented override, and says what it just did.
    forced = checkpoint(wt, "--unlock", "--agent", "claude-code", "--force")
    assert forced.rc == 0 and "WARN unlock" in forced.stdout, forced.stdout
    assert json.loads(wt_lock.read_text("utf-8"))["released_at"] is not None
    # The point of the refusal: the override is local, so the other machine's
    # hold is still there. That is a documented limit, not a silent lie.
    assert json.loads(main_lock.read_text("utf-8"))["released_at"] is None


# ---------------------------------------------------------------- F3 --------
def test_f3_clobber_with_no_agents_block_keeps_a_cap_the_file_meets(tmp_path):
    """RED-AT-BASE: `--clobber --no-agents-block` restored cap 65 under a
    66-line AGENTS.md, exited 0 and promised "no FAILED line" (F3)."""
    repo = git_repo_with_agents_file(tmp_path)
    assert scaffold(repo).rc == 0
    assert (repo / ".ai" / "scripts" / "sync_verify.py").exists()
    n = len((repo / "AGENTS.md").read_text(encoding="utf-8").splitlines())
    assert n == 66, n  # 50 own lines + the 16-line managed block
    again = scaffold(repo, "--clobber", "--no-agents-block")
    assert again.rc == 0, again.stdout
    cap = cfg_of(repo)["budgets"]["AGENTS.md"]
    assert cap >= n, f"installer wrote cap {cap} under a {n}-line file it left"
    res = verify(repo)
    assert "FAILED" not in res.stdout, res.stdout
    assert res.rc == 0, res.stdout


def git_repo_with_agents_file(tmp_path) -> Path:
    from helpers import make_repo
    repo = make_repo(tmp_path)
    (repo / "AGENTS.md").write_text(
        "\n".join(f"rule {i}" for i in range(50)) + "\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "own agents file")
    return repo


# ---------------------------------------------------------------- F4 --------
def test_f4_an_unreachable_cap_is_a_named_malformed_value(ai_repo):
    """RED-AT-BASE: six `[PASS] … (cap 999999999)` lines at rc 0, with the
    500-entry decision log measured and booked as verified (F4)."""
    set_config(ai_repo, budgets={".ai/state/CURRENT.md": 999999999},
               decisions_max_active_entries=999999999,
               check_timeout=999999999)
    res = verify(ai_repo)
    assert "above 10000 lines cannot fail" in res.stdout, res.stdout
    assert res.rc == 2, res.stdout
    assert "cap 999999999" not in res.stdout, res.stdout


def test_f4_control_a_large_but_reachable_cap_still_measures(ai_repo):
    """CONTROL (green at base): the ceiling must not swallow a generous-but-
    realizable cap; 10,000 lines is still a measurement that can fail."""
    set_config(ai_repo, budgets={**cfg_of(ai_repo)["budgets"],
                                 ".ai/state/CURRENT.md": 10_000})
    res = verify(ai_repo)
    assert "[PASS] budget .ai/state/CURRENT.md: 42 lines (cap 10000)" \
        in res.stdout, res.stdout
    assert res.rc == 0, res.stdout


# ---------------------------------------------------------------- F5 --------
def test_f5_the_numerator_never_counts_a_line_that_did_not_print(ai_repo):
    """RED-AT-BASE: 19 counted PASSes against 18 printed `[PASS]` lines, and the
    whole extra-checks section collapsed into one UnicodeEncodeError FAIL (F5).
    The numerator has to equal the evidence actually printed."""
    cfg = cfg_of(ai_repo)
    cfg["extra_checks"] = [{"name": "freeze", "cmd": [
        sys.executable, "-c",
        "import sys; sys.stdout.buffer.write(b'ok \\xff\\xfe byte')"]}]
    (ai_repo / ".ai" / "sync_config.json").write_text(json.dumps(cfg, indent=2),
                                                      encoding="utf-8")
    res = run_python(ai_repo / ".ai" / "scripts" / "sync_verify.py", [],
                     cwd=ai_repo, env={"PYTHONIOENCODING": "utf-8"})
    printed = [ln for ln in res.lines
               if ln.startswith(("[PASS]", "[FAIL]", "[SKIP]"))]
    passed, total = passed_and_total(res)
    assert passed == sum(1 for ln in printed if ln.startswith("[PASS]")), \
        f"{res.stdout}\n-- counted {passed}, printed " \
        f"{sum(1 for ln in printed if ln.startswith('[PASS]'))}"
    assert total == len(printed), f"{res.stdout}\n-- counted {total} checks, " \
        f"printed {len(printed)} lines"
    assert "UnicodeEncodeError" not in res.stdout, res.stdout
    assert "[FAIL] extra checks check" not in res.stdout, \
        "one undisplayable child line must not delete the whole section"


def test_f5_a_line_that_cannot_be_written_is_a_named_degradation(ai_repo,
                                                                 monkeypatch):
    """The other half of F5, pinned directly: `record()` may only append AFTER a
    line survives the stream, and a line that does not survive must be booked as
    a named FAIL rather than silently counted as the verdict it would have been.
    `protect_stdio()` now prevents the incident, so this is the guard behind it
    (RED-AT-BASE for the append-before-print ordering)."""
    import importlib.util
    name = "_sv_under_test_lane_z_f5"
    saved = sys.modules.pop("ai_common", None)
    try:
        spec = importlib.util.spec_from_file_location(
            name, str(ai_repo / ".ai" / "scripts" / "sync_verify.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
        sys.modules.pop("ai_common", None)
        if saved is not None:
            sys.modules["ai_common"] = saved
    mod.RESULTS.clear()

    class Exploding:
        def write(self, *_a):
            raise UnicodeEncodeError("utf-8", "boom", 0, 1, "surrogates not ok")

        def flush(self):
            pass

    real = sys.stdout
    sys.stdout = Exploding()
    try:
        mod.record("freeze", True, "child wrote \udcff bytes")
    finally:
        sys.stdout = real
    assert len(mod.RESULTS) == 1, mod.RESULTS
    name, ok, evidence = mod.RESULTS[0]
    assert ok is False, "an unprinted PASS must not stay a PASS"
    assert name == "freeze (unprintable)", name
    assert "not a verification" in evidence, evidence


# ---------------------------------------------------------------- F6 --------
def test_f6_an_unusable_config_exits_2_as_documented(ai_repo):
    """RED-AT-BASE: rc 1 for a config nobody can read, while `SKILL.md`'s
    exit-code table documents rc 2 as "no verdict: … config unusable" (F6)."""
    set_config(ai_repo, required_files=[ESCAPING])
    res = verify(ai_repo)
    assert "== 0/1 checks passed ==" in res.lines, res.lines
    assert "FAILED: config readable" in res.stdout, res.stdout
    assert res.rc == 2, "SKILL.md's table says 2 for a config nobody can read"
    assert "NOT VERIFIED" in res.stdout, res.stdout


def test_f6_control_a_real_failure_still_exits_1(ai_repo):
    """CONTROL (green at base): rc 2 is for "no verdict", never for a check that
    ran and failed — a real FAIL must stay rc 1."""
    (ai_repo / ".ai/state/CURRENT.md").write_text("", encoding="utf-8")
    res = verify(ai_repo)
    assert res.rc == 1, res.stdout


# ---------------------------------------------------------------- F7 --------
def test_f7_a_future_stamp_is_named_not_certified(ai_repo):
    """RED-AT-BASE: `[PASS] protocol version readable: 99.99.99` at rc 0, and
    the documented `--scripts-only` upgrade path then refuses the tree (F7)."""
    (ai_repo / ".ai/protocol/VERSION").write_text("99.99.99\n",
                                                  encoding="utf-8")
    res = verify(ai_repo)
    assert "[PASS] protocol version" not in res.stdout, res.stdout
    assert "[FAIL] protocol version matches installed scripts" in res.stdout, \
        res.stdout
    assert "99.99.99" in res.stdout and "2.1.0" in res.stdout, res.stdout
    assert res.rc == 1, res.stdout
    # The documented upgrade path must not be bricked by the tree it is run in.
    upgrade = run_python(INIT, [str(ai_repo), "--scripts-only"], cwd=ai_repo)
    assert upgrade.rc == 1 and "VERSION MISMATCH" in upgrade.stdout, \
        upgrade.stdout
    assert "[FAIL] protocol version matches installed scripts" \
        in verify(ai_repo).stdout, "the refusal left the stamp unverified-clean"


def test_f7_stamp_and_installed_scripts_agree(ai_repo):
    """CONTROL (green at base as a total, red as this wording): a default
    install's stamp and its installed scripts name the same version, and the
    PASS line says so instead of only "readable"."""
    res = verify(ai_repo)
    assert "[PASS] protocol version readable: 2.1.0" in res.stdout, res.stdout
    assert "matches the 2.1.0 these scripts implement" in res.stdout, res.stdout
    assert res.rc == 0, res.stdout


def test_f7_the_version_constant_ships_with_the_install(ai_repo):
    """RED-AT-BASE: `PROTOCOL_VERSION` lived only in `init_sync.py`, which is
    not installed, so an installed tree held no copy of the version its scripts
    implement (F7's root cause)."""
    shipped = (ai_repo / ".ai/scripts/ai_common.py").read_text("utf-8")
    assert 'PROTOCOL_VERSION = "2.1.0"' in shipped, \
        "an installed tree with no copy of the version its scripts implement is " \
        "what let a hand-edited stamp certify itself"
