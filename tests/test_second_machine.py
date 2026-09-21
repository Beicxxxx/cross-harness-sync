"""Task 7 (D6, D16, spec 10.B): a fresh clone on a second machine.

Two defects, one scenario. A second machine clones the repo, and:

  * D16: git does not track empty directories, so the DIRECTORY SET the protocol
    creates but leaves empty on install day -- `handoff/archive`, `state/archive`,
    `state/authorizations`, `runtime` -- is simply absent in the clone. (An
    earlier draft of this file said the first `--handoff` there "crashed"; that
    was false at the base commit -- `cmd_handoff` mkdirs the archive itself and
    `_atomic_write` mkdirs every JSON parent -- so what is pinned here is that
    the directory set is present and tracked, not a crash that never happened.)
  * D6: mirrored secrets are git-ignored BY DESIGN, so NEITHER side of a
    `secret_mirrors` pair can exist on a second machine, and the check used to
    record FAIL for that. Close-out was therefore unreachable on machine two for
    any repo that declares a mirror -- a permanent red nobody could fix without
    committing a secret. Only that both-absent branch is a SKIP. Exactly one
    side present is evidence of local drift (half a mirror, or a typo in
    `secret_mirrors`, where a wrong path is indistinguishable from an absent
    one) and stays a FAIL: spec 4 lets an absent file skip only when its absence
    is covered elsewhere, and nothing covers that case.

Both halves obey spec 4: the D6 SKIP is a named SKIP, not a PASS, and it stays
out of the passed fraction (`sync_verify._summarise`). A mirror pair that really
does disagree on a machine holding both sides still fails (see the last tests).

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
    """The protocol's directory set is absent from a clone unless tracked.

    Not "a clone used to crash here": it never could, because `cmd_handoff`
    mkdirs the archive and `_atomic_write` mkdirs each JSON parent. What this
    pins is that the clone has the directories a close-out writes into.
    """
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


def test_mirror_check_fails_when_only_one_side_exists(ai_repo, sv):
    """One side present is drift, not a per-machine difference -- spec 4.

    Lane T7's D6 fix went one branch too far and turned this shape into a SKIP,
    so a typo'd mirror path or a half-deleted secret store exited 0. The two
    branches are named apart: neither file is a `SKIP`, exactly one is a `FAIL`
    that names which side is missing.
    """
    _with_mirrors(ai_repo)
    (ai_repo / ".env").write_text("A=1\n", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    line = [ln for ln in res.lines if ln.startswith("[FAIL] secret mirror")]
    assert len(line) == 1, res.lines
    assert "present on this machine: .env" in line[0], line[0]
    assert "absent: .claude/.env" in line[0], line[0]
    assert res.rc == 1, res.stdout + res.stderr
    assert not any(ln.startswith("[SKIP] secret mirror") for ln in res.lines), \
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


# --------------------------------------------------------------------------
# lane W: what the two-clone acceptance actually holds constant, plus the D16
# UPGRADE path, the layout record, and what --scripts-only promises.

import re  # noqa: E402  (mid-file import keeps lane W's block self-contained)

from helpers import REPO_ROOT, SCRIPTS, scaffold  # noqa: E402


def test_two_identities_and_a_registered_mirror_share_a_remote(ai_repo, tmp_path):
    """The strongest two-clone acceptance this repo can build on ONE host.

    It varies what the cycle above held constant -- a distinct `--author`
    identity per commit, so git was told who wrote each one rather than reading
    a shared `[user]` block; a separate HOME per clone (`hermetic_env` points
    HOME/USERPROFILE at the directory the child runs in, so neither clone can
    reach the other's or the developer's global config); and one registered
    `secret_mirrors` pair, whose BOTH-ABSENT SKIP, ONE-SIDE-PRESENT FAIL and
    BOTH-PRESENT PASS are all exercised on the clone.
    It still does NOT vary host, filesystem, locale, code page or git's
    line-ending config, so it is not cross-machine verification; what it proves
    is that the D6 branches and the identity plumbing hold across a push/pull.
    The AUTHOR identity is the one git lets a test vary per command (`--author`;
    a per-command `-c user.*` cannot beat the `GIT_AUTHOR_*` the harness pins in
    the environment), so the committer side of "two machines" stays held
    constant here, and that limit is stated instead of papered over.
    """
    _with_mirrors(ai_repo)
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q",
        "--author=Machine One <one@example.invalid>", "-m", "install")
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
    # Neither mirrored secret exists here: a legitimate per-machine difference,
    # and a named SKIP at rc 0 (D6's both-absent branch).
    verify = run_python(sv, cwd=clone)
    assert verify.rc == 0, verify.stdout + verify.stderr
    assert any(ln.startswith("[SKIP] secret mirror")
               and "no mirrored secrets on this machine" in ln
               for ln in verify.lines), verify.lines
    # Exactly one side appearing on machine two is drift, not a per-machine
    # difference: FAIL naming the missing side, at rc 1 (item 2).
    (clone / ".env").write_text("A=1\nB=2\n", encoding="utf-8")
    half = run_python(sv, cwd=clone)
    assert half.rc == 1, half.stdout + half.stderr
    assert any(ln.startswith("[FAIL] secret mirror")
               and "absent: .claude/.env" in ln for ln in half.lines), half.lines
    (clone / ".claude").mkdir()
    (clone / ".claude" / ".env").write_text("A=9\nB=8\n", encoding="utf-8")
    both = run_python(sv, cwd=clone)
    assert both.rc == 0, both.stdout + both.stderr
    assert any(ln.startswith("[PASS] secret mirror") for ln in both.lines), \
        both.lines
    assert run_python(cp, ["--handoff", "--agent", "claude-code"],
                      cwd=clone).rc == 0
    assert run_python(cp, ["--unlock", "--agent", "claude-code"],
                      cwd=clone).rc == 0
    git(clone, "add", "-A")
    assert not [ln for ln in git(clone, "ls-files").splitlines()
                if ln.endswith(".env")], "a mirrored secret reached the index"
    git(clone, "commit", "-q", "--author=Machine Two <two@example.invalid>",
        "-m", "handoff from claude-code")
    git(clone, "push", "-q", "origin", "main")
    authors = git(shared, "log", "--format=%ae").splitlines()
    assert "two@example.invalid" in authors, authors
    assert "one@example.invalid" in authors, authors
    git(ai_repo, "pull", "-q", "origin", "main")
    assert git(ai_repo, "rev-parse", "HEAD") == git(clone, "rev-parse", "HEAD")
    assert (ai_repo / ".ai" / "handoff" / "LATEST.md").read_bytes() == \
        (clone / ".ai" / "handoff" / "LATEST.md").read_bytes()


def test_scripts_only_repairs_a_stale_gitignore_and_tracks_the_placeholder(repo):
    """D16 has to survive the flag existing installs are told to run.

    `--scripts-only` wrote `.ai/runtime/.gitkeep` from a branch that could not
    reach `update_gitignore()`, so on any tree scaffolded before that exception
    existed the placeholder was created, stayed covered by the `.ai/runtime/*`
    glob, and `git add -A` silently dropped it: the second machine still got no
    directory. `git ls-files` is the assertion, because the question is what the
    OTHER machine receives.
    """
    assert scaffold(repo).rc == 0
    stale = "\n".join(["", "# cross-harness-sync", ".ai/runtime/*",
                       "!.ai/runtime/WRITER_LOCK.json", ".env", ""])
    (repo / ".gitignore").write_text(stale, encoding="utf-8")
    keep = repo / ".ai" / "runtime" / ".gitkeep"
    keep.unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "an install predating the gitignore fix")
    res = scaffold(repo, "--scripts-only")
    assert res.rc == 0, res.stdout + res.stderr
    assert keep.exists(), res.stdout
    assert "!.ai/runtime/.gitkeep" in (repo / ".gitignore").read_text("utf-8"), \
        res.stdout
    git(repo, "add", "-A")
    tracked = set(git(repo, "ls-files").splitlines())
    assert ".ai/runtime/.gitkeep" in tracked, (
        "the upgrade wrote a placeholder git will not carry: "
        f"{sorted(p for p in tracked if p.startswith('.ai/runtime'))}")


def test_a_green_run_books_the_layout_gate_it_passed(ai_repo, sv):
    """Item 4: a report that never mentions check 0 cannot be audited.

    The layout check had exactly one `record()` call and it was the FAIL, so a
    `17/18 checks passed` line carried no evidence the gate ran -- against this
    wave's own "silence is not clean" sentences. This is also finding 12's
    denominator pin: the passed count plus the skipped count IS the total.
    """
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    layout = [ln for ln in res.lines if "install layout" in ln]
    assert len(layout) == 1, res.lines
    assert layout[0].startswith("[PASS] install layout: normal"), layout[0]
    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1, res.lines
    match = re.fullmatch(r"== (\d+)/(\d+) checks passed(?:, (\d+) skipped)? ==",
                         summary[0])
    assert match, summary[0]
    passed, total, skipped = match.groups()
    assert int(passed) + int(skipped or 0) == int(total), summary[0]


def test_scripts_only_help_says_what_the_flag_touches():
    """Item 5: the shipped `--help` contradicted the shipped behaviour.

    "no state, config, template, AGENTS.md, CLAUDE.md or .gitignore is read,
    written or created" was vacuously true before lane V made the flag refresh
    scripts and is false now; two SCRIPT strings were routed to a doc lane that
    cannot ship them.
    """
    res = run_python(SCRIPTS / "init_sync.py", ["--help"], cwd=REPO_ROOT)
    assert res.rc == 0, res.stdout + res.stderr
    text = " ".join(res.stdout.split())
    assert "is read, written or created" not in text, text
    assert ".ai/scripts/" in text and "protocol/VERSION" in text, text
    assert "placeholder" in text, text
    assert ".gitignore" in text, text
    assert "Implied by --scripts-only." in text, text
    src = (SCRIPTS / "init_sync.py").read_text(encoding="utf-8")
    assert "read, written or created" not in src, "the docstring tells it again"


def test_scripts_only_names_every_script_it_replaces(ai_repo):
    """Item 6: notice-only. The behaviour stands, the silence does not.

    A fail-closed tool that swaps bytes over an install must say so, and say
    which of the two cases it is: an older shipped version (the upgrade path
    working), or a copy that differs from what THESE scripts install, which can
    only be a local edit. Neither case needs `--force`: the upgrade stays one
    command.
    """
    untouched = scaffold(ai_repo, "--scripts-only")
    assert untouched.rc == 0, untouched.stdout + untouched.stderr
    assert not [ln for ln in untouched.lines
                if ln.startswith("NOTE replaced:")], untouched.lines
    script = ai_repo / ".ai" / "scripts" / "sync_verify.py"
    script.write_bytes(script.read_bytes() + b"\n# hand edit\n")
    res = scaffold(ai_repo, "--scripts-only")
    assert res.rc == 0, res.stdout + res.stderr
    notes = [ln for ln in res.lines if ln.startswith("NOTE replaced:")]
    assert len(notes) == 1, res.lines
    assert "sync_verify.py" in notes[0], notes[0]
    assert "locally modified" in notes[0], notes[0]
    assert script.read_bytes() == (SCRIPTS / "sync_verify.py").read_bytes()

