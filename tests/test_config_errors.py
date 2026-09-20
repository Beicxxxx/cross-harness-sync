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
])
def test_a_governed_key_of_the_wrong_shape_is_named_not_guessed(
        ai_repo, sv, bad, expected_key):
    """`{"secret_files": ".env"}` used to iterate the four CHARACTERS of a
    string: the floor was silently gone and the run printed nonsense instead."""
    write_raw(ai_repo, bad)
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert readable_failures(res), res.lines
    assert "malformed:" in readable_failures(res)[0], res.lines
    assert expected_key in readable_failures(res)[0], res.lines


def test_load_config_raises_a_typed_error_for_each_reason(tmp_path):
    """The three prefixes are the contract later lanes parse; they must come
    from `load_config()`, not only from the printed line."""
    missing = tmp_path / ".ai"
    (missing / "sub").mkdir(parents=True)
    sync_verify.CONFIG_PATH = missing / "sync_config.json"
    cases = [(None, "unreadable:"), ('{"budgets": ', "malformed:"),
             ("[]", "not-object:"), ('{"budgets": []}', "malformed:"),
             ('{"secret_files": ".env"}', "malformed:"),
             ('{"budgets": {"a": "60"}}', "malformed:")]
    try:
        for text, prefix in cases:
            if text is None:
                sync_verify.CONFIG_PATH.unlink(missing_ok=True)
            else:
                sync_verify.CONFIG_PATH.write_text(text, encoding="utf-8")
            with pytest.raises(sync_verify.ConfigError) as excinfo:
                sync_verify.load_config()
            assert str(excinfo.value).startswith(prefix), (prefix, excinfo.value)
    finally:
        sync_verify.CONFIG_PATH = None


def test_load_config_merges_instead_of_replacing_defaults(tmp_path):
    ai = tmp_path / ".ai"
    ai.mkdir()
    (ai / "sync_config.json").write_text(
        json.dumps({"budgets": {".ai/state/CURRENT.md": 10}}), encoding="utf-8")
    sync_verify.CONFIG_PATH = ai / "sync_config.json"
    try:
        cfg = sync_verify.load_config()
    finally:
        sync_verify.CONFIG_PATH = None
    assert cfg["budgets"][".ai/handoff/LATEST.md"] == 80, cfg["budgets"]
    assert cfg["budgets"][".ai/state/CURRENT.md"] == 10, cfg["budgets"]
    assert "AGENTS.md" not in cfg["budgets"], cfg["budgets"]
    assert cfg["secret_files"] == [".env"], cfg


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


def _evidence_lines(capfd) -> list[str]:
    out = capfd.readouterr().out
    return [ln for ln in out.splitlines() if ln.strip()]


def _run_extra(monkeypatch, tmp_path, result_argv, timeout=None):
    mod = _load_sync_verify()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    if timeout is not None:
        monkeypatch.setattr(mod, "EXTRA_CHECK_TIMEOUT", timeout)
    mod.check_extra({"extra_checks": [{"name": "freeze", "cmd": result_argv}]})
    return mod.RESULTS[-1]


def test_a_timed_out_extra_check_names_its_command(tmp_path, monkeypatch, capfd):
    """`res.timed_out` was computed and discarded: `rc=-1; (no output)`."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    name, ok, evidence = _run_extra(monkeypatch, tmp_path, sleeper, timeout=1)
    assert name == "freeze"
    assert ok is False, evidence
    assert "TIMEOUT" in evidence, evidence
    assert "after 1s" in evidence, evidence
    assert "time.sleep" in evidence, evidence
    printed = _evidence_lines(capfd)
    assert any(ln.startswith("[FAIL] freeze:") for ln in printed), printed


def test_an_unlaunchable_extra_check_names_its_command(tmp_path, monkeypatch, capfd):
    bogus = ["definitely-not-an-executable-here", "--version"]
    name, ok, evidence = _run_extra(monkeypatch, tmp_path, bogus)
    assert name == "freeze"
    assert ok is False, evidence
    assert "could not run" in evidence, evidence
    assert "definitely-not-an-executable-here" in evidence, evidence
    printed = _evidence_lines(capfd)
    assert any(ln.startswith("[FAIL] freeze:") for ln in printed), printed


def test_a_green_extra_check_still_reports_its_command_and_rc(
        tmp_path, monkeypatch, capfd):
    name, ok, evidence = _run_extra(
        monkeypatch, tmp_path, [sys.executable, "-c", "print('freeze verified')"])
    assert name == "freeze"
    assert ok is True, evidence
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
