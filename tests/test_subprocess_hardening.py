"""Lane B3a: the verifier must never crash, never read a degradation as green,
and never count something it did not observe.

Spec 4's law governs every test here: a degradation may produce only a named
`WARN` or `SKIP`, never `PASS`, and `returncode == 0` is never by itself
evidence. Three shapes are pinned in this file, in the order the lane landed
them:

  * `record()` speaks three verdicts (PASS / FAIL / SKIP) and the summary line
    keeps skips OUT of the passed fraction — the channel lane S1's
    `# TODO-1a/1b boundary` comments were waiting for;
  * the pre-flight and child-process shapes of Task 6 (D5, D11, D12, D13, D21):
    no git on PATH, a non-git tree, a hung `extra_checks` command, a
    string-typed `cmd`, and the `protect_stdio()` call that keeps a cp936
    console from killing the run mid-report;
  * review finding A.2: an `extra_checks` child that exits 0 having written
    zero bytes on both streams observed NOTHING, which is a SKIP, not a
    `[PASS] … rc=0` counted in `== N/N checks passed ==`.

The three D5 tests copied from `d5-repro.md` §6.2 (via `batch-B3.md`) were
measured green at `d1628d7` and are REGRESSION PINS, not this lane's
red-before-green work; the commit bodies say which tests were actually red.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys

import pytest

from helpers import SCRIPTS, run_python

# The one summary line format, pinned rather than eyeballed. The skip count
# shares the line with the fraction so it cannot be scrolled past; it is
# optional ONLY because a run with nothing skipped has nothing to say — every
# test below that produces a skip asserts the count is present.
SUMMARY_RE = re.compile(r"== (\d+)/(\d+) checks passed(?:, (\d+) skipped)? ==")


def _load_sync_verify():
    """A fresh import of the shipped verifier, for the in-process pins.

    `ai_common` is popped around it (same dance as
    `tests/test_config_errors.py`): the module imports it by name, and a
    stale entry would hand a test a half-initialised copy.
    """
    saved = sys.modules.pop("ai_common", None)
    name = "_sync_verify_under_test_subprocess_hardening"
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


# --------------------------------------------------------------------------
# Step 1: `record()` gains a third state, and a skip is not evidence


def test_record_prints_three_verdicts_and_a_skip_is_not_a_pass(capsys):
    """The channel itself, with no install and no subprocess in the way.

    Before this landed `record()` could only say PASS or FAIL, so lane S1 left
    two spec-correct SKIPs printing as FAILs and costing a legal install its
    green. A value that is neither bool nor None (which would once have read as
    PASS through a bare truthiness test) is reported as FAIL, never PASS, and
    never raises — Task 6's "the verifier cannot crash" applies to its own
    reporting path.
    """
    mod = _load_sync_verify()
    mod.record("a pass", True, "looked")
    mod.record("a fail", False, "looked and disagreed")
    mod.record("a skip", None, "SKIP(could not look)")
    mod.record("a lie", 1, "not a verdict this function speaks")
    printed = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert printed[0].startswith("[PASS] a pass:"), printed
    assert printed[1].startswith("[FAIL] a fail:"), printed
    assert printed[2].startswith("[SKIP] a skip:"), printed
    assert printed[3].startswith("[FAIL] a lie:"), printed
    assert [ok for _, ok, _ in mod.RESULTS] == [True, False, None, False], \
        mod.RESULTS
    assert mod._summarise() == 1, "a FAIL is present, so the run is red"
    reported = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    summary = [ln for ln in reported if "checks passed" in ln]
    assert len(summary) == 1, reported
    assert summary[0] == "== 1/4 checks passed, 1 skipped ==", summary[0]
    assert reported[-1] == "FAILED: a fail, a lie", reported


def test_an_install_that_declares_no_decision_log_is_a_skip_not_a_red(
        ai_repo, sv):
    """Lane S1 finding 3's `# TODO-1a/1b boundary`, converted.

    Ruling: an unconfigured `decisions_file` that simply is not there is a
    legal installation, so it is a SKIP — but only because presence is covered
    by a necessity check elsewhere. `.ai/state/DECISIONS.md` is a member of
    `ai_common.DEFAULT_REQUIRED_FILES`, which IS `DEFAULT_CONFIG`'s
    `required_files`, and it is deliberately NOT in `REQUIRED_FILE_FLOOR`: a
    repo that keeps the entry and loses the file still gets
    `[FAIL] required .ai/state/DECISIONS.md: missing`, and a repo that drops
    the entry has declared, in the one key that owns the question, that it
    keeps no decision log. Either way the absence is named by a check that owns
    it, which is what spec 4 demands before anything may skip.

    A `decisions_file` RETARGETED to a path that does not exist stays a FAIL
    (`tests/test_config_errors.py::test_a_retargeted_decisions_file_is_a_named_failure`):
    no requirement covers that path, so skipping there is exactly the silent
    removal of the cap that finding 3 exists to catch.
    """
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["required_files"] = [rel for rel in cfg["required_files"]
                             if rel != ".ai/state/DECISIONS.md"]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (ai_repo / ".ai" / "state" / "DECISIONS.md").unlink()

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    skips = [ln for ln in res.lines if ln.startswith("[SKIP]")]
    assert any(ln.startswith("[SKIP] budget DECISIONS active entries:")
               for ln in skips), res.lines
    assert not any(ln.startswith("[FAIL] budget DECISIONS") for ln in res.lines)
    assert not any(ln.startswith("[FAIL]") for ln in res.lines), res.lines

    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1, res.lines
    match = SUMMARY_RE.fullmatch(summary[0])
    assert match, summary[0]
    passed, total, skipped = match.groups()
    assert skipped == "1", summary[0]
    assert int(passed) < int(total), summary[0]
    assert "FAILED:" not in res.lines, res.lines
