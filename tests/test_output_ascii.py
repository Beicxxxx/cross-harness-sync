"""The console-output layer: what a script PRINTS must arrive readable.

Two rules, each measured against the shipped code's own output rather than
against an assumption about it:

* `protect_stdio()` runs first in every entry script, so what a script prints
  arrives as UTF-8 bytes instead of the console codepage's bytes.
* The printed prose is ASCII. UTF-8 bytes are *correct* and still unreadable on
  a cp936 console — they render as mojibake — so "valid UTF-8" is not the
  finish line for console output. `init_sync.py` is the first thing a new user
  ever runs, which is why its `--help`-adjacent output is pinned here.

State files and templates are NOT under the second rule: the protocol allows
any language in them (a CJK state file is a supported configuration), so the
managed block `init_sync.py` writes into `AGENTS.md` keeps its em dashes and its
`<= 15 lines` budgets. `templates/AGENTS.md` is likewise exempt.

The AST scan at the bottom is the complement to the runtime assertions, never a
substitute for them: it names the printed-string paths this host's runs cannot
reach (a config that declines a budget, a floor-only required file), and it is
deliberately narrow — comment and docstring prose is not output and is skipped.
"""
from __future__ import annotations

import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from helpers import (REPO_ROOT, SCRIPTS, make_repo, run_python, scaffold)

ENTRY_SCRIPTS = ["init_sync.py", "checkpoint.py", "sync_verify.py",
                 "ai_common.py"]

# Non-ASCII payloads that are STATE-FILE / template content, not console
# output, so the ASCII rule does not apply to them (module docstring).
FILE_CONTENT_SIGNATURES = (
    "Cross-Harness Continuity (managed block",   # MANAGED_BLOCK -> AGENTS.md
    "# Claude Code",                            # claude_text  -> CLAUDE.md
)


def _non_ascii_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.isascii()]


def _assert_output_is_ascii(res, where: str) -> None:
    bad = [("stdout", ln) for ln in _non_ascii_lines(res.stdout)]
    bad += [("stderr", ln) for ln in _non_ascii_lines(res.stderr)]
    assert not bad, (
        f"{where} printed non-ASCII text, which a cp936 console renders as "
        f"mojibake; use ASCII punctuation in printed prose:\n"
        + "\n".join(f"  {stream}: {ln!r}" for stream, ln in bad))
    assert "Traceback" not in res.stderr, res.stderr


@pytest.fixture
def workspace():
    """An absolute throwaway dir OUTSIDE this checkout, ASCII-nameable."""
    base = Path(tempfile.mkdtemp(prefix="laneH-out-"))
    try:
        if not str(base).isascii():
            pytest.skip(f"{base} cannot be named in ASCII on this host; the "
                        "assertions below would fail on the path, not the prose")
        yield base
    finally:
        shutil.rmtree(str(base), ignore_errors=True)


@pytest.fixture
def installed(workspace):
    """A fresh git repo with the skill installed into it, plus init's output."""
    repo = make_repo(workspace)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    return repo, res


# --- item 1: protect_stdio() on the install path -----------------------------

def test_installer_stdout_bytes_decode_as_utf_8(installed):
    """Red today: the installer writes its own arrow into the console codepage.

    Nothing here depends on the printed text being non-ASCII — the point is the
    BYTES a caller with a pipe gets back, which is what every log, CI collector
    and `> file` redirect on a Windows host has to decode.
    """
    _repo, res = installed
    assert res.stdout_raw, "the installer wrote nothing at all"
    try:
        res.stdout_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        pytest.fail(f"installer stdout is not UTF-8 — protect_stdio() is not "
                    f"running first: {exc}\n  {res.stdout_raw[:160]!r}")


def test_installer_carries_a_non_ascii_target_path_in_utf_8(workspace):
    """The durable form of the same pin: non-ASCII content the script does not
    own, so removing the non-ASCII punctuation from printed prose cannot make
    this test vacuous. `init_sync.py` prints the target path it was handed."""
    target = workspace / "项目-包"
    target.mkdir(parents=True)
    res = run_python(SCRIPTS / "init_sync.py", [str(target)], cwd=target)
    assert res.stdout_raw, "the installer wrote nothing at all"
    try:
        decoded = res.stdout_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        pytest.fail(f"installer stdout is not UTF-8 — protect_stdio() is not "
                    f"running first: {exc}\n  {res.stdout_raw[:160]!r}")
    assert "项目" in decoded, (
        "the target path never reached stdout as text: "
        f"{decoded[:200]!r}")


# The child prints sys.stdout.encoding AFTER main() has run, so it reports the
# stream the installer is actually holding when it prints. The wrapper is
# forced to cp936 here rather than inherited from the host, so the test says
# the same thing on a UTF-8 host.
_PROTECT_CHILD = (
    "import io, os, sys\n"
    "sys.path.insert(0, os.environ['LANEH_SCRIPTS'])\n"
    "import init_sync\n"
    # The cp936 wrapper has to stay referenced: protect_stdio() re-wraps its
    # buffer, and an unreferenced TextIOWrapper is collected and CLOSES it.
    # sys.__stdout__ keeps the real stream alive in production, so this only
    # bites a probe that builds its own stream.
    "stdout_cp936 = io.TextIOWrapper(open(os.devnull, 'wb'),\n"
    "                             encoding='cp936')\n"
    "sys.stdout = stdout_cp936\n"
    "sys.stderr = sys.__stderr__\n"
    "sys.argv = ['init_sync.py', '--help']\n"
    "try:\n    init_sync.main()\nexcept SystemExit:\n    pass\n"
    "print(getattr(sys.stdout, 'encoding', None), file=sys.__stdout__)\n"
)


def test_installer_replaces_a_non_utf8_stdout_before_printing():
    out = subprocess.run([sys.executable, "-c", _PROTECT_CHILD],
                         cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         env=dict(os.environ, LANEH_SCRIPTS=str(SCRIPTS)))
    reported = out.stdout.decode("utf-8", "replace").strip()
    assert reported.startswith("utf-8"), (
        f"init_sync.main() left a {reported!r} stdout in place; it must call "
        "ai_common.protect_stdio() first, as checkpoint.py and sync_verify.py "
        f"do (rc {out.returncode}: {out.stderr[:300]!r})")


# --- item 2: printed prose is ASCII ------------------------------------------

def test_fresh_install_prints_only_ascii(installed):
    _repo, res = installed
    _assert_output_is_ascii(res, "init_sync.py on a fresh install")


@pytest.mark.parametrize("script", ["init_sync.py", "checkpoint.py",
                                     "sync_verify.py"])
def test_help_prints_only_ascii(installed, script):
    """`--help` is the other first contact a new user gets."""
    repo, _res = installed
    # init_sync.py is the skill's own entry script; the two it installs are
    # read from the install, which is where they are actually run from.
    path = (SCRIPTS / script) if script == "init_sync.py" \
        else repo / ".ai" / "scripts" / script
    assert path.is_file(), path
    res = run_python(path, ["--help"], cwd=repo)
    _assert_output_is_ascii(res, f"{script} --help")


def test_verifier_on_a_fresh_install_prints_only_ascii(installed):
    repo, _res = installed
    res = run_python(repo / ".ai" / "scripts" / "sync_verify.py", [], cwd=repo)
    _assert_output_is_ascii(res, "sync_verify.py on a fresh install")


@pytest.fixture
def installed_without_git(workspace):
    """An install in a plain directory: the layout refusal is prose too."""
    repo = workspace / "not-a-repo"
    repo.mkdir(parents=True)
    res = run_python(SCRIPTS / "init_sync.py", [str(repo)], cwd=repo)
    assert res.rc == 0, res.stdout + res.stderr
    return repo


def test_verifier_outside_a_repository_prints_only_ascii(installed_without_git):
    repo = installed_without_git
    res = run_python(repo / ".ai" / "scripts" / "sync_verify.py", [], cwd=repo)
    out = res.stdout
    assert "outside-repo" in out or "not determined" in out, (
        f"the refusal did not run: {out[:400]!r}")
    _assert_output_is_ascii(res, "sync_verify.py outside a repository")


def test_lock_refusal_outside_a_repository_prints_only_ascii(
        installed_without_git):
    repo = installed_without_git
    res = run_python(repo / ".ai" / "scripts" / "checkpoint.py",
                     ["--lock", "--agent", "lane-h"], cwd=repo)
    assert res.stdout.strip(), "the refusal wrote nothing"
    _assert_output_is_ascii(res, "checkpoint.py --lock outside a repository")


def test_script_prose_strings_are_ascii():
    """Every string constant that is not a docstring, a comment, or state-file
    content reaches a console, so it must be ASCII.

    This is the backstop for printed paths a run on one host cannot reach; the
    tests above are the primary evidence. Comments and docstrings are skipped:
    they are never printed, and folding them in would only teach the next author
    to delete the explanation.
    """
    offenders = []
    for name in ENTRY_SCRIPTS:
        path = SCRIPTS / name
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) \
                    or not isinstance(node.value, str) \
                    or id(node) in docstrings:
                continue
            bad = sorted({c for c in node.value if not c.isascii()})
            if not bad:
                continue
            if any(s in node.value for s in FILE_CONTENT_SIGNATURES):
                continue                 # state-file / template payload
            if any(c != "\ufeff" for c in bad):        # BOM handling is code
                offenders.append((name, node.lineno,
                                  "".join(bad), node.value[:60]))
    assert not offenders, (
        "non-ASCII punctuation in printed strings (use '-', '->', '<='): "
        + "; ".join(f"{n}:{ln} {cs!r} {v!r}" for n, ln, cs, v in offenders))
