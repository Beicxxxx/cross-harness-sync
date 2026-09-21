"""`init_sync.py --migrate` (spec §8): refuse-and-write-nothing, NO_HISTORY,
`.new` sidecars, the text-edited config, the writer lock, the `.ai/**` commit,
and idempotency as a VERIFYING no-op.

Every assertion here is about what the migrated tree itself does next, not about
what a printout claimed: `rc == 0` is never the evidence, so each test reads the
config, `MIGRATION.json`, the commit's own file list, and (where git is
involved) the bytes of the files it must not have touched.

Temp repos only, always under `tmp_path` — `git()` refuses to run inside this
checkout, which is the guard that keeps a migration test from rewriting the
branch the wave is on.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from helpers import (REPO_ROOT, SCRIPTS, git, make_repo, run_python, scaffold,
                     write_lock)


def _load(name: str, path: Path):
    """Import a shipped script by path without poisoning `sys.modules['ai_common']`
    (the reason `tests/test_governance_record.py` spells the same helper)."""
    saved = sys.modules.pop("ai_common", None)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
        sys.modules.pop("ai_common", None)
        if saved is not None:
            sys.modules["ai_common"] = saved
    return mod


init_sync = _load("_b3_migrate_init_sync", SCRIPTS / "init_sync.py")
ai_common = _load("_b3_migrate_ai_common", SCRIPTS / "ai_common.py")

INDEX_REL = ".ai/state/authorizations/INDEX.md"
MIGRATION_REL = ".ai/protocol/MIGRATION.json"
JOURNAL_REL = ".ai/protocol/MIGRATION.md"
LOCK_REL = ".ai/runtime/WRITER_LOCK.json"
CONFIG_REL = ".ai/sync_config.json"
HEAD40 = re.compile(r"\A[0-9a-f]{40}\Z")


def migrate(repo: Path, *flags: str):
    return run_python(SCRIPTS / "init_sync.py",
                      [str(repo), "--migrate", *flags], cwd=repo)


def installed(repo: Path, msg: str = "install") -> Path:
    """A scaffolded install COMMITTED as-is: the state a real `--migrate` meets.

    Committed, because customization detection reads HEAD blobs — an install
    with no history is the documented unsolvable case (spec §8), so every test
    that asserts a decision about a script has to give git something to read.
    """
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return repo


def cfg_of(repo: Path) -> dict:
    return json.loads((repo / CONFIG_REL).read_text("utf-8"))


def snapshot(root: Path) -> dict:
    """`{rel-path: sha256}` for every file outside `.git/` — the write-nothing proof.

    `__pycache__` is excluded on purpose: it is a by-product of running an
    installed script (gitignored by N5's entries), not a state file `--migrate`
    could be accused of touching.
    """
    state = {}
    for dirpath, dirnames, filenames in os.walk(str(root)):
        if ".git" in dirnames:
            dirnames.remove(".git")
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        for name in filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            state[rel] = hashlib.sha256(full.read_bytes()).hexdigest()
    return state


def commit_files(repo: Path, ref: str = "HEAD") -> list:
    out = git(repo, "show", "--name-only", "--format=", ref)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


# ---------------------------------------------------------------------------
# the shape of a real migration


def test_migrate_records_head_index_and_pins_the_role_policy(tmp_path):
    repo = make_repo(tmp_path)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    # model the tree `--migrate` actually meets: an install from BEFORE wave 1b,
    # so the index is not on disk yet and only the migration can create it.
    (repo / INDEX_REL).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "pre-1b install")
    head = git(repo, "rev-parse", "HEAD")
    assert HEAD40.match(head), head

    res = migrate(repo)
    assert res.rc == 0, res.stdout + res.stderr
    cfg = cfg_of(repo)
    assert cfg["governance"]["window_start_commit"] == head, cfg
    role = (repo / ".ai/state/ROLE_POLICY.md").read_bytes()
    assert cfg["role_policy_sha256"] == hashlib.sha256(role).hexdigest(), cfg
    assert cfg["authorizations_dir"] == ".ai/state/authorizations", cfg
    assert cfg["protected_paths"] == [], cfg
    assert cfg["protected_paths_case"] == "case-sensitive", cfg

    index = repo / INDEX_REL
    assert index.is_file() and index.stat().st_size > 0, res.lines

    record = json.loads((repo / MIGRATION_REL).read_text("utf-8"))
    # The record's exact shape, pinned: `warnings`/`degraded` are there so an
    # rc-only caller (a hook, a wrapper script) can see a `.new`-sidecar
    # divergence — a run that exits 0 having NOT delivered every script.
    assert set(record) == {"from", "to", "started", "completed",
                           "files_touched", "warnings", "degraded"}, record
    assert record["warnings"] == [] and record["degraded"] is False, record
    assert record["to"] == init_sync.PROTOCOL_VERSION, record
    # this install's own stamp is the `from`: the migration records the upgrade
    # it actually performed, and a re-run of the same version says so honestly.
    assert record["from"] == init_sync.PROTOCOL_VERSION, record
    assert INDEX_REL in record["files_touched"], record
    assert record["started"] and record["completed"], record

    # the commit: `.ai/**` only, and NOT the writer lock it acquired.
    files = commit_files(repo)
    assert files, res.lines
    assert all(rel.startswith(".ai/") for rel in files), files
    assert LOCK_REL not in files, files
    # the INDEX this run created is IN the commit (the install was a pre-1b
    # one, so nothing else could have written it).
    assert INDEX_REL in files, files
    assert git(repo, "ls-files", "--", INDEX_REL) == INDEX_REL
    # the lock record exists on disk (the run held the pen) and names its agent.
    lock = json.loads((repo / LOCK_REL).read_text("utf-8"))
    assert lock["agent"] == "init-sync-migrate", lock
    assert lock["released_at"] in (None, ""), lock


def test_a_migrated_tree_verifies_with_the_new_required_file(tmp_path):
    repo = installed(make_repo(tmp_path))
    assert migrate(repo).rc == 0
    res = run_python(repo / ".ai/scripts/sync_verify.py", [], cwd=repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] required " + INDEX_REL)
               for ln in res.lines), res.lines
    assert not any(ln.startswith("[FAIL]") for ln in res.lines), res.lines
    # `role policy integrity` was unpinned (SKIP) on a fresh install; a migrated
    # tree pinned the digest, so the check now answers a question.
    assert any(ln.startswith("[PASS] role policy integrity")
               for ln in res.lines), res.lines
    assert any("checks passed" in ln for ln in res.lines), res.lines


def test_validate_passes_on_a_migrated_tree(tmp_path):
    repo = installed(make_repo(tmp_path))
    assert migrate(repo).rc == 0
    res = run_python(repo / ".ai/scripts/checkpoint.py", ["--validate"],
                     cwd=repo)
    assert res.rc == 0, res.stdout + res.stderr
    # `--validate` prints `.ai`-relative names in the platform separator, so the
    # assertion is on the entry it reported and the verdict it gave, not on a
    # spelling.
    index_lines = [ln for ln in res.lines if "authorizations" in ln
                   and "INDEX.md" in ln]
    assert index_lines, res.lines
    assert any("OK" in ln for ln in index_lines), index_lines
    assert not any("MISS" in ln for ln in index_lines), index_lines


# ---------------------------------------------------------------------------
# refuse-and-write-nothing


def test_unborn_head_refuses_and_writes_nothing(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    before = snapshot(repo)

    res = migrate(repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert "unborn" in res.stdout.lower() or "no commits" in res.stdout.lower(), \
        res.lines
    assert "Nothing was written" in res.stdout, res.lines
    assert snapshot(repo) == before, "a refused migration still wrote a file"
    assert not (repo / MIGRATION_REL).exists()


def test_detached_head_refuses(tmp_path):
    repo = installed(make_repo(tmp_path))
    git(repo, "checkout", "-q", "--detach", "HEAD")
    before = snapshot(repo)

    res = migrate(repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert "detached" in res.stdout, res.lines
    assert snapshot(repo) == before
    assert git(repo, "status", "--porcelain") == ""


def test_a_newer_or_unparseable_stamp_refuses(tmp_path):
    repo = installed(make_repo(tmp_path))
    stamp = repo / ".ai/protocol/VERSION"
    stamp.write_text("9.9.9\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "newer stamp")
    before = snapshot(repo)
    res = migrate(repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert "NEWER" in res.stdout, res.lines
    assert snapshot(repo) == before

    stamp.write_text("nightly\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "unparseable stamp")
    before = snapshot(repo)
    res = migrate(repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert "unparseable" in res.stdout, res.lines
    assert snapshot(repo) == before


def test_an_unparseable_config_refuses_rather_than_dropping_the_owners_keys(
        tmp_path):
    repo = installed(make_repo(tmp_path))
    (repo / CONFIG_REL).write_text('{"budgets": }\n', encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "broken config")
    before = snapshot(repo)
    res = migrate(repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert "sync_config.json" in res.stdout, res.lines
    assert snapshot(repo) == before, \
        "a refused config edit must not rewrite anything else either"


def test_an_unstaged_edit_under_ai_scripts_aborts_the_whole_run(tmp_path):
    repo = installed(make_repo(tmp_path))
    head = git(repo, "rev-parse", "HEAD")
    target = repo / ".ai/scripts/checkpoint.py"
    target.write_text(read_bytes(target).decode("utf-8") + "\n# hand edit\n",
                      encoding="utf-8")
    before = snapshot(repo)

    res = migrate(repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert ".ai/scripts/checkpoint.py" in res.stdout, res.lines
    assert snapshot(repo) == before, "aborted after writing"
    assert git(repo, "rev-parse", "HEAD") == head
    assert not (repo / MIGRATION_REL).exists()


def test_a_held_writer_lock_refuses(tmp_path):
    repo = installed(make_repo(tmp_path))
    import datetime as _dt
    future = (_dt.datetime.now().astimezone()
              + _dt.timedelta(hours=1)).isoformat(timespec="seconds")
    write_lock(repo, json.dumps({"agent": "other-harness",
                                 "acquired_at": "2026-09-21T00:00:00+00:00",
                                 "expires_at": future, "released_at": None}))
    before = snapshot(repo)
    res = migrate(repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert "lock" in res.stdout.lower(), res.lines
    assert snapshot(repo) == before


# ---------------------------------------------------------------------------
# customization: `.new` sidecars, never a clobber


def test_a_diverged_script_gets_a_new_sidecar_and_keeps_its_bytes(tmp_path):
    repo = installed(make_repo(tmp_path))
    target = repo / ".ai/scripts/sync_verify.py"
    original = read_bytes(target)
    target.write_bytes(original + b"\n# local customisation\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "customised the verifier")

    res = migrate(repo)
    assert res.rc == 0, res.stdout + res.stderr
    sidecar = repo / ".ai/scripts/sync_verify.py.new"
    assert sidecar.is_file(), res.lines
    assert sidecar.read_bytes() == (SCRIPTS / "sync_verify.py").read_bytes()
    assert read_bytes(target) == original + b"\n# local customisation\n", \
        "a hand-customised script was overwritten"
    warns = [ln for ln in res.lines if ln.startswith("[WARN]")]
    assert any("sync_verify.py" in ln and ".new" in ln for ln in warns), res.lines
    assert not any(ln.startswith("wrote: .ai/scripts/sync_verify.py\n")
                   for ln in res.lines), res.lines
    record = json.loads((repo / MIGRATION_REL).read_text("utf-8"))
    assert ".ai/scripts/sync_verify.py.new" in record["files_touched"], record
    # the journal names it as not reversible by a revert of the migration commit.
    journal = (repo / JOURNAL_REL).read_text("utf-8")
    assert "sync_verify.py" in journal and "NOT reversible" in journal, journal


def test_a_pristine_script_is_refreshed_and_an_identical_one_is_untouched(
        tmp_path):
    """The two non-divergent branches, in one run.

    `.ai/scripts/checkpoint.py` carries a v2.0 blob (the embedded reference
    table's own digest), so overwriting it is the upgrade `--migrate` exists to
    deliver; `.ai/scripts/sync_verify.py` already holds the shipped bytes, so
    nothing is written for it and `files_touched` must say so honestly.
    """
    v20 = init_sync.V20_SCRIPT_SHA256[".ai/scripts/checkpoint.py"]
    blob = git_blob("e692e73", "scripts/checkpoint.py")
    # The embedded table is only worth having if it is the released v2.0 bytes.
    assert hashlib.sha256(blob).hexdigest() == v20, \
        "init_sync's v2.0 hash table does not match commit e692e73"

    repo = make_repo(tmp_path)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    shipped = {name: (SCRIPTS / name).read_bytes()
               for name in ("ai_common.py", "checkpoint.py", "sync_verify.py")}
    # forge a v2.0-looking install: the released checkpoint.py blob in HEAD.
    cp = repo / ".ai/scripts/checkpoint.py"
    cp.write_bytes(blob)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "v2.0 install")
    assert hashlib.sha256(
        git_blob_of(repo, "HEAD:.ai/scripts/checkpoint.py")).hexdigest() == v20

    res = migrate(repo)
    assert res.rc == 0, res.stdout + res.stderr
    record = json.loads((repo / MIGRATION_REL).read_text("utf-8"))
    assert ".ai/scripts/checkpoint.py" in record["files_touched"], record
    assert cp.read_bytes() == shipped["checkpoint.py"], \
        "a pristine v2.0 script was not refreshed"
    assert ".ai/scripts/sync_verify.py" not in record["files_touched"], record
    assert (repo / ".ai/scripts/sync_verify.py").read_bytes() == \
        shipped["sync_verify.py"]
    assert not (repo / ".ai/scripts/sync_verify.py.new").exists()


def git_blob(rev: str, rel: str) -> bytes:
    """A blob from THIS checkout (read-only; the v2.0 reference hashes' source)."""
    proc = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=str(REPO_ROOT),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def git_blob_of(repo: Path, rev_and_path: str) -> bytes:
    proc = subprocess.run(["git", "show", rev_and_path], cwd=str(repo),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


# ---------------------------------------------------------------------------
# NO_HISTORY: never a PASS-shaped claim


def test_no_repository_writes_the_no_history_sentinel(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir(parents=True)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr

    res = migrate(repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert cfg_of(repo)["governance"]["window_start_commit"] == "NO_HISTORY"
    assert "SKIP(no-history)" in res.stdout, res.lines
    assert not any(ln.startswith("[PASS]") and "window" in ln
                   for ln in res.lines), res.lines
    assert (repo / INDEX_REL).is_file()
    record = json.loads((repo / MIGRATION_REL).read_text("utf-8"))
    assert record["to"] == init_sync.PROTOCOL_VERSION, record
    # nothing was committed: there is no repository to commit into.
    assert not (repo / ".git").exists()


# ---------------------------------------------------------------------------
# idempotency: a re-run VERIFIES


def test_second_migrate_is_a_verifying_noop(tmp_path):
    repo = installed(make_repo(tmp_path))
    first = migrate(repo)
    assert first.rc == 0, first.stdout + first.stderr
    head = git(repo, "rev-parse", "HEAD")
    before_files = snapshot(repo)
    record_before = (repo / MIGRATION_REL).read_bytes()
    cfg_before = (repo / CONFIG_REL).read_bytes()

    res = migrate(repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert "already migrated" in res.stdout, res.lines
    assert git(repo, "rev-parse", "HEAD") == head, "a second migration commit"
    assert (repo / MIGRATION_REL).read_bytes() == record_before
    assert (repo / CONFIG_REL).read_bytes() == cfg_before
    assert snapshot(repo) == before_files, \
        "the re-run wrote a file, not just a verdict"


def test_idempotency_is_a_verify_not_a_trust(tmp_path):
    """MIGRATION.json present but the INDEX deleted: the re-run says so.

    A no-op that only reads its own record would report success over a tree that
    lost the file, which is the same fail-open class as `rc == 0`.
    """
    repo = installed(make_repo(tmp_path))
    assert migrate(repo).rc == 0
    (repo / INDEX_REL).unlink()
    head = git(repo, "rev-parse", "HEAD")

    res = migrate(repo)
    assert "[FAIL]" in res.stdout or "INCOMPLETE" in res.stdout, res.lines
    assert res.rc == 1, res.stdout + res.stderr
    assert not (repo / INDEX_REL).exists(), \
        "the re-run was supposed to verify, not silently re-migrate"
    assert git(repo, "rev-parse", "HEAD") == head


def test_the_migration_commit_is_tagged_and_scoped_to_ai(tmp_path):
    repo = installed(make_repo(tmp_path))
    (repo / "notes.txt").write_text("outside .ai\n", encoding="utf-8")
    res = migrate(repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert "cross-harness-sync-migrate" in git(repo, "log", "-1",
                                               "--format=%B"), res.lines
    files = commit_files(repo)
    assert all(rel.startswith(".ai/") for rel in files), files
    assert "notes.txt" not in files
    assert (repo / "notes.txt").exists(), "untracked work outside .ai survived"


def test_an_already_staged_change_outside_ai_refuses(tmp_path):
    repo = installed(make_repo(tmp_path))
    (repo / "elsewhere.txt").write_text("staged by the caller\n",
                                        encoding="utf-8")
    git(repo, "add", "elsewhere.txt")
    before = snapshot(repo)
    commits_before = git(repo, "rev-list", "--count", "HEAD")
    res = migrate(repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert "outside .ai/" in res.stdout, res.lines
    assert snapshot(repo) == before
    assert git(repo, "rev-list", "--count", "HEAD") == commits_before


# ---------------------------------------------------------------------------
# --authorizations-dir: never a guess


def test_authorizations_dir_is_honoured_and_recorded(tmp_path):
    repo = make_repo(tmp_path)
    assert scaffold(repo).rc == 0
    # a pre-1b install: the canonical home has no index yet, so the only INDEX
    # on disk after this run can be the one the flag asked for.
    (repo / INDEX_REL).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "pre-1b install")
    res = migrate(repo, "--authorizations-dir", ".ai/state/authz")
    assert res.rc == 0, res.stdout + res.stderr
    cfg = cfg_of(repo)
    assert cfg["authorizations_dir"] == ".ai/state/authz", cfg
    assert (repo / ".ai/state/authz/INDEX.md").is_file()
    assert not (repo / INDEX_REL).exists(), \
        "the migrator guessed a second home for the records"


def test_an_absolute_authorizations_dir_is_a_usage_error(tmp_path):
    repo = installed(make_repo(tmp_path))
    before = snapshot(repo)
    res = migrate(repo, "--authorizations-dir", "../outside")
    assert res.rc == 2, res.stdout + res.stderr
    assert snapshot(repo) == before


def test_the_new_flags_exist(tmp_path):
    res = run_python(SCRIPTS / "init_sync.py", ["--help"], cwd=REPO_ROOT)
    assert res.rc == 0, res.stdout + res.stderr
    assert "--migrate" in res.stdout, res.stdout
    assert "--authorizations-dir" in res.stdout, res.stdout


# ---------------------------------------------------------------------------
# fix round 1, guard 1: a guard that could not run is never "clean"
#
# `dirty_tracked_scripts()` and `staged_outside_ai()` answered a FAILED git
# command with `[]` — the same value as "checked, nothing found" — so the two
# states that exist to stop a destructive migration (an unstaged edit under
# `.ai/scripts/`, an index holding someone else's work) read as clean exactly
# when git refused to answer: dubious ownership, `index.lock` contention, a
# timeout. `None` is the not-known answer, and the caller turns it into a
# refusal.


def test_a_failed_git_probe_is_not_known_clean(tmp_path, monkeypatch):
    repo = installed(make_repo(tmp_path))
    lock_err = (b"fatal: Unable to create '/tmp/x/.git/index.lock':"
                b" File exists.")

    def subcommand_fails(root_, args, timeout=60):
        # The work tree answers; the guard's own command does not.
        if args[:2] == ["rev-parse", "--is-inside-work-tree"]:
            return ai_common.GitResult(0, b"true\n", b"", False)
        return ai_common.GitResult(128, b"", lock_err, False)

    monkeypatch.setattr(init_sync, "run_git", subcommand_fails)
    dirty, why_dirty = init_sync.dirty_tracked_scripts(repo)
    outside, why_outside = init_sync.staged_outside_ai(repo)
    assert dirty is None, "a failed `ls-files` read as 'nothing dirty'"
    assert outside is None, "a failed `diff --cached` read as 'index is clean'"
    assert "ls-files" in why_dirty and "index.lock" in why_dirty, why_dirty
    assert "diff --cached" in why_outside, why_outside

    def probe_refused(root_, args, timeout=60):
        return ai_common.GitResult(
            128, b"", b"fatal: detected dubious ownership in repository at "
            b"'//tsclient/x'", False)

    monkeypatch.setattr(init_sync, "run_git", probe_refused)
    assert init_sync.dirty_tracked_scripts(repo)[0] is None
    assert init_sync.staged_outside_ai(repo)[0] is None
    # §6: dubious ownership is its own actionable error, NOT the no-repository
    # bucket — so no `NO_HISTORY` stamp and no skipped writer lock.
    assert init_sync.git_head_state(repo)[0] == "probe-refused"

    def no_repository(root_, args, timeout=60):
        return ai_common.GitResult(
            128, b"", b"fatal: not a git repository (or any of the parent "
            b"directories): .git", False)

    monkeypatch.setattr(init_sync, "run_git", no_repository)
    # The confirmed non-repository is the ONE case where nothing is tracked, so
    # "clean" is a real answer rather than a guess.
    assert init_sync.git_head_state(repo)[0] == "no-repo"
    assert init_sync.dirty_tracked_scripts(repo) == ([], "")
    assert init_sync.staged_outside_ai(repo) == ([], "")


def test_a_git_that_cannot_answer_is_its_own_halt(tmp_path):
    """End to end: with no `git` to ask, `--migrate` stops — it does not guess.

    The empty PATH is the reachable instance of the same hole as a refused
    probe: `git_head_state()` used to answer `no-git` for "git is not on PATH",
    which is the bucket that skips the writer lock and permanently stamps
    `NO_HISTORY` into a tree that HAS history (and, because the stamp goes into
    the config that the next machine pulls, stamps it for every machine).
    """
    repo = installed(make_repo(tmp_path))
    before = snapshot(repo)
    cfg_before = (repo / CONFIG_REL).read_bytes()
    res = run_python(SCRIPTS / "init_sync.py", [str(repo), "--migrate"],
                     cwd=repo, env={"PATH": ""})
    assert res.rc == 2, res.stdout + res.stderr
    assert "Nothing was written" in res.stdout, res.lines
    assert "NO_HISTORY" not in res.stdout, res.lines
    assert "no-history" not in res.stdout, res.lines
    assert "PATH" in res.stdout, res.lines
    assert snapshot(repo) == before
    assert (repo / CONFIG_REL).read_bytes() == cfg_before
    assert not (repo / MIGRATION_REL).exists()


def test_a_bad_index_is_caught_before_the_commit_and_the_commit_is_scoped(
        tmp_path, monkeypatch):
    """Two halves of one guard: verify the staged set, THEN commit by path.

    The old order checked the created commit with `git show` — after the fact,
    at rc 0, with the bad index already in history.
    """
    repo = installed(make_repo(tmp_path / "staged"))
    (repo / "outside.py").write_text("staged by someone else\n",
                                     encoding="utf-8")
    git(repo, "add", "outside.py")
    calls: list = []
    real = init_sync.run_git

    def spy(root_, args, timeout=60):
        calls.append(list(args))
        return real(root_, args, timeout=timeout)

    monkeypatch.setattr(init_sync, "run_git", spy)
    head_before = git(repo, "rev-parse", "HEAD")
    count_before = int(git(repo, "rev-list", "--count", "HEAD"))
    ok, detail = init_sync._migration_commit(repo, "2.0.0")
    assert ok is False, detail
    assert "outside .ai/" in detail, detail
    assert not any(c and c[0] == "commit" for c in calls), calls
    assert any(c[:2] == ["diff", "--cached"] for c in calls), calls
    assert git(repo, "rev-parse", "HEAD") == head_before
    assert int(git(repo, "rev-list", "--count", "HEAD")) == count_before, \
        "a refused index still reached history"

    # The clean path: still verified before the commit, and the commit itself
    # cannot name anything outside `.ai/`.
    repo2 = installed(make_repo(tmp_path / "scoped"))
    (repo2 / ".ai/state/CURRENT.md").write_text("# written by the migration\n",
                                                encoding="utf-8")
    calls2: list = []

    def spy2(root_, args, timeout=60):
        calls2.append(list(args))
        return real(root_, args, timeout=timeout)

    monkeypatch.setattr(init_sync, "run_git", spy2)
    ok2, detail2 = init_sync._migration_commit(repo2, "2.0.0")
    assert ok2 is True, detail2
    commits = [i for i, c in enumerate(calls2) if c and c[0] == "commit"]
    assert len(commits) == 1, calls2
    argv = calls2[commits[0]]
    assert "--" in argv, argv
    assert ".ai" in argv[argv.index("--"):], argv
    verified = [i for i, c in enumerate(calls2) if c[:2] == ["diff", "--cached"]]
    assert verified and min(verified) < commits[0], calls2
    files = commit_files(repo2)
    assert files and all(f.startswith(".ai/") for f in files), files


# ---------------------------------------------------------------------------
# fix round 1, guard 2: a real 2.0.0 -> 2.1.0 step must re-run as a NO-OP


def test_a_real_cross_version_migrate_rereads_as_a_true_noop(tmp_path):
    """The fixture the idempotency rule actually needs: a REAL version step.

    Every other idempotency case here migrates a tree whose own stamp already
    reads 2.1.0, so `prior["from"] == installed` held by construction and never
    met the case that matters: after a genuine 2.0.0 -> 2.1.0 migration the
    record says `from: 2.0.0` while the install now says `2.1.0`, and the
    second run must VERIFY, not migrate a second time.

    The scripts here are the released v2.0 blobs with no `ai_common.py` beside
    them, which is what a real v2.0 install is: deleting `ai_common.py` from a
    2.1 install would not model 2.0.0, it would model a broken tree whose
    `checkpoint.py` cannot even take the writer lock.
    """
    repo = make_repo(tmp_path)
    assert scaffold(repo).rc == 0
    stamp = repo / ".ai/protocol/VERSION"
    stamp.write_text("2.0.0\n", encoding="utf-8")
    (repo / ".ai/scripts/ai_common.py").unlink()      # v2.0 never shipped one
    for name in ("checkpoint.py", "sync_verify.py"):
        (repo / ".ai/scripts" / name).write_bytes(
            git_blob("e692e73", "scripts/" + name))
    # the other half of the v2.0 hole: no canonical home for the records.
    (repo / INDEX_REL).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "v2.0.0 install")

    first = migrate(repo)
    assert first.rc == 0, first.stdout + first.stderr
    assert stamp.read_text("utf-8").strip() == init_sync.PROTOCOL_VERSION
    record_a = (repo / MIGRATION_REL).read_bytes()
    assert json.loads(record_a)["from"] == "2.0.0", record_a
    assert json.loads(record_a)["to"] == init_sync.PROTOCOL_VERSION, record_a
    cfg_a = (repo / CONFIG_REL).read_bytes()
    journal_a = (repo / JOURNAL_REL).read_bytes()
    head_a = git(repo, "rev-parse", "HEAD")
    count_a = int(git(repo, "rev-list", "--count", "HEAD"))
    files_a = snapshot(repo)
    assert json.loads(cfg_a.decode("utf-8"))["governance"][
        "window_start_commit"], "the first run recorded no window anchor"

    second = migrate(repo)
    assert second.rc == 0, second.stdout + second.stderr
    assert "already migrated" in second.stdout, second.lines
    assert "2.0.0" in second.stdout, second.lines
    assert not any(ln.startswith("wrote:") for ln in second.lines), second.lines
    assert (repo / MIGRATION_REL).read_bytes() == record_a
    assert (repo / CONFIG_REL).read_bytes() == cfg_a
    assert (repo / JOURNAL_REL).read_bytes() == journal_a
    assert git(repo, "rev-parse", "HEAD") == head_a
    assert int(git(repo, "rev-list", "--count", "HEAD")) == count_a, \
        "a second migration commit on an already-migrated tree"
    assert snapshot(repo) == files_a, "the re-run wrote a file"


# ---------------------------------------------------------------------------
# fix round 1, guard 3: a weak verify reads a forged anchor as 'done'


def test_verify_migration_accepts_only_a_real_anchor_or_the_sentinel(tmp_path):
    repo = installed(make_repo(tmp_path))
    assert migrate(repo).rc == 0
    cfg_path = repo / CONFIG_REL
    real = json.loads(cfg_path.read_text("utf-8"))["governance"][
        "window_start_commit"]
    assert re.fullmatch(r"[0-9a-f]{40}", real), real

    def verdict():
        kinds = {name: kind for kind, name, _d in init_sync.verify_migration(repo)}
        return kinds["window anchor"]

    assert verdict() == "PASS"
    # Anything that is not 40 LOWERCASE hex, and is not the exact sentinel, is
    # not an anchor: a short prefix, an upppercased id, a ref name, a padded
    # sentinel, an unset value. (`"0123…" * 4` is NOT in this list: 40 lowercase
    # hex is well-formed, and `verify_migration` cannot and must not judge
    # whether a real-looking id exists — that is `commit_exists`' job.)
    for forged in ("deadbeef", "deadbeef-deadbeef-deadbeef-deadbeef-01",
                   "A" * 40, "HEAD",
                   "NO_HISTORY ", " NO_HISTORY", "", real.upper(),
                   "0" * 39, "0" * 41):
        cfg = json.loads(cfg_path.read_text("utf-8"))
        cfg["governance"]["window_start_commit"] = forged
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        assert verdict() == "FAIL", f"{forged!r} read as a completed migration"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["governance"]["window_start_commit"] = "NO_HISTORY"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    assert verdict() == "PASS"


# ---------------------------------------------------------------------------
# fix round 1, minors: the degradation must survive the console


def test_a_sidecar_divergence_is_recorded_not_just_printed(tmp_path):
    """`warnings[]` + `degraded` in MIGRATION.json.

    A preserved customised script exits 0 (the migration itself completed), so
    the ONLY way a caller that reads the exit code — a hook, a wrapper — learns
    this install still runs an old script is the record saying so.
    """
    repo = installed(make_repo(tmp_path))
    target = repo / ".ai/scripts/checkpoint.py"
    target.write_bytes(target.read_bytes() + b"\n# local customisation\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "customised the writer")

    res = migrate(repo)
    assert res.rc == 0, res.stdout + res.stderr
    record = json.loads((repo / MIGRATION_REL).read_text("utf-8"))
    assert record["degraded"] is True, record
    assert any(".ai/scripts/checkpoint.py" in w and ".new" in w
               for w in record["warnings"]), record
    assert (repo / ".ai/scripts/checkpoint.py.new").is_file()
    # and the verifying re-run still says so out loud rather than going quiet
    again = migrate(repo)
    assert any(ln.startswith("[WARN] migrate verify") and ".new" in ln
               for ln in again.lines), again.lines


def test_the_record_names_a_commit_that_did_not_land(tmp_path, monkeypatch):
    """A failed commit is a degradation the record carries, not a printout."""
    repo = installed(make_repo(tmp_path))
    monkeypatch.setattr(
        init_sync, "_migration_commit",
        lambda root, installed_: (False, "simulated: `git commit` exited 128"))
    rc = init_sync.run_migration(repo, argparse.Namespace(
        authorizations_dir=None))
    assert rc == 0, rc
    record = json.loads((repo / MIGRATION_REL).read_text("utf-8"))
    assert record["degraded"] is True, record
    assert any("commit" in w and "simulated" in w for w in record["warnings"]), \
        record
    # the journal is the other half of the record: it names the same failure
    journal = (repo / JOURNAL_REL).read_text("utf-8")
    assert "simulated" in journal, journal


# ---------------------------------------------------------------------------
# fix round 1, minors: the text editor's own edges (it had only end-to-end
# coverage, which cannot reach an escaped key or a non-object parent)


def test_splice_json_handles_an_escaped_quote_key():
    text = ('{\n  "say \\"hi\\"": 1,\n  "governance": {\n'
            '    "window_start_commit": ""\n  }\n}\n')
    out = init_sync._splice_json(text, [(("say \"hi\"",), "2")])
    assert out != text
    assert json.loads(out) == {"say \"hi\"": 2,
                               "governance": {"window_start_commit": ""}}, out
    # the key's own bytes survived: the edit is a splice, not a re-dump
    assert '"say \\"hi\\""' in out, out
    assert "window_start_commit" in out, out


def test_splice_json_refuses_a_parent_segment_that_is_not_an_object():
    arr = '{\n  "governance": [\n    "window_start_commit"\n  ]\n}\n'
    edits = [(("governance", "window_start_commit"), '"deadbeef"')]
    assert init_sync._splice_json(arr, edits) == arr, \
        "a member was stuffed into a key whose value is an ARRAY"
    # and a wholly absent parent is not invented by the splice either
    flat = '{\n  "budgets": {\n    "CURRENT.md": 60\n  }\n}\n'
    assert init_sync._splice_json(
        flat, [(("governance", "window_start_commit"), '"x"')]) == flat
