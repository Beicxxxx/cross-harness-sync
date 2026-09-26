"""ISSUE-40 regression net: child output is never decoded by the locale codec.

ISSUE-40 (font-repertoire-expansion ledger, anchor `.ai/scripts/sync_verify.py`):
"sync_verify 在 GBK 区域下解码大段输出崩溃". The v2.0.0-lineage verifier ran
every child with `capture_output=True, text=True` and no `encoding=`, so on a
cp936 host a child's large report was decoded with the GBK codec, and one byte
sequence the codec cannot place killed the run. Measured on the Windows host
that filed the issue, the death is TWO-faced: the decode happens inside
subprocess's reader thread, so `run()` itself returns rc 0 with stdout=None
(the whole report is gone) and the operator sees a thread traceback followed by
a TypeError from the caller's very next line (`proc.stdout + proc.stderr`);
on POSIX the same call raises UnicodeDecodeError out of communicate(). Both
faces are pinned below, each on its own platform marker.

The shipped policy since d1628d7 is the opposite of every half of that
sentence: `run_argv` captures raw BYTES (the one subprocess call site in
`scripts/`), `decode()` is the only decoder (utf-8 + surrogateescape, cannot
raise), and `protect_stdio()` owns the way out. The tests reproduce the crash
on the old code shape (spelled with an explicit GBK codec, so the
reproduction is deterministic on a host whose preferred codec is not GBK),
prove the shipped path survives the same child under the same cp936 condition,
and structurally forbid a locale-decoding subprocess call site from coming
back — the same structural-guard shape N3 pinned for line endings in
test_install_encoding.py.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import SCRIPTS, load_ai_common, run_python

# What implicit `text=True` decoding does on the cp936 host that filed
# ISSUE-40, spelled explicitly so the reproduction does not depend on the
# host's own locale: the codec is named GBK, and `errors=` is deliberately
# NOT named — strict is the defect. The child's own text layer is pinned to
# UTF-8 so the child never crashes on its side; the fatal bytes still reach
# the pipe raw, the way a freeze-verifier report reaches the verifier.
DEFECT_DECODE = dict(capture_output=True, text=True, encoding="gbk",
                     timeout=600)
CHILD_TEXT_LAYER = dict(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

# GBK-fatal, measured: 0x90 is a legal GBK lead byte and 0x30 is a forbidden
# trail byte, so this pair cannot be placed by the codec at all —
# UnicodeDecodeError, "illegal multibyte sequence". (A lone 0x80 would NOT
# work: cp936 maps it to the euro sign.)
GBK_FATAL = b"\x90\x30"


def write_loud_child(repo: Path) -> Path:
    """The ISSUE-40 child: a large report ending in a GBK-fatal pair.

    Built as text and written as UTF-8 bytes, so the fixture does not depend
    on the writing process's own locale. The fatal pair is spelled as escapes
    in the child's source and reaches the pipe raw through
    `sys.stdout.buffer`, bypassing the child's text layer exactly like the
    freeze-verifier output that crashed the installed lineage.
    """
    lines = ["print('== 项目冻结检验报告 ==')"]
    lines += [f"print('模块 {i:03d}: 组件族覆盖率检验通过，冻结哈希一致。')"
              for i in range(200)]
    lines += ["import sys",
              "sys.stdout.buffer.write(b'tail ok \\x90\\x30 end\\n')"]
    child = repo / "loud_check.py"
    child.write_bytes("\n".join(lines).encode("utf-8") + b"\n")
    return child


# --------------------------------------------------------------------------
# The defect, reproduced (the red half of the pair: this is the crash
# ISSUE-40 reports, and these two tests pin that the suite understands both
# of its faces — if the crash shape ever changes, the pins say so instead of
# going vacuous).


@pytest.mark.windows
def test_issue40_repro_the_v2_lineage_run_shape_crashes_windows(tmp_path):
    """Windows face, measured: the GBK decode dies inside subprocess's reader
    thread, `run()` returns rc 0 with the whole report LOST (stdout=None),
    and the crash the operator files is the caller's next line."""
    child = write_loud_child(tmp_path)
    proc = subprocess.run([sys.executable, str(child)], cwd=str(tmp_path),
                          env=dict(os.environ, **CHILD_TEXT_LAYER),
                          **DEFECT_DECODE)
    assert proc.returncode == 0, proc.returncode
    assert proc.stdout is None, repr(proc.stdout)[-40:]
    with pytest.raises(TypeError):
        proc.stdout + proc.stderr  # check_extra's own `+`, v2.0.0 lineage


@pytest.mark.posix
def test_issue40_repro_the_v2_lineage_run_shape_crashes_posix(tmp_path):
    """POSIX face: no reader thread, so the same call raises out of
    communicate() instead of eating the report."""
    child = write_loud_child(tmp_path)
    with pytest.raises(UnicodeDecodeError):
        subprocess.run([sys.executable, str(child)], cwd=str(tmp_path),
                       env=dict(os.environ, **CHILD_TEXT_LAYER),
                       **DEFECT_DECODE)


# --------------------------------------------------------------------------
# The shipped defense: bytes in, one non-raising decoder, printable out.


def test_the_shipped_run_argv_returns_bytes_and_the_only_decoder_never_raises(
        tmp_path):
    ai_common = load_ai_common()
    child = write_loud_child(tmp_path)
    res = ai_common.run_argv(tmp_path, [sys.executable, str(child)], timeout=60)
    assert res.ok, res.err()
    assert isinstance(res.stdout, bytes), type(res.stdout)
    assert GBK_FATAL in res.stdout, res.stdout[-40:]
    text = ai_common.decode(res.stdout)  # utf-8 + surrogateescape: cannot raise
    assert "项目冻结检验报告" in text
    assert "tail ok " in text
    # And the evidence survives the way OUT, the way `record()` prints it:
    text.encode("utf-8", "backslashreplace")


def test_the_installed_verifier_survives_a_gbk_fatal_extra_check(ai_repo):
    """ISSUE-40 end to end, under the exact condition that crashed the old
    lineage: the verifier child runs with UTF-8 mode OFF and no
    PYTHONIOENCODING (its piped stdout would be cp936), one registered
    extra_check prints a large report ending in a GBK-fatal pair, and the run
    must still reach its summary with the check's verdict on the page.

    Against the v2.0.0-lineage `run()` this exact scenario died inside
    subprocess before any summary line; the assertions below are the net that
    keeps the bytes-capture policy from regressing.
    """
    write_loud_child(ai_repo)
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["extra_checks"] = [{"name": "loud check",
                            "cmd": [sys.executable, "loud_check.py"]}]
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    # Empty string is CPython's "unset": the child drops into cp936 exactly
    # like the host that filed ISSUE-40 (measured: preferred encoding cp936,
    # piped stdout gbk) no matter what this pytest process inherited.
    res = run_python(ai_repo / ".ai" / "scripts" / "sync_verify.py",
                     cwd=ai_repo,
                     env={"PYTHONUTF8": "", "PYTHONIOENCODING": ""})
    assert "Traceback" not in res.stderr, res.stderr
    assert "Traceback" not in res.stdout, res.stdout
    assert res.rc == 0, res.stdout + res.stderr
    verdicts = [ln for ln in res.lines
                if ln.startswith("[PASS] loud check")
                or ln.startswith("[FAIL] loud check")]
    assert verdicts, res.lines
    assert any(ln.startswith("== ") and "checks passed" in ln
               for ln in res.lines), res.lines


# --------------------------------------------------------------------------
# The structural guard: the defect must not be able to come back silently.


def test_no_shipped_script_decodes_child_output_with_the_locale_codec():
    """No shipped script may run a subprocess in a mode that decodes its
    output with the locale codec. `text=True` / `universal_newlines=True` as
    a CALL KEYWORD is that defect (an unset codec means the ANSI code page);
    a non-UTF-8 codec named anywhere in `scripts/` is the same defect spelled
    explicitly. The patterns require call context (a `,`/`)`/end-of-line
    after the value, no backtick, no comment) so the docstrings that NAME the
    defect as the reason this policy exists stay documentation, not
    offenders. The scan floor keeps the assertion from going vacuous if every
    call site is ever renamed away — the shape `test_install_encoding.py`
    pinned for N3.
    """
    names = ["ai_common.py", "sync_verify.py", "checkpoint.py", "init_sync.py"]
    forbidden = [re.compile(p) for p in (
        r"(?<![`'\"\w])(?:text|universal_newlines)\s*=\s*True\b\s*(?:[,)]|$)",
        r"\bencoding\s*=\s*[\"'](?!utf-8)",
    )]
    call = re.compile(r"subprocess\.(?:run|Popen|check_output|check_call)\s*\(")
    sites: dict[str, int] = {}
    offenders: list[str] = []
    for name in names:
        src = (SCRIPTS / name).read_text("utf-8")
        sites[name] = 0
        for lineno, ln in enumerate(src.splitlines(), 1):
            if ln.lstrip().startswith("#"):
                continue
            if call.search(ln):
                sites[name] += 1
            for pat in forbidden:
                if pat.search(ln):
                    offenders.append(f"{name}:{lineno}: {ln.strip()}")
    assert sites["ai_common.py"] >= 1, \
        "scan floor lost: no subprocess call site in ai_common.py"
    assert sum(sites.values()) >= 1, \
        "scan floor lost: no subprocess call site found in scripts/"
    assert not offenders, offenders
