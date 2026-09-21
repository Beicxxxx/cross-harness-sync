"""Task 2 (D4) + Task 1 review findings D and E: a config or child-stream
problem must be a named failure, never a default and never a quiet line.

Three shapes are pinned here, all of them the same defect wearing different
clothes:

  * An unreadable config used to print a bare `WARNING:` line and exit 0 with
    built-in defaults, so the checker certified a repository whose config it
    had not read (D4). It is now a `[FAIL] config readable` check that stops
    the run with its own `0/1` summary.
  * `check_extra` computed `res.timed_out` and threw it away, printing
    `rc=-1; (no output)` for a command it never managed to finish. The
    degradation has to name the command and the reason (finding D).
  * The import-time refusal in `sync_verify.py` contained an em dash, so under
    an ASCII stdout it died with `UnicodeEncodeError` — rc 1 and an EMPTY
    stdout, i.e. the message the user needed was the one thing that never
    reached them (finding E, this script's half; `checkpoint.py`'s twin is
    pinned by an xfail in `tests/test_ai_common.py`).

Lane S1 added the fourth and fifth members of the same family: a config key
whose ELEMENT shape was never checked (`secret_mirrors`, `extra_checks`,
`decisions_file`, `decisions_max_active_entries`) escaped as an
IndexError/KeyError/TypeError traceback rather than a `malformed:` line, and a
cap that disappeared while its file stayed present produced no line at all.
Every case below therefore asserts both halves: the named line AND the absence
of a traceback.

No assertion below is satisfied by empty output: each one names a line.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from helpers import SCRIPTS, run_python

_CONFIG_REL = ".ai/sync_config.json"


def _load_sync_verify():
    saved = sys.modules.pop("ai_common", None)
    name = "_sync_verify_under_test_config_errors"
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / "sync_verify.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.modules.pop(name, None)
        sys.modules.pop("ai_common", None)
        if saved is not None:
            sys.modules["ai_common"] = saved


sync_verify = _load_sync_verify()


def write_raw(repo: Path, text: str, encoding: str = "utf-8") -> None:
    (repo / _CONFIG_REL).write_text(text, encoding=encoding)


def patch_cfg(repo: Path, **key_value) -> None:
    """Change named keys of the SHIPPED config, leaving the rest alone."""
    path = repo / _CONFIG_REL
    cfg = json.loads(path.read_text("utf-8"))
    cfg.update(key_value)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def readable_failures(res) -> list[str]:
    return [ln for ln in res.lines if ln.startswith("[FAIL] config readable")]


# --------------------------------------------------------------------------
# D4: a config that cannot be read is a failure, with its own reason


def test_malformed_json_is_a_failure_not_a_default(ai_repo, sv):
    write_raw(ai_repo, '{"budgets": ')
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert readable_failures(res), res.lines
    assert "malformed:" in readable_failures(res)[0], res.lines
    assert "sync_config.json" in readable_failures(res)[0], res.lines
    assert "WARNING: cannot read" not in res.stdout, res.lines


def test_missing_config_is_a_failure(ai_repo, sv):
    (ai_repo / _CONFIG_REL).unlink()
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert readable_failures(res), res.lines
    assert "unreadable:" in readable_failures(res)[0], res.lines


def test_top_level_array_is_rejected(ai_repo, sv):
    write_raw(ai_repo, "[]")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert readable_failures(res), res.lines
    assert "not-object:" in readable_failures(res)[0], res.lines


def test_a_config_failure_stops_the_run_and_says_zero_of_one(ai_repo, sv):
    """An unreadable config must not print a confident-looking report either."""
    write_raw(ai_repo, "not json at all")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert res.stdout_raw, "verifier exited without writing any output"
    assert "== 0/1 checks passed ==" in res.lines, res.lines
    assert "FAILED: config readable" in res.lines, res.lines
    assert not any(ln.startswith("[PASS]") for ln in res.lines), res.lines


def test_a_readable_config_is_itself_a_passing_check(ai_repo, sv):
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert f"[PASS] config readable: {_CONFIG_REL}" in res.lines, res.lines


def test_a_bom_before_the_brace_is_still_our_config(ai_repo, sv):
    """init_sync writes plain UTF-8; an editor on Windows adds a BOM, and a
    reader that is not `utf-8-sig` calls the file malformed."""
    write_raw(ai_repo, '{"budgets": {".ai/state/CURRENT.md": 60}}', "utf-8-sig")
    res = run_python(sv, cwd=ai_repo)
    assert not readable_failures(res), res.lines
    assert f"[PASS] config readable: {_CONFIG_REL}" in res.lines, res.lines


@pytest.mark.parametrize("bad,expected_key", [
    ('{"secret_files": ".env"}', "secret_files"),
    ('{"budgets": []}', "budgets"),
    ('{"required_files": ".ai/state/CURRENT.md"}', "required_files"),
    ('{"budgets": {"AGENTS.md": "65"}}', "budgets"),
    ('{"secret_files": [".env", 7]}', "secret_files"),
    # lane S1 finding 3: two scalar keys reached the checks unvalidated
    ('{"decisions_file": null}', "decisions_file"),
    ('{"decisions_file": ["a.md"]}', "decisions_file"),
    ('{"decisions_max_active_entries": "20"}', "decisions_max_active_entries"),
    ('{"decisions_max_active_entries": true}', "decisions_max_active_entries"),
    ('{"decisions_max_active_entries": 0}', "decisions_max_active_entries"),
    # lane S1 finding 4: the element shapes one key over from D19's fix
    ('{"secret_mirrors": [".env", ".claude/.env"]}', "secret_mirrors"),
    ('{"secret_mirrors": [["a"]]}', "secret_mirrors"),
    ('{"secret_mirrors": [[".env", 7]]}', "secret_mirrors"),
    ('{"extra_checks": [{"name": "x"}]}', "extra_checks"),
    ('{"extra_checks": ["x"]}', "extra_checks"),
    ('{"extra_checks": [{"name": "x", "cmd": "git status"}]}', "extra_checks"),
    ('{"extra_checks": [{"name": "x", "cmd": []}]}', "extra_checks"),
])
def test_a_governed_key_of_the_wrong_shape_is_named_not_guessed(
        ai_repo, sv, bad, expected_key):
    """`{"secret_files": ".env"}` used to iterate the four CHARACTERS of a
    string: the floor was silently gone and the run printed nonsense instead.
    The cases lane S1 added were worse than nonsense — they left the run as a
    traceback (`IndexError: list index out of range`, `KeyError: 'cmd'`,
    `TypeError: string indices must be integers`, `TypeError: unsupported
    operand type(s) for /: 'WindowsPath' and 'NoneType'`)."""
    write_raw(ai_repo, bad)
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert readable_failures(res), res.lines
    assert "malformed:" in readable_failures(res)[0], res.lines
    assert expected_key in readable_failures(res)[0], res.lines
    assert "Traceback" not in res.stderr, res.stderr + res.stdout


def test_a_flat_secret_mirrors_list_cannot_report_on_characters(ai_repo, sv):
    """The specific nonsense this closed: `[[".env", 7]]`-shaped mistakes aside,
    `[.env, .claude/.env]` used to run and print `secret mirror . vs e`."""
    write_raw(ai_repo, '{"secret_mirrors": [".env", ".claude/.env"], '
                       '"budgets": {"AGENTS.md": 65}}')
    res = run_python(sv, cwd=ai_repo)
    assert not any(" vs " in ln for ln in res.lines), res.lines
    assert readable_failures(res), res.lines


def test_load_config_raises_a_typed_error_for_each_reason(tmp_path):
    """The three prefixes are the contract later lanes parse; they must come
    from `load_config()`, not only from the printed line. The path is an
    argument now (finding 7), so no test has to monkey-assign a module global
    and leave a stale `None` behind for the next one."""
    missing = tmp_path / ".ai"
    (missing / "sub").mkdir(parents=True)
    cfg_path = missing / "sync_config.json"
    cases = [(None, "unreadable:"), ('{"budgets": ', "malformed:"),
             ("[]", "not-object:"), ('{"budgets": []}', "malformed:"),
             ('{"secret_files": ".env"}', "malformed:"),
             ('{"budgets": {"a": "60"}}', "malformed:")]
    for text, prefix in cases:
        if text is None:
            cfg_path.unlink(missing_ok=True)
        else:
            cfg_path.write_text(text, encoding="utf-8")
        with pytest.raises(sync_verify.ConfigError) as excinfo:
            sync_verify.load_config(cfg_path)
        assert str(excinfo.value).startswith(prefix), (prefix, excinfo.value)


def test_a_config_path_that_was_never_given_is_a_named_error():
    """The stale-`None` half of finding 7 used to escape as
    `AttributeError: 'NoneType' object has no attribute 'read_bytes'`."""
    saved = sync_verify.CONFIG_PATH
    sync_verify.CONFIG_PATH = None
    try:
        with pytest.raises(sync_verify.ConfigError) as excinfo:
            sync_verify.load_config()
        assert str(excinfo.value).startswith("unreadable:"), excinfo.value
    finally:
        sync_verify.CONFIG_PATH = saved


def test_load_config_merges_instead_of_replacing_defaults(tmp_path):
    ai = tmp_path / ".ai"
    ai.mkdir()
    (ai / "sync_config.json").write_text(
        json.dumps({"budgets": {".ai/state/CURRENT.md": 10,
                                ".ai/handoff/NEXT_PROMPT.md": None}}),
        encoding="utf-8")
    cfg, nulled = sync_verify.load_config(ai / "sync_config.json")
    assert cfg["budgets"][".ai/handoff/LATEST.md"] == 80, cfg["budgets"]
    assert cfg["budgets"][".ai/state/CURRENT.md"] == 10, cfg["budgets"]
    assert "AGENTS.md" not in cfg["budgets"], cfg["budgets"]
    assert ".ai/handoff/NEXT_PROMPT.md" not in cfg["budgets"], cfg["budgets"]
    # the declined default travels out as a name, not as a missing key
    assert nulled == {".ai/handoff/NEXT_PROMPT.md"}, nulled
    assert cfg["secret_files"] == [".env"], cfg


# --------------------------------------------------------------------------
# lane S1 finding 3: the decision cap cannot be retargeted into silence


def test_a_retargeted_decisions_file_is_a_named_failure(ai_repo, sv):
    """`if dec.exists():` with no else used to mean one config line removed the
    decision-cap check while `required …DECISIONS.md` still PASSed. The answer
    is a FAIL today and a named SKIP once Task 7's tri-state `record()` lands."""
    patch_cfg(ai_repo, decisions_file=".ai/state/NOTHERE.md")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[FAIL] budget DECISIONS active entries")
               and "not present at .ai/state/NOTHERE.md" in ln
               for ln in res.lines), res.lines
    assert not any(ln.startswith("[PASS] budget DECISIONS") for ln in res.lines)
    assert "Traceback" not in res.stderr, res.stderr


def test_a_directory_or_unreadable_decisions_file_does_not_crash_the_run(
        ai_repo, sv):
    """`{"decisions_file": ""}` names ROOT itself, which EXISTS and is not a
    file: the reader must call that out rather than die on read_text."""
    patch_cfg(ai_repo, decisions_file=".ai/state")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[FAIL] budget DECISIONS active entries")
               for ln in res.lines), res.lines
    assert "Traceback" not in res.stderr, res.stderr


# --------------------------------------------------------------------------
# lane S1 finding 5: a budget that vanishes cannot leave the run green


def test_a_present_file_with_no_cap_and_no_explicit_null_is_named(ai_repo, sv):
    """Delete one line from `templates/sync_config.json`, or `--force`-skip the
    config on an upgrade, and AGENTS.md used to end up uncapped, unrequired and
    green. This is the shape the D18/D27 ownership argument was always about."""
    write_raw(ai_repo, '{"budgets": {".ai/state/CURRENT.md": 60}}')
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[FAIL] budget AGENTS.md")
               and "file present, no cap in config" in ln
               and "no explicit null" in ln for ln in res.lines), res.lines


def test_an_explicit_null_cap_leaves_a_trace(ai_repo, sv):
    """The considered act stays allowed -- and it says so as a SKIP.

    Lane S2 finding 1: this line used to record `True`, so a declined cap sat in
    the passed numerator. `test_a_run_that_declines_every_cap_leaves_only_skip_traces`
    below is the exploit that conversion closes.
    """
    cfg = json.loads((ai_repo / _CONFIG_REL).read_text("utf-8"))
    cfg["budgets"]["AGENTS.md"] = None
    (ai_repo / _CONFIG_REL).write_text(json.dumps(cfg), "utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert any(ln.startswith("[SKIP] cap opt-out AGENTS.md")
               and "explicit null" in ln for ln in res.lines), res.lines
    assert not any(ln.startswith("[PASS] cap opt-out AGENTS.md")
                   for ln in res.lines), res.lines
    assert not any(ln.startswith("[FAIL] budget AGENTS.md")
                   for ln in res.lines), res.lines
    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1 and "skipped" in summary[0], res.lines


# --------------------------------------------------------------------------
# D20: the secret reader must not treat a BOM as part of a key name


def test_a_bom_does_not_make_two_secret_files_disagree(ai_repo, sv):
    cfg = json.loads((ai_repo / _CONFIG_REL).read_text("utf-8"))
    cfg["secret_mirrors"] = [[".env", ".claude/.env"]]
    (ai_repo / _CONFIG_REL).write_text(json.dumps(cfg), "utf-8")
    (ai_repo / ".env").write_text("A=1\nB=2\n", encoding="utf-8")
    claude = ai_repo / ".claude"
    claude.mkdir()
    (claude / ".env").write_text("A=1\nB=2\n", encoding="utf-8-sig")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert any(ln.startswith("[PASS] secret mirror .env vs .claude/.env")
               for ln in res.lines), res.lines


# --------------------------------------------------------------------------
# finding D: check_extra must name the command and the reason, never just rc=-1
#
# Honesty note (lane S2, r1 finding 9): the three tests below are REGRESSION
# PINS for an EARLIER lane's fix, not red-before-green pins for this one. The
# `cmd ` prefix they assert was already printed at this wave's base `1ab2dc4`
# (r1-review-report.md finding 9 walks the base source), and the `rc=0; freeze
# verified` string S1's report quoted as its pre-fix comparison is a written
# comparison, not an executed run: the base never emitted it. They stay because
# a pin that outlives its lane is still a pin; they are labelled for what they
# are.


def _evidence_lines(capfd) -> list[str]:
    out = capfd.readouterr().out
    return [ln for ln in out.splitlines() if ln.strip()]


def _run_extra(monkeypatch, tmp_path, result_argv, timeout=None):
    mod = _load_sync_verify()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    # Lane S2 finding 7: the timeout is a config key with no constant beside it,
    # so the driver passes the key instead of monkeypatching a module global.
    cfg = {"extra_checks": [{"name": "freeze", "cmd": result_argv}],
           "check_timeout": (mod.DEFAULT_CONFIG["check_timeout"]
                             if timeout is None else timeout)}
    mod.check_extra(cfg)
    return mod.RESULTS[-1]


def test_a_timed_out_extra_check_names_its_command(tmp_path, monkeypatch, capfd):
    """REGRESSION PIN for lane S1's finding D (see the honesty note above):
    `res.timed_out` was once computed and discarded, printing `rc=-1;
    (no output)`."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    name, ok, evidence = _run_extra(monkeypatch, tmp_path, sleeper, timeout=1)
    assert name == "freeze"
    assert ok is False, evidence
    assert evidence.startswith("cmd "), evidence
    assert "TIMEOUT" in evidence, evidence
    assert "after 1s" in evidence, evidence
    assert "time.sleep" in evidence, evidence
    printed = _evidence_lines(capfd)
    assert any(ln.startswith("[FAIL] freeze:") for ln in printed), printed


def test_an_unlaunchable_extra_check_names_its_command(tmp_path, monkeypatch, capfd):
    """REGRESSION PIN for lane S1's finding D (see the honesty note above)."""
    bogus = ["definitely-not-an-executable-here", "--version"]
    name, ok, evidence = _run_extra(monkeypatch, tmp_path, bogus)
    assert name == "freeze"
    assert ok is False, evidence
    assert evidence.startswith("cmd "), evidence
    assert "could not run" in evidence, evidence
    assert "definitely-not-an-executable-here" in evidence, evidence
    printed = _evidence_lines(capfd)
    assert any(ln.startswith("[FAIL] freeze:") for ln in printed), printed


def test_a_green_extra_check_still_reports_its_command_and_rc(
        tmp_path, monkeypatch, capfd):
    """REGRESSION PIN for lane S1's finding D (see the honesty note above): the
    `cmd ` prefix pins an EARLIER fix, and is satisfied by the base, so this is
    not a red-before-green pin at this HEAD."""
    name, ok, evidence = _run_extra(
        monkeypatch, tmp_path, [sys.executable, "-c", "print('freeze verified')"])
    assert name == "freeze"
    assert ok is True, evidence
    assert evidence.startswith("cmd "), evidence
    assert sys.executable in evidence, evidence
    assert "freeze verified" in evidence, evidence
    assert "rc=0" in evidence, evidence
    printed = _evidence_lines(capfd)
    assert any(ln.startswith("[PASS] freeze:") for ln in printed), printed


def test_a_real_subprocess_timeout_really_is_marked(tmp_path):
    """The fake above must match what `run_argv` actually returns, so build the
    genuine article once: timed_out True, rc -1, and `ok` False."""
    mod = _load_sync_verify()
    res = mod.run_argv(tmp_path, [sys.executable, "-c", "import time; time.sleep(5)"],
                       timeout=1)
    assert res.timed_out is True
    assert res.rc == -1
    assert res.ok is False, "a timed-out run must never read as success"


# --------------------------------------------------------------------------
# finding E (this half): the import-time refusal must survive an ASCII console


def test_sync_verify_names_the_missing_module_on_an_ascii_console(ai_repo, sv):
    (ai_repo / ".ai" / "scripts" / "ai_common.py").unlink()
    res = run_python(sv, cwd=ai_repo,
                     env=dict(os.environ, PYTHONIOENCODING="ascii"))
    assert res.rc == 2, res.stdout + res.stderr
    assert res.stdout_raw, "the refusal printed nothing at all"
    assert "ai_common.py is missing from .ai/scripts/" in res.stdout, res.stdout
    assert "UnicodeEncodeError" not in res.stderr, res.stderr
    assert "Traceback" not in res.stderr, res.stderr


def test_the_import_refusal_carries_only_ascii_characters():
    """The structural half of finding E: this one message is printed before
    `protect_stdio()` can run, so it must be encodable on any console. Checked
    on the source line, because the rest of the file is allowed its em dashes."""
    lines = [ln for ln in (SCRIPTS / "sync_verify.py").read_text("utf-8").splitlines()
             if "ai_common.py is missing from" in ln]
    assert len(lines) == 1, lines
    assert "--" in lines[0], lines[0]
    assert "—" not in lines[0], lines[0]


# --------------------------------------------------------------------------
# lane S2 (r1 findings 1, 2, 3, 4, 6, 7, 11): the same defect, four more times
# -- a decline, an emptiness, a crash, or an all-skipped run booking itself in
# the passed numerator, or escaping the run altogether.


def test_a_run_that_declines_every_cap_leaves_only_skip_traces(ai_repo, sv):
    """Finding 1 (HIGH): `{"budgets": {<each floor name>: null}}` measured ZERO
    line budgets and printed five `[PASS] cap opt-out ...` lines -- the same
    line count as a healthy run -- at rc 0. Spec 4: a degradation may be a WARN
    or a SKIP, never a PASS."""
    cfg = json.loads((ai_repo / _CONFIG_REL).read_text("utf-8"))
    cfg["budgets"] = {name: None for name in sync_verify.BUDGET_FLOOR}
    (ai_repo / _CONFIG_REL).write_text(json.dumps(cfg), "utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    declined = [ln for ln in res.lines if "cap opt-out" in ln]
    assert declined, res.lines
    assert all(ln.startswith("[SKIP] cap opt-out ") for ln in declined), declined
    assert not any(ln.startswith("[PASS]") and "cap opt-out" in ln
                   for ln in res.lines), res.lines
    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1 and "skipped" in summary[0], res.lines


def test_the_run_says_how_many_project_checks_it_was_asked_to_run(ai_repo, sv):
    """Finding 2 (HIGH): the run never recorded how many `extra_checks` /
    `secret_mirrors` it registered, so `{"extra_checks": []}` -- or deleting the
    key from a config that carried three governance verifiers -- removed every
    project check with NO line at all and `N/N` green. An empty governance set
    costs the run its clean `passed == total` without going red."""
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    empty = [ln for ln in res.lines
             if ln.startswith("[SKIP] registered project checks:")]
    assert empty, res.lines
    assert "0 extra_checks" in empty[0] and "secret_mirrors" in empty[0], empty[0]
    assert not any(ln.startswith("[PASS] registered project checks:")
                   for ln in res.lines), res.lines
    patch_cfg(ai_repo, extra_checks=[
        {"name": "freeze", "cmd": [sys.executable, "-c", "print('verified')"]}])
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] registered project checks:")
               and "1 extra_checks" in ln for ln in res.lines), res.lines
    assert any(ln.startswith("[PASS] freeze:") for ln in res.lines), res.lines


def test_a_check_that_raises_is_named_and_the_rest_of_the_run_survives(ai_repo, sv):
    """Finding 3 (MEDIUM-HIGH): "the verifier reports failures instead of dying"
    covered CHILDREN only. A budget naming a directory reached `read_text()` and
    raised `IsADirectoryError` out of `main()`: no summary printed, and
    `check_extra` never ran."""
    patch_cfg(ai_repo, budgets={".ai/state": 60})
    res = run_python(sv, cwd=ai_repo)
    assert "Traceback" not in res.stderr, res.stderr + res.stdout
    # The OS error for "read a directory" is host-dependent
    # (`IsADirectoryError` on POSIX, `PermissionError [WinError 5]` here), so
    # the pin is that the crash was CONTAINED AND NAMED, not its class name.
    assert any(ln.startswith("[FAIL] line budgets check:")
               and "check raised" in ln for ln in res.lines), res.lines
    assert [ln for ln in res.lines if "checks passed" in ln], res.lines
    assert any(ln.startswith("[PASS] registered project checks:")
               or ln.startswith("[SKIP] registered project checks:")
               for ln in res.lines), res.lines
    assert any("secret ignored" in ln for ln in res.lines), res.lines
    # the sibling shape the review named: a mirror entry that is a directory
    patch_cfg(ai_repo, secret_mirrors=[[".", ".ai/state"]])
    res = run_python(sv, cwd=ai_repo)
    assert "Traceback" not in res.stderr, res.stderr + res.stdout
    assert any(ln.startswith("[FAIL] secret mirrors check:") for ln in res.lines), \
        res.lines
    assert [ln for ln in res.lines if "checks passed" in ln], res.lines


@pytest.mark.parametrize("raw", [
    '{"required_files": ["/etc/passwd"]}',
    '{"required_files": ["../outside.md"]}',
    '{"secret_files": ["../../etc/passwd"]}',
    '{"secret_mirrors": [["../outside", ".env"]]}',
])
def test_a_path_entry_cannot_point_outside_the_checkout(tmp_path, raw):
    """Finding 4 (MEDIUM): `PATH_LIST_KEYS` validated `isinstance(str)` and
    nothing else, so `required_files: ["/etc/passwd"]` became
    `ROOT / "/etc/passwd"` == `/etc/passwd` and printed a counted PASS about a
    file outside the tree."""
    cfg_path = tmp_path / "sync_config.json"
    cfg_path.write_text(raw, encoding="utf-8")
    with pytest.raises(sync_verify.ConfigError) as excinfo:
        sync_verify.load_config(cfg_path)
    assert str(excinfo.value).startswith("malformed:"), excinfo.value
    assert "repo-relative" in str(excinfo.value), excinfo.value


def test_a_run_of_only_skips_does_not_exit_zero(capsys):
    """Finding 6 (MEDIUM): `_summarise()` returned 0 whenever `failed` was empty,
    so an all-SKIP report printed `== 0/N checks passed, N skipped ==` and exited
    0. Latent at the base only because `config readable` always books a PASS --
    and findings 1 and 2 add SKIP producers, so it stopped being latent here.
    The `git usable` / `install layout` early returns are unaffected: they have a
    FAIL, which is why the second half below is a REGRESSION PIN, not a fix."""
    mod = _load_sync_verify()
    mod.RESULTS[:] = [("cap opt-out a", None, "declined"),
                      ("cap opt-out b", None, "declined")]
    assert mod._summarise() == 1, mod.RESULTS
    printed = capsys.readouterr().out
    assert "== 0/2 checks passed, 2 skipped ==" in printed, printed
    assert "NOT VERIFIED" in printed, printed

    mod = _load_sync_verify()
    mod.RESULTS[:] = [("config readable", True, "read"),
                      ("cap opt-out a", None, "declined")]
    assert mod._summarise() == 0, mod.RESULTS
    capsys.readouterr()


def test_the_two_child_workloads_have_two_timeouts(capsys):
    """Finding 7 (MEDIUM): one knob served `git check-ignore` (milliseconds) and
    user-registered scientific verifiers (minutes), and `EXTRA_CHECK_TIMEOUT`
    stayed alive as a second source of truth purely for in-process callers -- a
    drift pin (`DEFAULT_CONFIG == EXTRA_CHECK_TIMEOUT`) that LOCKED IN the
    single-knob design. Each key is now pinned on its own."""
    mod = _load_sync_verify()
    assert mod.DEFAULT_CONFIG["check_timeout"] == 600, mod.DEFAULT_CONFIG
    assert mod.DEFAULT_CONFIG["git_check_timeout"] == 15, mod.DEFAULT_CONFIG
    assert "git_check_timeout" in mod.KEY_SHAPES, sorted(mod.KEY_SHAPES)
    assert "git_check_timeout" in mod.POSITIVE_INT_KEYS, sorted(mod.POSITIVE_INT_KEYS)
    assert not hasattr(mod, "EXTRA_CHECK_TIMEOUT"), \
        "the second source of truth is back"
    assert mod.check_secrets_ignored.__code__.co_varnames[:1] == ("cfg",)
    text = (SCRIPTS / "sync_verify.py").read_text("utf-8")
    assert 'cfg["git_check_timeout"]' in text, "git is off on its own knob again"
    assert 'cfg["check_timeout"]' in text, text


def test_a_zero_git_check_timeout_is_named_malformed(tmp_path):
    cfg_path = tmp_path / "sync_config.json"
    cfg_path.write_text('{"git_check_timeout": 0}', encoding="utf-8")
    with pytest.raises(sync_verify.ConfigError) as excinfo:
        sync_verify.load_config(cfg_path)
    assert "git_check_timeout" in str(excinfo.value), excinfo.value


def test_an_ignored_secret_that_is_not_there_says_so(ai_repo, sv):
    """Finding 11 (LOW): `secret ignored: .env` PASSed on `git check-ignore` rc 0
    -- which proves a RULE matched, not that the file is safely placed. An absent
    `.env` yielded a counted PASS with no hint that nothing was checked."""
    (ai_repo / ".env").unlink(missing_ok=True)
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    absent = [ln for ln in res.lines if ln.startswith("[PASS] secret ignored: .env")]
    assert absent, res.lines
    assert "file absent" in absent[0], absent[0]
    (ai_repo / ".env").write_text("KEY=value\n", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    present = [ln for ln in res.lines if ln.startswith("[PASS] secret ignored: .env")]
    assert present and "file absent" not in present[0], res.lines
