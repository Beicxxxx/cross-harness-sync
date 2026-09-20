"""B5 (N3, N4): the installer must not reformat or crash on the user's files.

  N3  There was no `newline=` anywhere in the write paths. `read_text()` translates
      every ending to LF and `write_text()`/`open(..., "a")` then writes
      `os.linesep`, so installing the protocol rewrote the caller's whole
      `AGENTS.md` in the installer's platform endings — measured on a cp936
      Windows host: an LF `AGENTS.md` went from 16 to 20 CRLF terminators, i.e.
      every line the user did not ask anyone to reformat, in a tool whose entire
      premise is one repo shared between a Windows and a macOS machine. The
      files this tool creates from scratch (`CLAUDE.md`, `.ai/protocol/VERSION`,
      the pruned config) came out CRLF while every `copy2`'d template is LF.
      Fix: read bytes, detect the file's own terminator, and write it back
      through one helper that always declares what it uses.

  N4  Existing user files were read as UTF-8 with no guard, so an `AGENTS.md`
      saved as GBK/ANSI — routine on a cp936 host — raised
      `UnicodeDecodeError` straight out of `main()`: a traceback *after*
      `.gitignore` had been appended, with no `CLAUDE.md` and no rollback, and
      the install was half-done with nothing naming it.

Assertions are over bytes and named printed lines. The structural test at the
end pins its own scan floor so it cannot go vacuous by matching nothing.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from helpers import SCRIPTS, run_python, scaffold

MODULE_NAME = "init_sync_b5"


def _load_init_sync():
    spec = importlib.util.spec_from_file_location(MODULE_NAME,
                                                 SCRIPTS / "init_sync.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def own_lines(n: int = 8) -> list[str]:
    return ["# Project rules"] + [
        f"- Rule {i}: keep the public API stable." for i in range(1, n)]


def block_lines() -> list[str]:
    return _load_init_sync().MANAGED_BLOCK.split("\n")


def joined(lines: list[str], term: str) -> bytes:
    return (term.join(lines) + term).encode("utf-8")


def crlf_counts(raw: bytes) -> tuple[int, int]:
    """(crlf terminators, lone-lf terminators)."""
    crlf = raw.count(b"\r\n")
    return crlf, raw.count(b"\n") - crlf


# --------------------------------------------------------------------------
# N3 — every file keeps the line endings it arrived with


def test_an_lf_agents_md_stays_pure_lf_after_install(repo):
    path = repo / "AGENTS.md"
    path.write_bytes(joined(own_lines(), "\n"))
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    raw = path.read_bytes()
    assert raw.count(b"\r\n") == 0, crlf_counts(raw)
    # Not merely "no CRLF": the exact bytes the append should have produced.
    assert raw == joined(own_lines(), "\n") + b"\n\n" + joined(
        block_lines(), "\n"), repr(raw[:160])


def test_the_block_follows_the_files_own_terminator_and_nothing_else_moves(repo):
    """A mixed file: the caller's inconsistency is theirs to keep.

    The dominant terminator here is LF, so the block is written with LF, and the
    two CRLF lines in the user's own text must survive with their CR.
    """
    user = joined(own_lines()[:6], "\n") + joined(own_lines()[6:], "\r\n")
    path = repo / "AGENTS.md"
    path.write_bytes(user)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    raw = path.read_bytes()
    assert raw.startswith(user), repr(raw[:160])
    assert raw == user + b"\n\n" + joined(block_lines(), "\n"), repr(raw[120:200])


def test_a_crlf_agents_md_keeps_crlf_and_a_second_install_changes_no_bytes(repo):
    """The in-place replace branch used to re-emit the whole file with
    `os.linesep`: re-running the installer on a file it already manages must be
    a no-op at byte level, on every platform."""
    path = repo / "AGENTS.md"
    path.write_bytes(joined(own_lines(), "\r\n"))
    first = scaffold(repo)
    assert first.rc == 0, first.stdout + first.stderr
    after_first = path.read_bytes()
    assert crlf_counts(after_first) == (8 + 16, 0), crlf_counts(after_first)
    assert after_first == joined(own_lines(), "\r\n") + b"\r\n\r\n" + joined(
        block_lines(), "\r\n"), repr(after_first[:160])

    second = scaffold(repo, "--force")
    assert second.rc == 0, second.stdout + second.stderr
    assert path.read_bytes() == after_first, "re-install churned line endings"
    assert any(ln.startswith("AGENTS.md: replaced managed block in place")
               for ln in second.lines), second.lines


def test_a_crlf_gitignore_gets_crlf_entries(repo):
    path = repo / ".gitignore"
    path.write_bytes(b"node_modules/\r\n*.log\r\n")
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    raw = path.read_bytes()
    assert raw.startswith(b"node_modules/\r\n*.log\r\n"), repr(raw)
    assert crlf_counts(raw)[1] == 0, crlf_counts(raw)
    assert ".ai/runtime/*" in raw.decode("utf-8").split("\r\n"), repr(raw)


@pytest.mark.parametrize("rel", ["CLAUDE.md", ".ai/protocol/VERSION"])
def test_files_the_installer_creates_are_lf_everywhere(repo, rel):
    """The templates it copies are LF; a file it writes itself came out CRLF on
    Windows, so a Windows-run install handed the mac side a 100%-changed file."""
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    raw = (repo / rel).read_bytes()
    assert raw, f"{rel} was not written"
    assert b"\r" not in raw, repr(raw[:80])
    assert raw.endswith(b"\n")


def test_pruning_the_budget_rewrites_the_config_as_lf(repo):
    """D18's prune edits the config the installer just copied in LF; it must not
    re-emit it as CRLF while it is at it."""
    res = scaffold(repo, "--no-agents-block")
    assert res.rc == 0, res.stdout + res.stderr
    raw = (repo / ".ai" / "sync_config.json").read_bytes()
    assert b"\r" not in raw, repr(raw[:80])
    assert '"AGENTS.md"' not in raw.decode("utf-8"), repr(raw[:120])
    assert any(ln.startswith("sync_config.json: dropped AGENTS.md budget")
               for ln in res.lines), res.lines


def test_every_text_write_in_the_installer_declares_its_terminator():
    """N3's root cause is structural, so the guard is structural: no
    `Path.write_text` and no text-mode file handle may rely on the platform
    default. Bytes writes are the only accepted form.

    The scan floor is pinned so the assertion cannot go vacuous by every call
    site being renamed away.
    """
    import re

    src = (SCRIPTS / "init_sync.py").read_text("utf-8")
    site = re.compile(r"(_write_text|_write_bytes_text|\.write_text"
                      r"|\.write_bytes|\bopen)\s*\(")
    seen = [ln.strip() for ln in src.splitlines() if site.search(ln)]
    assert len(seen) >= 8, seen
    relying_on_default = [ln for ln in seen
                          if ".write_text(" in ln
                          or (re.search(r"\bopen\s*\(", ln) and "newline=" not in ln)]
    assert not relying_on_default, relying_on_default


# --------------------------------------------------------------------------
# N4 — a non-UTF-8 user file is a named, non-destructive failure


def gbk_repo_file(repo: Path, rel: str = "AGENTS.md") -> bytes:
    raw = "# 项目规则\n\n请保持接口稳定，不要提交密钥。\n".encode("gbk")
    (repo / rel).write_bytes(raw)
    return raw


def test_a_gbk_agents_md_does_not_crash_the_install(repo):
    raw = gbk_repo_file(repo)
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")

    res = scaffold(repo)
    assert res.stdout_raw, "init exited without writing any output"
    assert "Traceback" not in res.stderr, res.stderr
    named = [ln for ln in res.lines if ln.startswith("AGENTS.md: ERROR")]
    assert named, res.lines
    assert "UTF-8" in named[0], named[0]
    assert res.rc == 1, res.stdout + res.stderr


def test_a_gbk_agents_md_is_left_untouched_and_the_rest_installs(repo):
    """Non-destructive means both halves: the unreadable file keeps its bytes,
    and the install is not left half-finished behind the crash it used to be."""
    raw = gbk_repo_file(repo)
    res = scaffold(repo)
    assert (repo / "AGENTS.md").read_bytes() == raw
    assert "untouched" in " ".join(res.lines).lower(), res.lines
    # The rest of the protocol really landed, so the run is re-runnable.
    for rel in (".ai/state/CURRENT.md", ".ai/sync_config.json",
                ".ai/scripts/sync_verify.py", "CLAUDE.md"):
        assert (repo / rel).is_file(), (rel, res.lines)
    # And it did not pretend to manage what it could not read.
    assert b"CROSS-HARNESS-SYNC" not in (repo / "AGENTS.md").read_bytes()
    assert (repo / ".ai" / "sync_config.json").read_bytes().count(
        b'"AGENTS.md": 65') == 1


def test_a_gbk_agents_md_failure_is_reported_again_on_rerun(repo):
    """The condition does not quietly become a success line after one run."""
    gbk_repo_file(repo)
    first = scaffold(repo)
    assert any(ln.startswith("AGENTS.md: ERROR") for ln in first.lines), first.lines
    assert first.rc == 1, first.stdout + first.stderr
    again = scaffold(repo)
    assert any(ln.startswith("AGENTS.md: ERROR") for ln in again.lines), again.lines
    assert again.rc == 1, again.stdout + again.stderr


def test_a_gbk_gitignore_is_still_a_named_warning(repo):
    """B4's `.gitignore` guard covers the same file shape; pinning it here so
    N4's fix cannot be read as replacing the only guard that existed."""
    raw = "# 忽略\nbuild/\n".encode("gbk")
    path = repo / ".gitignore"
    path.write_bytes(raw)
    res = scaffold(repo)
    assert path.read_bytes() == raw
    warned = [ln for ln in res.lines
              if ln.startswith("WARNING:") and ".gitignore" in ln]
    assert warned, res.lines
    assert not [ln for ln in res.lines if "gitignore: appended" in ln], res.lines
