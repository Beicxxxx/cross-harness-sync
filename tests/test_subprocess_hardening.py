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

import ast
import importlib.util
import json
import locale
import os
import re
import subprocess
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
    # Two SKIPs, both named: the absent decision log (B3a) and lane S2 finding
    # 2's `registered project checks`, a SKIP because the shipped template
    # registers no `extra_checks` and no `secret_mirrors`.
    assert skipped == "2", summary[0]
    assert int(passed) < int(total), summary[0]
    assert "FAILED:" not in res.lines, res.lines


# --------------------------------------------------------------------------
# Step 2 (Task 6): the verifier cannot crash, and cannot be blindsided by a
# child it could not read.
#
# The first three tests are `batch-B3.md` Step 1 verbatim. The three D5 tests
# at the bottom are copied verbatim from `d5-repro.md` §6.2 through the same
# brief: they were measured green at `d1628d7`, so they are REGRESSION PINS for
# Task 1's bytes plumbing, not this lane's red.


def test_no_git_on_path_is_one_clean_failure(ai_repo, sv, tmp_path):
    fake = tmp_path / "empty-bin"
    fake.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "PATH"}
    env["PATH"] = str(fake)
    res = run_python(sv, cwd=ai_repo, env=env)
    assert res.rc == 1, res.stdout
    assert "Traceback" not in res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] git usable") for ln in res.lines), res.lines


def test_non_git_tree_reports_repository_once(ai_repo, sv, tmp_path):
    """`batch-B3.md` Step 1 verbatim except for HOW the tree loses git.

    The brief's `shutil.rmtree(ai_repo / ".git")` cannot run on this host: git
    writes its objects read-only, so the delete dies with
    `PermissionError: [WinError 5]` on `.git\\objects\\12\\9e6f...` (measured)
    before the verifier is ever invoked. Renaming `.git` out of the tree is the
    idiom this suite already uses for "git cannot locate this work tree"
    (`tests/test_install_layout.py:91`), and it leaves `git` on PATH, which is
    the whole point of the case: the tree is the problem, not the tool.
    """
    (ai_repo / ".git").rename(tmp_path / "not-this-tree-s-git")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any(ln.startswith("[FAIL] git repository") for ln in res.lines), \
        res.lines
    assert not any("rc=128" in ln for ln in res.lines), res.lines


def test_hung_extra_check_becomes_a_fail_not_a_traceback(ai_repo, sv):
    slow = "import time; time.sleep(30)"
    (ai_repo / "slow.py").write_text(slow, encoding="utf-8")
    cfg = json.loads((ai_repo / ".ai" / "sync_config.json").read_text("utf-8"))
    cfg["extra_checks"] = [{"name": "slow check",
                            "cmd": [sys.executable, "slow.py"]}]
    cfg["check_timeout"] = 1
    (ai_repo / ".ai" / "sync_config.json").write_text(json.dumps(cfg), "utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any(ln.startswith("[FAIL] slow check") and "timed out" in ln
               for ln in res.lines), res.lines


def test_a_string_valued_check_timeout_is_named_not_multiplied(ai_repo, sv):
    """`{"check_timeout": "1"}` must not become a string compared against an
    int, and must not silently inherit the 600 s default either: the shape
    check owns the first answer, the second would be D5's fail-open wearing
    config."""
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["check_timeout"] = "1"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    # F6 (lane Z): a config the shape check refuses is "unusable", which
    # SKILL.md's exit-code table documents as rc 2 (no verdict), not rc 1
    # (a check ran and failed). The named-in-the-message half is unchanged.
    assert res.rc == 2, res.stdout
    assert any(ln.startswith("[FAIL] config readable") and "malformed:" in ln
               and "check_timeout" in ln for ln in res.lines), res.lines
    assert "Traceback" not in res.stderr, res.stderr


def test_a_string_extra_check_cmd_is_a_named_failure(tmp_path, monkeypatch,
                                                     capsys):
    """D21: a string `cmd` runs under a shell on one platform and dies on
    another, so a governance check can quietly exist on Windows and not on
    macOS. `check_extra` refuses the shape even though `_check_shape` already
    rejects it on the way in — the check is where the promise lives."""
    mod = _load_sync_verify()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    # lane S2 finding 7: the timeout arrives as config, never as a patched
    # constant, because a constant is a second source of truth.
    mod.check_extra({"extra_checks": [{"name": "freeze", "cmd": "git status"}],
                     "check_timeout": mod.DEFAULT_CONFIG["check_timeout"]})
    printed = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    name, ok, evidence = mod.RESULTS[-1]
    assert name == "freeze"
    assert ok is False, evidence
    assert "JSON array" in evidence, evidence
    assert printed[-1].startswith("[FAIL] freeze:"), printed


def test_the_timeout_knobs_are_two_and_not_one_anymore(tmp_path, monkeypatch,
                                                       capsys):
    """Lane S2 finding 7, replacing `test_the_timeout_default_is_the_config_key_
    falls_back_to_the_constant`. That pin ASSERTED the drift
    (`DEFAULT_CONFIG["check_timeout"] == EXTRA_CHECK_TIMEOUT`), which locked in a
    single 600 s knob shared by `git check-ignore` (milliseconds) and
    user-registered scientific verifiers (minutes), and kept the constant alive
    only so in-process callers could skip the config. One key per workload now,
    each pinned on its own, and the git half gets its own short allowance."""
    mod = _load_sync_verify()
    assert mod.DEFAULT_CONFIG["git_check_timeout"] == 15, mod.DEFAULT_CONFIG
    assert mod.DEFAULT_CONFIG["check_timeout"] == 600, mod.DEFAULT_CONFIG
    assert not hasattr(mod, "EXTRA_CHECK_TIMEOUT"), \
        "the constant is back, and with it the second source of truth"
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    mod.check_extra({"extra_checks": [{"name": "freeze", "cmd": sleeper}],
                     "check_timeout": 2})
    _, ok, evidence = mod.RESULTS[-1]
    assert ok is False, evidence
    assert "timed out" in evidence and "TIMEOUT" in evidence, evidence
    assert "after 2s" in evidence, evidence
    capsys.readouterr()


def test_main_protects_stdio_before_anything_can_be_printed():
    """Structural pin (REGRESSION PIN, green at `ec505e3`): Task 1 wired
    `protect_stdio()` and Task 6 asserts the wiring stays first, because every
    later line in `main()` may carry a character the console codec refuses."""
    tree = ast.parse((SCRIPTS / "sync_verify.py").read_text(encoding="utf-8"))
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = [s for s in main.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str))
            and not (isinstance(s, ast.Global) or isinstance(s, ast.Nonlocal))]
    first = body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call), \
        ast.dump(first)
    fn = first.value.func
    assert isinstance(fn, ast.Name) and fn.id == "protect_stdio", ast.dump(fn)


def test_a_non_ascii_verdict_reaches_an_ascii_console(ai_repo, sv):
    """D13 end-to-end (REGRESSION PIN for Task 1's `protect_stdio()`): the child
    writes raw UTF-8, the parent decodes it, and the parent must still be able
    to PRINT it on a console pinned to ASCII — the failure was
    UnicodeEncodeError with an empty stdout."""
    arrow = "→"
    child = ("import sys;sys.stdout.buffer.write("
             f"bytes({[b for b in arrow.encode('utf-8')]}[:0] + "
             "[0xE2, 0x86, 0x92]) + b' observed')")
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["extra_checks"] = [{"name": "arrow check",
                            "cmd": [sys.executable, "-c", child]}]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    res = run_python(sv, cwd=ai_repo,
                     env=dict(os.environ, PYTHONIOENCODING="ascii"))
    assert res.rc == 0, res.stdout + res.stderr
    assert "UnicodeEncodeError" not in res.stderr, res.stderr
    assert "Traceback" not in res.stderr, res.stderr
    assert arrow.encode("utf-8") in res.stdout_raw, res.stdout_raw
    assert any(ln.startswith("[PASS] arrow check:") for ln in res.lines), res.lines


# --------------------------------------------------------------------------
# Step 3 (review finding A.2): rc == 0 with NOTHING observed is not a pass.


def test_a_silent_extra_check_is_a_named_skip_not_a_pass(ai_repo, sv):
    """The last surviving instance of the class this wave exists to end.

    Task 1 closed D5's DECODE path (bytes, never `text=True`) but not `ok`
    semantics: a child that exits 0 having written zero bytes on both streams
    was reported `[PASS] <name> rc=0; (no output)` and COUNTED in
    `== N/N checks passed ==`. Nothing was observed, so nothing was verified;
    spec 4 allows that shape only as a named WARN or SKIP. The command and its
    rc stay in the evidence, because "which check went mute" is the question an
    operator on the other side of a handoff actually has to answer.
    """
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["extra_checks"] = [{"name": "silent check",
                            "cmd": [sys.executable, "-c", "pass"]}]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert not any(ln.startswith("[PASS] silent check") for ln in res.lines), \
        res.lines
    skips = [ln for ln in res.lines if ln.startswith("[SKIP] silent check:")]
    assert len(skips) == 1, res.lines
    line = skips[0]
    assert "wrote nothing" in line, line
    assert "nothing observed" in line, line
    assert "rc=0" in line, line
    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1, res.lines
    match = SUMMARY_RE.fullmatch(summary[0])
    assert match, summary[0]
    passed, total, skipped = match.groups()
    assert skipped == "1", summary[0]
    assert int(passed) == int(total) - 1, summary[0]


def test_a_silent_failing_child_is_still_a_fail(ai_repo, sv):
    """The SKIP is for a child that CLAIMS success without evidence; a nonzero
    exit that wrote nothing is a FAIL, and must never be softened into a skip
    that leaves the run green."""
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["extra_checks"] = [{"name": "mute failure",
                            "cmd": [sys.executable, "-c", "raise SystemExit(3)"]}]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[FAIL] mute failure:") and "rc=3" in ln
               for ln in res.lines), res.lines
    assert not any(ln.startswith("[SKIP] mute failure") for ln in res.lines)
    assert "FAILED: mute failure" in res.lines, res.lines


# --------------------------------------------------------------------------
# D5 regression pins, verbatim from d5-repro.md §6.2 via batch-B3.md Step 1.

WEN_PY = "文.py"        # U+6587 -> UTF-8 E6 96 87; 0x87 + '.' (2E) is no cp936 pair
EMIT = "import sys;sys.stdout.buffer.write(bytes([int(x, 16) for x in sys.argv[1:]]))"
# sync_verify.py as shipped at 60fa5dd — the anti-pattern, pinned so this file can
# never drift back to it without a test going red.
LEGACY_KW = dict(capture_output=True, text=True, timeout=600)

WALK_SRC = '''\
import subprocess, sys
cmd = ["git", "log", "--no-merges", "--full-history", "--name-only", "-z",
       "--pretty=format:%H", "--", "*.py"]
p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
paths = [t.split(b"\\n")[-1] for t in p.stdout.split(b"\\0") if t.endswith(b".py")]
paths.sort(key=lambda b: (b"\\xe6" not in b, b))     # CJK first: beats the [:160] cut
sys.stdout.buffer.write(b"covered=%d:" % len(paths) + b",".join(paths))
sys.stdout.buffer.flush()
raise SystemExit(0)
'''


def pipe_codec() -> str:
    fn = getattr(subprocess, "_text_encoding", None)      # 3.12+; earlier inlined it
    return fn() if fn else locale.getpreferredencoding(False)


def first_rejected_byte(codec: str):
    for b in range(0x80, 0x100):
        try:
            bytes([b]).decode(codec)
        except UnicodeDecodeError:
            return b
    return None


BAD_BYTE = first_rejected_byte(pipe_codec())
BAD_ARGV = [sys.executable, "-c", EMIT,
            f"{BAD_BYTE:02X}" if BAD_BYTE is not None else "E6"]


def walk_line(res) -> str:
    """The one PASS line, or a hard failure. Absence is never a pass."""
    hit = [ln for ln in res.lines if ln.startswith("[PASS] protected-path walk:")]
    assert len(hit) == 1, res.lines
    return hit[0]


@pytest.fixture
def walked(ai_repo):
    """A scaffolded repo whose protected-path walk can only answer in raw UTF-8."""
    (ai_repo / WEN_PY).write_text("x = 1\n", encoding="utf-8")
    (ai_repo / "plain.py").write_text("x = 1\n", encoding="utf-8")
    ident = ["-c", "user.name=Test Human", "-c", "user.email=t@example.invalid",
             "-c", "commit.gpgsign=false"]
    for args in (["add", "--", WEN_PY, "plain.py"],
                 ["commit", "-q", "-m", "touch a Chinese path"]):
        r = subprocess.run(["git", *ident, *args], cwd=str(ai_repo),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert r.returncode == 0, r.stderr
    (ai_repo / "walk.py").write_text(WALK_SRC, encoding="utf-8")
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["extra_checks"] = [{"name": "protected-path walk",
                            "cmd": [sys.executable, "walk.py"]}]
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return ai_repo


def test_verifier_surfaces_a_raw_nonascii_path(walked, sv):
    res = run_python(sv, cwd=walked)
    assert res.stdout_raw, "the verifier wrote nothing at all"
    assert "Traceback" not in res.stderr, res.stderr
    assert "_readerthread" not in res.stderr, res.stderr
    assert WEN_PY in walk_line(res), res.lines


@pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_text_capture_goes_blind_on_a_byte_the_host_codec_rejects():
    """Same shape as the codec test below: the crash is the finding.

    HOST PROBE, NOT A FIX PIN. The `text=True` capture built here is this test's
    own (`LEGACY_KW`), never a shipped script's, so no revert of any file under
    `scripts/` can redden it — it documents CPython's blindness, which is D5's
    premise. The D5 evidence is `test_verifier_surfaces_a_raw_nonascii_path`
    above, which a revert of `run_argv` back to `text=True` does turn red. Do
    not count this one among the fixes.

    This test asserts that the legacy `text=True` capture goes BLIND — rc 0
    with `stdout is None` — which can only happen because the reader thread
    died in this process, and pytest reports that death as
    PytestUnhandledThreadExceptionWarning. The warning is the expected shape
    of a passing assertion here, so it is ignored for this test alone rather
    than for the suite.
    """
    if BAD_BYTE is None and sys.platform == "win32":
        pytest.fail("the host codec decodes every byte 0x80-0xFF, so the silent "
                    "form of D5 cannot be exhibited here; do not let this one "
                    "skip green.")
    if sys.platform == "win32":
        proc = subprocess.run(BAD_ARGV, **LEGACY_KW)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout is None, ascii(proc.stdout)
        assert proc.stderr == "", ascii(proc.stderr)
    else:
        with pytest.raises(UnicodeDecodeError):
            subprocess.run(BAD_ARGV, **LEGACY_KW)
    fixed = subprocess.run(BAD_ARGV, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    assert fixed.returncode == 0
    if BAD_BYTE is not None:
        assert fixed.stdout == bytes([BAD_BYTE]), ascii(fixed.stdout)


@pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning")
@pytest.mark.parametrize("codec", ["cp936", "shift_jis", "big5"])
def test_the_hazard_does_not_depend_on_the_host_codepage(monkeypatch, codec):
    """The reader-thread crash IS the assertion, not something suppressed.

    HOST PROBE, NOT A FIX PIN: like the test above, this exercises `text=True`
    that the test itself passes to `subprocess.run`, so no revert of a shipped
    file can redden it. It exists to show the blindness is the codec-independent
    shape of D5, not a quirk of this console. D5's pin stays
    `test_verifier_surfaces_a_raw_nonascii_path`.

    With `text=True` and a child byte the host codec rejects, CPython's
    subprocess _readerthread dies inside THIS process. pytest surfaces that as
    PytestUnhandledThreadExceptionWarning, and the test then passes — on
    `stdout is None`, which is exactly the D5 blindness under test. A green
    suite may not carry that warning: a listing gate reads a warning-laden run
    as an unstable one, and `-W error` CI would fail on a passing test. So the
    filter is scoped to this test and nowhere else; anywhere else in the suite
    an unhandled thread exception still surfaces.
    """
    if not hasattr(subprocess, "_text_encoding"):
        pytest.skip("CPython < 3.12 has no subprocess._text_encoding to force")
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: codec)
    assert subprocess._text_encoding() == codec, "the patch did not take"
    argv = [sys.executable, "-c", EMIT, "E6", "96", "87", "2E"]   # '文' + '.'
    if sys.platform == "win32":
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        assert proc.stdout is None, f"{codec}: {ascii(proc.stdout)}"
    else:
        with pytest.raises(UnicodeDecodeError):
            subprocess.run(argv, capture_output=True, text=True, timeout=600)

