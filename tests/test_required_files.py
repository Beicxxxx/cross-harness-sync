"""Task 3 (D23): one config-backed required-file list, and it stays honest.

Three copies had drifted apart — `sync_verify.REQUIRED_FILES`,
`checkpoint.cmd_validate`'s local list, and `cmd_status`'s inline names — and
none of them required `ROLE_POLICY.md`, so the governance document could simply
be absent. This commit makes `sync_verify` read ONE list from config, and puts
the default in `ai_common.DEFAULT_REQUIRED_FILES` so `checkpoint.py` and
`init_sync.py` import the same object instead of copying it (their halves are
the checkpoint and init lanes').

Two properties the list has to keep, both pinned here:

  * every entry is something the installer actually writes. That is why
    `.ai/state/authorizations/INDEX.md` is NOT in the 1a list: nothing populates
    it until wave 1b, so requiring it now would make every fresh install red for
    a reason no 1a file can answer.
  * it is overridable by replace, so a repo with no decision log can say so —
    the mirror of `secret_files`, which is a floor and unions.

The cross-view agreement test the wave-1a brief sketched
(`sv` vs `checkpoint --validate` vs `--status`) is deliberately not here: it
asserts on `checkpoint.py`'s output, a file this lane must not touch while its
lane is rewriting those two functions.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from helpers import SCRIPTS, TEMPLATES_DIR, run_python

_CONFIG_REL = ".ai/sync_config.json"


def _load(module_name: str, path: Path):
    saved = sys.modules.pop("ai_common", None)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop("ai_common", None)
        if saved is not None:
            sys.modules["ai_common"] = saved


ai_common = _load("_ai_common_under_test_required_files", SCRIPTS / "ai_common.py")
sync_verify = _load("_sync_verify_under_test_required_files",
                    SCRIPTS / "sync_verify.py")


def required_names(res) -> list[str]:
    """The file names this run actually reported on, from its own lines."""
    return [ln.split("] required ", 1)[1].split(":")[0]
            for ln in res.lines
            if ln.startswith(("[PASS] required ", "[FAIL] required "))]


def set_cfg(repo: Path, key: str, value) -> None:
    path = repo / _CONFIG_REL
    cfg = json.loads(path.read_text("utf-8"))
    cfg[key] = value
    path.write_text(json.dumps(cfg), encoding="utf-8")


# --------------------------------------------------------------------------
# one list, three spellings of it


def test_code_default_and_shipped_template_carry_the_same_list():
    """The drift this task ends was three copies disagreeing; a fourth, in the
    template every install starts from, has to say the same thing."""
    from_template = json.loads(
        (TEMPLATES_DIR / "sync_config.json").read_text("utf-8"))["required_files"]
    assert ai_common.DEFAULT_REQUIRED_FILES == from_template, from_template
    assert sync_verify.DEFAULT_CONFIG["required_files"] == \
        ai_common.DEFAULT_REQUIRED_FILES, sync_verify.DEFAULT_CONFIG
    assert "REQUIRED_FILES" not in vars(sync_verify), \
        "sync_verify kept its own copy of the list"


def test_the_list_names_the_governance_files_and_nothing_unwritten():
    assert ".ai/state/ROLE_POLICY.md" in ai_common.DEFAULT_REQUIRED_FILES
    assert ".ai/state/CURRENT.md" in ai_common.DEFAULT_REQUIRED_FILES
    assert ".ai/protocol/VERSION" in ai_common.DEFAULT_REQUIRED_FILES
    # wave 1b populates this; requiring it in 1a makes every fresh install red
    assert not any("authorizations" in rel
                   for rel in ai_common.DEFAULT_REQUIRED_FILES), \
        ai_common.DEFAULT_REQUIRED_FILES


def test_every_required_file_is_one_a_fresh_install_has(ai_repo):
    """A required file nothing creates is a permanently red install, which is
    the mistake this list's shape is easy to make."""
    for rel in ai_common.DEFAULT_REQUIRED_FILES:
        path = ai_repo / Path(rel)
        assert path.is_file(), (rel, "not created by init_sync.py")
        assert path.stat().st_size > 0, (rel, "created empty")


# --------------------------------------------------------------------------
# through the CLI


def test_role_policy_is_required(ai_repo, sv):
    """v2.0 copied ROLE_POLICY.md in but never required it, so the governance
    document could simply be absent. Spec section 6 item 2."""
    (ai_repo / ".ai" / "state" / "ROLE_POLICY.md").unlink()
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert "[FAIL] required .ai/state/ROLE_POLICY.md: missing" in res.lines, res.lines
    assert "FAILED: required .ai/state/ROLE_POLICY.md" in res.lines, res.lines


def test_dropping_a_state_file_is_caught(ai_repo, sv):
    (ai_repo / ".ai" / "state" / "BLOCKERS.md").unlink()
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "[FAIL] required .ai/state/BLOCKERS.md: missing" in res.lines, res.lines


def test_an_empty_required_file_is_as_bad_as_a_missing_one(ai_repo, sv):
    (ai_repo / ".ai" / "state" / "TASK.md").write_text("", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "[FAIL] required .ai/state/TASK.md: empty" in res.lines, res.lines


def test_a_fresh_install_reports_exactly_the_shared_list(ai_repo, sv):
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert required_names(res) == list(ai_common.DEFAULT_REQUIRED_FILES), res.lines


def test_required_files_is_config_overridable_by_replace(ai_repo, sv):
    """A repo that keeps no decision log must be able to say so — and the
    override must really REPLACE, not add to the floor it was merged over.

    VERSION is the file to drop with: no budget and no mirror check mentions
    it, so the only way it can go red is the required-file list itself. A union
    merge would still report `[FAIL] required .ai/protocol/VERSION: missing`.
    """
    set_cfg(ai_repo, "required_files", [".ai/state/CURRENT.md"])
    (ai_repo / ".ai" / "protocol" / "VERSION").unlink()
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert required_names(res) == [".ai/state/CURRENT.md"], res.lines
