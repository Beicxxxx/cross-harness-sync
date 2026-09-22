"""Wave 1e void queue: Q8 / Q11 / Q12 / Q15.

Red-first pins for the four implementable defects left open in
`docs/evidence/wave1d-queue.md`. Each case names the defect it closes.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from helpers import SCRIPTS, git, load_module, run_python

# ---------------------------------------------------------------------------
# load shipped scripts under private names (do not poison sys.modules)

sync_verify = load_module("_lane_1e_sync_verify", SCRIPTS / "sync_verify.py")
ai_common = load_module("_lane_1e_ai_common", SCRIPTS / "ai_common.py")
init_sync = load_module("_lane_1e_init_sync", SCRIPTS / "init_sync.py")

def run(repo):
    return run_python(repo / ".ai" / "scripts" / "sync_verify.py", [], cwd=repo)


def line(res, prefix):
    return next((ln for ln in res.lines if ln.startswith(prefix)), None)


def _set_cfg(repo, **keys):
    cfg_path = repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg.update(keys)
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def promote(repo):
    (repo / "scripts").mkdir(exist_ok=True)
    for name in ("ai_common.py", "checkpoint.py", "sync_verify.py"):
        src = repo / ".ai" / "scripts" / name
        if src.is_file():
            shutil.copy2(str(src), str(repo / "scripts" / name))
    (repo / "scripts" / "init_sync.py").write_text("# installer\n",
                                                   encoding="utf-8")


# ---------------------------------------------------------------------------
# Q8 — diverged sidecar


def test_q8_a_py_new_sidecar_fails_governing_copy_before_skip(ai_repo):
    """OLD installed script still runs while a .py.new waits -- named FAIL.

    Folded into governing copy (no new check count). Answered even on an
    ordinary install that would otherwise SKIP(not-source-checkout).
    """
    side = ai_repo / ".ai" / "scripts" / "sync_verify.py.new"
    side.write_text("# shipped bytes waiting\n", encoding="utf-8")
    res = run(ai_repo)
    found = line(res, "[FAIL] governing copy:")
    assert found, res.lines
    assert "sidecar" in found.lower() or ".py.new" in found, found
    assert "sync_verify.py.new" in found, found
    assert "OLD" in found or "old" in found, found
    assert line(res, "[SKIP] governing copy:") is None, res.lines


def test_q8_sidecar_also_fails_on_a_source_checkout(ai_repo):
    promote(ai_repo)
    side = ai_repo / ".ai" / "scripts" / "checkpoint.py.new"
    side.write_text("# waiting\n", encoding="utf-8")
    res = run(ai_repo)
    found = line(res, "[FAIL] governing copy:")
    assert found and "checkpoint.py.new" in found, res.lines


# ---------------------------------------------------------------------------
# Q11 — typo / empty release_paths


def test_q11_unknown_config_key_is_a_config_error():
    with pytest.raises(sync_verify.ConfigError) as exc:
        sync_verify.merge_config(sync_verify.DEFAULT_CONFIG,
                                 {"release_path": ["scripts/*"]})
    msg = str(exc.value)
    assert msg.startswith("malformed: unknown config key"), msg
    assert "release_path" in msg, msg


def test_q11_absent_release_paths_still_skips(ai_repo):
    """Fresh template omits the key; that is SKIP(no-release-paths), not FAIL."""
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    assert "release_paths" not in cfg, cfg
    res = run(ai_repo)
    skip = line(res, "[SKIP] release authorization:")
    assert skip and "no-release-paths" in skip, res.lines
    assert line(res, "[FAIL] release authorization:") is None, res.lines


def test_q11_present_empty_release_paths_fails(ai_repo):
    """A declared empty face is FAIL whether or not a window is set."""
    _set_cfg(ai_repo, release_paths=[])
    res = run(ai_repo)
    found = line(res, "[FAIL] release authorization:")
    assert found and "empty" in found, res.lines
    assert line(res, "[SKIP] release authorization:") is None, res.lines


def test_q11_present_empty_with_window_names_the_window(ai_repo):
    head = git(ai_repo, "rev-parse", "HEAD").strip()
    _set_cfg(ai_repo, release_paths=[], release_window_start_commit=head)
    res = run(ai_repo)
    found = line(res, "[FAIL] release authorization:")
    assert found and "empty" in found, res.lines
    assert head[:8] in found, found


# ---------------------------------------------------------------------------
# Q12 — authorizations_dir resolves checkout-root only


def test_q12_resolve_authorizations_dir_empty_uses_ai_subdir(tmp_path):
    root = tmp_path / "repo"
    ai = root / ".ai"
    ai.mkdir(parents=True)
    got = ai_common.resolve_authorizations_dir(root, ai, {})
    assert got == ai / ai_common.AUTHORIZATIONS_SUBDIR


def test_q12_relative_authorizations_dir_is_root_only_not_under_ai(tmp_path):
    """`state/authorizations` must NOT also probe `.ai/state/authorizations`."""
    root = tmp_path / "repo"
    ai = root / ".ai"
    under_ai = ai / "state" / "authorizations"
    under_root = root / "state" / "authorizations"
    under_ai.mkdir(parents=True)
    under_root.mkdir(parents=True)
    (under_ai / "only-ai.md").write_text("# ai\n", encoding="utf-8")
    (under_root / "only-root.md").write_text("# root\n", encoding="utf-8")
    got = ai_common.resolve_authorizations_dir(
        root, ai, {"authorizations_dir": "state/authorizations"})
    assert got == under_root, got
    assert got != under_ai, got
    names = {p.name for p in ai_common.authorization_records(got)}
    assert names == {"only-root.md"}, names


def test_q12_sync_verify_and_checkpoint_share_one_resolver():
    """Both shipped readers import the same resolve_authorizations_dir helper."""
    cp_src = (SCRIPTS / "checkpoint.py").read_text("utf-8")
    sv_src = (SCRIPTS / "sync_verify.py").read_text("utf-8")
    assert "resolve_authorizations_dir" in cp_src
    assert "resolve_authorizations_dir" in sv_src
    assert "AI_DIR / cand" not in cp_src
    assert "for probe in" not in cp_src


# ---------------------------------------------------------------------------
# Q15 — empty git show listing


def test_q15_empty_post_commit_listing_names_the_recheck_it_skipped(
        tmp_path, monkeypatch):
    from helpers import make_repo, scaffold

    repo = make_repo(tmp_path)
    assert scaffold(repo).rc == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "install")
    (repo / ".ai" / "state" / "CURRENT.md").write_text(
        "# written by the migration\n", encoding="utf-8")
    real = init_sync.run_git

    def empty_ok_show(root_, args, timeout=60):
        if args and args[0] == "show":
            return ai_common.GitResult(rc=0, stdout=b"", stderr=b"",
                                       timed_out=False)
        return real(root_, args, timeout=timeout)

    monkeypatch.setattr(init_sync, "run_git", empty_ok_show)
    ok, detail = init_sync._migration_commit(repo, "2.0.0")
    assert ok is True, detail
    assert "recheck did not run" in detail, detail
    assert "wrote nothing" in detail or "listing" in detail, detail
    assert "0 path(s) committed" not in detail, detail
    monkeypatch.setattr(init_sync, "run_git", real)
