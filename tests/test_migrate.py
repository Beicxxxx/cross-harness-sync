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
    assert set(record) == {"from", "to", "started", "completed",
                           "files_touched"}, record
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
