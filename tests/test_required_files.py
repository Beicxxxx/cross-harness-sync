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
  * config may add entries and may drop the OPTIONAL TAIL (a repo with no
    decision log can say so), but it cannot un-check the five files nothing else
    covers: `sync_verify.REQUIRED_FILE_FLOOR` is unioned back in after the
    merge and is not configurable.

The floor is lane S1's correction of finding 2, and it corrected a test in this
file rather than only adding one: `test_required_files_is_config_overridable_by_
replace` used to assert that `{"required_files": [".ai/state/CURRENT.md"]}` with
`protocol/VERSION` deleted exits 0 — i.e. it *demonstrated* the one-line
un-check as intended behaviour. See
`test_required_files_override_replaces_only_the_optional_tail`.

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


def budget_names(res) -> set[str]:
    """The files whose line cap this run monitored, read off its own lines."""
    return {ln.split("] budget ", 1)[1].split(":")[0]
            for ln in res.lines
            if ln.startswith(("[PASS] budget ", "[FAIL] budget "))}


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
    # wave 1b flipped this pin: the authorization index IS required now, because
    # the same commit that requires it also ships the template and installs it
    # (`FILE_MAP` in init_sync.py), so no install can be red for wanting a file
    # nothing writes. `templates/authorizations/INDEX.md` is the proof of the
    # other half; `test_authorization_records.py` pins that a fresh install gets
    # the file.
    assert ".ai/state/authorizations/INDEX.md" in \
        ai_common.DEFAULT_REQUIRED_FILES, ai_common.DEFAULT_REQUIRED_FILES


def test_the_floor_is_a_named_subset_of_the_shared_list():
    """The floor cannot ask for a file the shared default does not carry, or a
    fresh install would report lines the config never listed; and it must hold
    the two files the review found nothing else checking."""
    floor = sync_verify.REQUIRED_FILE_FLOOR
    assert set(floor) <= set(ai_common.DEFAULT_REQUIRED_FILES), floor
    assert ".ai/state/ROLE_POLICY.md" in floor, floor
    assert ".ai/protocol/VERSION" in floor, floor
    assert ".ai/state/CURRENT.md" in floor and ".ai/state/TASK.md" in floor \
        and ".ai/state/BLOCKERS.md" in floor, floor
    # the optional tail stays optional: a repo with no decision log may say so
    assert ".ai/state/DECISIONS.md" not in floor, floor
    assert ".ai/state/DECISIONS_INDEX.md" not in floor, floor
    assert ".ai/handoff/LATEST.md" not in floor, floor


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


def test_a_fresh_install_monitors_agents_md(ai_repo, sv):
    """Finding 5's missing pin: AGENTS.md is the most-loaded auto-loaded
    instruction file, its cap is installer-owned (D18/D27) and it is in no
    required-file list, so the budget line is the ONLY thing watching it.
    Nothing used to assert that a plain run monitored it at all."""
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert "AGENTS.md" in budget_names(res), res.lines
    assert any(ln.startswith("[PASS] budget AGENTS.md") for ln in res.lines), res.lines


def test_required_files_override_replaces_only_the_optional_tail(ai_repo, sv):
    """The override must really REPLACE — the optional tail only.

    This replaces `test_required_files_is_config_overridable_by_replace`, which
    asserted `rc == 0` here and so pinned finding 2 as intended behaviour: one
    config line dropped the only check on ROLE_POLICY.md and protocol/VERSION.
    A correction of a pin, not a regression — VERSION has no budget, no mirror
    and no other necessity check anywhere in the install, so a union merge is
    the only thing that can still see it go missing.
    """
    set_cfg(ai_repo, "required_files", [".ai/state/CURRENT.md"])
    (ai_repo / ".ai" / "protocol" / "VERSION").unlink()
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "[FAIL] required .ai/protocol/VERSION: missing" in res.lines, res.lines
    # Lane S2 finding 8: the floor line is a TRACE, not a check -- a PASS booked
    # the config "attempted to narrow coverage". The restored files are counted
    # by their own `required ...` lines below it, which is why the SKIP stays
    # evidence-bearing.
    assert any(ln.startswith("[SKIP] required-file floor:")
               and ".ai/protocol/VERSION" in ln
               and "config listed 1 entries" in ln for ln in res.lines), res.lines
    # the tail the repo legitimately has no use for really did go
    assert required_names(res) == [".ai/state/CURRENT.md", ".ai/state/TASK.md",
                                   ".ai/state/BLOCKERS.md",
                                   ".ai/state/ROLE_POLICY.md",
                                   ".ai/protocol/VERSION"], res.lines


def test_a_config_declaring_zero_required_files_is_named_not_green(ai_repo, sv):
    """Finding 1: an empty list used to record nothing and print `8/8 passed`.
    Interim answer is a FAIL with an evidence line naming the emptiness, not a
    SKIP, because `record()` speaks only PASS/FAIL — see the boundary comment in
    `check_required_files`. The floor is checked either way."""
    set_cfg(ai_repo, "required_files", [])
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[FAIL] required-file list:")
               and "zero required_files" in ln for ln in res.lines), res.lines
    assert "FAILED: required-file list" in res.lines, res.lines
    assert required_names(res) == list(sync_verify.REQUIRED_FILE_FLOOR), res.lines


def test_config_may_still_add_requirements(ai_repo, sv):
    """The floor is a floor, not a ceiling: a project can name its own files."""
    (ai_repo / ".freeze").write_text("pinned\n", encoding="utf-8")
    set_cfg(ai_repo, "required_files",
            list(ai_common.DEFAULT_REQUIRED_FILES) + [".freeze"])
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert any(ln.startswith("[PASS] required .freeze:") for ln in res.lines), res.lines
    assert "FAILED:" not in " ".join(res.lines), res.lines
    assert not any(ln.startswith("[PASS] required-file floor:")
                   for ln in res.lines), res.lines
