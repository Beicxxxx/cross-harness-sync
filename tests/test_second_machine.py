"""Task 7 (D6, D16, spec 10.B): a fresh clone on a second machine.

Two defects, one scenario. A second machine clones the repo, and:

  * D16: git does not track empty directories, so every directory the protocol
    creates but leaves empty on install day -- `handoff/archive`, `state/archive`,
    `state/authorizations`, `runtime` -- is simply absent in the clone. The first
    `--handoff` there used to die writing into a directory that was never cloned.
  * D6: mirrored secrets are git-ignored BY DESIGN, so neither side of a
    `secret_mirrors` pair can exist on a second machine, and the check used to
    record FAIL for that. Close-out was therefore unreachable on machine two for
    any repo that declares a mirror -- a permanent red nobody could fix without
    committing a secret.

Both halves obey spec 4: the D6 fix is a named SKIP, not a PASS, and it stays out
of the passed fraction (`sync_verify._summarise`). A mirror pair that really does
disagree on a machine holding both sides still fails (see the last two tests).

Clone discipline: the commit helpers run `git` in `tmp_path`, never in this
checkout (`helpers.git` refuses the latter), and the clone inherits no repo-local
`[user]` block, which is what `helpers.hermetic_env` supplies the identity for.
"""
from __future__ import annotations

import json

from helpers import git, run_python

MIRROR_PAIR = [".env", ".claude/.env"]

# The tracked placeholders the installer owes a fresh clone (D16).
PLACEHOLDERS = (
    ".ai/handoff/archive/.gitkeep",
    ".ai/state/archive/.gitkeep",
    ".ai/state/authorizations/.gitkeep",
    ".ai/runtime/.gitkeep",
)


def _install_clone(ai_repo, tmp_path, name="clone"):
    """Commit the install in `ai_repo` and clone it somewhere else."""
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "install")
    clone = tmp_path / name
    git(tmp_path, "clone", "-q", str(ai_repo), str(clone))
    return clone


def _with_mirrors(ai_repo, extra=None):
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["secret_mirrors"] = [MIRROR_PAIR]
    for key, val in (extra or {}).items():
        cfg[key] = val
    cfg_path.write_text(json.dumps(cfg), "utf-8")


def test_the_installer_tracks_a_placeholder_for_every_empty_protocol_dir(ai_repo):
    """A directory only survives a clone if something inside it is tracked.

    `git ls-files` is the assertion, not `Path.exists()`: a directory present on
    the installing machine proves nothing about the cloning one.
    """
    git(ai_repo, "add", "-A")
    tracked = set(git(ai_repo, "ls-files").splitlines())
    missing = [rel for rel in PLACEHOLDERS if rel not in tracked]
    assert not missing, f"untracked empty dirs die in a clone: {missing}"


def test_a_fresh_clone_has_the_protocol_directories(ai_repo, tmp_path):
    clone = _install_clone(ai_repo, tmp_path)
    for rel in (".ai/handoff/archive", ".ai/state/archive",
                ".ai/state/authorizations", ".ai/runtime"):
        assert (clone / rel).is_dir(), f"{rel} did not survive the clone"


def test_handoff_works_on_a_fresh_clone(ai_repo, tmp_path):
    """Empty dirs are not tracked by git, so a clone used to crash here."""
    clone = _install_clone(ai_repo, tmp_path, "clone-handoff")
    cp = clone / ".ai" / "scripts" / "checkpoint.py"
    res = run_python(cp, ["--handoff", "--agent", "codex"], cwd=clone)
    assert res.rc == 0, res.stdout + res.stderr
    assert (clone / ".ai" / "runtime").is_dir()


def test_mirror_check_skips_when_neither_side_exists(ai_repo, sv):
    """D6: an absent mirror on THIS machine is not a failure of the install."""
    _with_mirrors(ai_repo)
    res = run_python(sv, cwd=ai_repo)
    skip = ("[SKIP] secret mirror .env vs .claude/.env: "
            "SKIP(no mirrored secrets on this machine)")
    assert res.lines.count(skip) == 1, res.lines
    assert not any(ln.startswith("[FAIL] secret mirror") for ln in res.lines), \
        res.lines
    assert any("SKIP" in ln for ln in res.lines), res.lines
    # The SKIP must not be booked as a pass: it is in the denominator only.
    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1, res.lines
    assert ", 1 skipped" in summary[0], summary[0]


def test_mirror_check_names_which_side_this_machine_is_missing(ai_repo, sv):
    """One side present is a DIFFERENT fact from none, and gets its own text."""
    _with_mirrors(ai_repo)
    (ai_repo / ".env").write_text("A=1\n", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    line = [ln for ln in res.lines if ln.startswith("[SKIP] secret mirror")]
    assert len(line) == 1, res.lines
    assert "present on this machine: .env" in line[0], line[0]
    assert "absent: .claude/.env" in line[0], line[0]
    assert not any(ln.startswith("[FAIL] secret mirror") for ln in res.lines), \
        res.lines


def test_mirror_check_still_fails_when_both_exist_differing(ai_repo, sv):
    """The SKIP is for absence, never for disagreement -- spec 4."""
    _with_mirrors(ai_repo, extra={"secret_files": []})
    (ai_repo / ".env").write_text("A=1\n", encoding="utf-8")
    (ai_repo / ".claude").mkdir()
    (ai_repo / ".claude" / ".env").write_text("B=2\n", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any(ln.startswith("[FAIL] secret mirror") for ln in res.lines), res.lines
    assert not any(ln.startswith("[SKIP] secret mirror") for ln in res.lines), \
        res.lines


def test_mirror_check_passes_when_both_exist_and_agree(ai_repo, sv):
    _with_mirrors(ai_repo, extra={"secret_files": []})
    (ai_repo / ".env").write_text("A=1\nB=2\n", encoding="utf-8")
    (ai_repo / ".claude").mkdir()
    (ai_repo / ".claude" / ".env").write_text("A=9\nB=8\n", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] secret mirror") for ln in res.lines), res.lines


def test_second_machine_full_closeout_cycle(ai_repo, tmp_path):
    """spec 10.B end to end: clone, verify green, lock, hand off, unlock, push.

    The remote is a BARE repo, not machine one's working tree: pushing into a
    branch that is checked out is refused by default, and the real protocol has
    machine one `git pull` the handoff instead. That pull-back is the half of the
    acceptance that proves the handoff is readable on the first machine, so it is
    asserted here rather than run only by hand.
    """
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "install")
    shared = tmp_path / "shared.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(shared))
    git(ai_repo, "remote", "add", "origin", str(shared))
    git(ai_repo, "push", "-q", "origin", "main")
    clone = tmp_path / "clone2"
    git(tmp_path, "clone", "-q", str(shared), str(clone))
    cp = clone / ".ai" / "scripts" / "checkpoint.py"
    sv = clone / ".ai" / "scripts" / "sync_verify.py"
    assert run_python(cp, ["--lock", "--agent", "claude-code",
                           "--reason", "wave1"], cwd=clone).rc == 0
    verify = run_python(sv, cwd=clone)
    assert verify.rc == 0, verify.stdout + verify.stderr
    assert any("checks passed" in ln for ln in verify.lines), verify.lines
    assert run_python(cp, ["--handoff", "--agent", "claude-code"],
                      cwd=clone).rc == 0
    assert run_python(cp, ["--unlock", "--agent", "claude-code"],
                      cwd=clone).rc == 0
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "handoff from claude-code")
    git(clone, "push", "-q", "origin", "main")
    assert git(shared, "rev-parse", "main") == git(clone, "rev-parse", "HEAD")
    # machine one reads the handoff back: the bytes on disk in clone 1 are the
    # bytes machine two wrote, which is the whole point of the shared remote.
    git(ai_repo, "pull", "-q", "origin", "main")
    pulled = (ai_repo / ".ai" / "handoff" / "LATEST.md").read_bytes()
    assert pulled == (clone / ".ai" / "handoff" / "LATEST.md").read_bytes(), pulled
    assert pulled, "machine one pulled an empty handoff"
    assert git(ai_repo, "rev-parse", "HEAD") == git(clone, "rev-parse", "HEAD")

