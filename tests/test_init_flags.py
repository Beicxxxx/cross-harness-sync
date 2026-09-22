"""Task 9 (batch B4): install flags and .gitignore report the truth (D17, D18).

  D17 `update_gitignore` decided *whether* to write by looking for one absent
      line but then appended ALL five lines, so a repo that already listed
      `.env` got a second `.env` and a second block — while printing
      `appended 4 entries` for five lines it wrote.
  D18 `--no-agents-block` skipped AGENTS.md but still wrote a CLAUDE.md pointer
      to it and left `"AGENTS.md": 65` in the config, so `sync_verify.py` was
      red forever and init's own closing line ("should be all green") lied.

D18 is fixed by pruning the budget entry, NOT by downgrading a missing budget
to WARN: AGENTS.md appears in no required-file list, so that would leave it
monitored by nothing. Every assertion here is over a file's content or a named
printed line, never over the absence of output.
"""
from __future__ import annotations

import json
from pathlib import Path

from helpers import load_script, run_python, scaffold

GITIGNORE_MARKER = "# cross-harness-sync"


def _load_init_sync():
    return load_script("init_sync.py", "init_sync_t9", keep=True)


def budgets(repo: Path) -> dict:
    cfg = json.loads((repo / ".ai" / "sync_config.json").read_text("utf-8"))
    return cfg.get("budgets", {})


def verify(repo: Path):
    return run_python(repo / ".ai" / "scripts" / "sync_verify.py", cwd=repo)


def ignore_line(res) -> str:
    lines = [ln for ln in res.lines if ln.startswith(".gitignore:")]
    assert len(lines) == 1, res.lines
    return lines[0]


def reported_count(line: str) -> int:
    assert "appended " in line, line
    return int(line.split("appended ")[1].split(" ")[0])


# --------------------------------------------------------------------------
# D17


def test_gitignore_appends_only_absent_lines(ai_repo):
    (ai_repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    res = scaffold(ai_repo)
    assert res.rc == 0, res.stdout
    text = (ai_repo / ".gitignore").read_text("utf-8")
    assert text.count(".env\n") == 1, repr(text)
    assert text.count(GITIGNORE_MARKER) == 1, repr(text)
    line = ignore_line(res)
    n = reported_count(line)
    assert n == len(text.splitlines()) - 1, (line, text)


def test_gitignore_keeps_untouched_entries_and_custom_lines(ai_repo):
    """The lines that were already there — including the caller's own — survive
    in their original order, and only the protocol block is added below them."""
    before = ".env\nbuild/\n"
    (ai_repo / ".gitignore").write_text(before, encoding="utf-8")
    res = scaffold(ai_repo)
    assert res.rc == 0, res.stdout
    text = (ai_repo / ".gitignore").read_text("utf-8")
    assert text.startswith(before), repr(text)
    assert text.count("build/\n") == 1, repr(text)
    assert text.count(".ai/runtime/*\n") == 1, repr(text)
    # `.env` was present, so it must not be re-added: 7 lines were (marker,
    # runtime glob, lock exception, the D16 `.gitkeep` exception, blank
    # separator, and the two bytecode-cache entries N5 added).
    assert reported_count(ignore_line(res)) == 7, ignore_line(res)
    assert text.splitlines().count(".env") == 1, repr(text)


def test_gitignore_message_is_a_noop_when_complete(ai_repo):
    scaffold(ai_repo)
    before = (ai_repo / ".gitignore").read_text("utf-8")
    res = scaffold(ai_repo)
    assert "already up to date" in res.stdout
    assert (ai_repo / ".gitignore").read_text("utf-8") == before


def test_gitignore_gets_a_newline_before_the_block(repo):
    """A file with no trailing newline must not end up with a glued-together
    first entry, which would silently ignore nothing."""
    (repo / ".gitignore").write_text("dist", encoding="utf-8")
    res = scaffold(repo)
    assert res.rc == 0, res.stdout
    lines = (repo / ".gitignore").read_text("utf-8").splitlines()
    assert lines[0] == "dist", lines
    assert GITIGNORE_MARKER in lines, lines
    assert reported_count(ignore_line(res)) == len(lines) - 1, (lines, res.lines)


def test_update_gitignore_reports_what_it_wrote(tmp_path):
    """The produced interface: update_gitignore(root, wanted) -> str, and the
    count in the string is the number of lines that hit the file."""
    mod = _load_init_sync()
    (tmp_path / ".gitignore").write_text("keepme\n", encoding="utf-8")
    msg = mod.update_gitignore(tmp_path, ["keepme", ".new"])
    lines = (tmp_path / ".gitignore").read_text("utf-8").splitlines()
    assert msg == ".gitignore: appended 1 entries", msg
    assert lines == ["keepme", ".new"], lines
    assert mod.update_gitignore(tmp_path, ["keepme", ".new"]) \
        == ".gitignore: already up to date"


# --------------------------------------------------------------------------
# D18


def test_no_agents_block_installs_cleanly(repo):
    """D18: verify used to be permanently red after this flag."""
    res = scaffold(repo, "--no-agents-block")
    assert res.rc == 0, res.stdout
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / "CLAUDE.md").exists()
    cfg = json.loads((repo / ".ai" / "sync_config.json").read_text("utf-8"))
    assert "AGENTS.md" not in cfg.get("budgets", {}), cfg
    verify_res = verify(repo)
    assert verify_res.rc == 0, verify_res.stdout + verify_res.stderr
    # The degradation is named, not silent: the line says what was dropped and
    # why, and the verifier says what it actually checked.
    assert any("AGENTS.md" in ln and "budget" in ln for ln in res.lines), res.lines
    assert any(ln.startswith("[PASS] required") for ln in verify_res.lines), \
        verify_res.lines


def test_no_agents_block_prune_is_named_and_idempotent(repo):
    """The prune prints what it dropped, and a second run says there is nothing
    left to drop rather than inventing a change."""
    first = scaffold(repo, "--no-agents-block")
    assert first.rc == 0, first.stdout
    assert any(ln.startswith("sync_config.json: dropped AGENTS.md budget")
               for ln in first.lines), first.lines
    assert "AGENTS.md" not in budgets(repo), budgets(repo)

    second = scaffold(repo, "--no-agents-block")
    assert second.rc == 0, second.stdout
    assert any(ln.startswith("sync_config.json: no AGENTS.md budget to drop")
               for ln in second.lines), second.lines
    assert "AGENTS.md" not in budgets(repo), budgets(repo)
    out = verify(repo)
    assert out.rc == 0, out.stdout + out.stderr


def test_budget_survives_when_the_repo_has_its_own_agents_md(repo):
    """--no-agents-block means "do not touch AGENTS.md", not "delete its budget".

    A repo that already has the file must stay monitored by the verifier, so
    the budget is kept and the reason is printed.
    """
    (repo / "AGENTS.md").write_text("# Project rules\n\nBe kind.\n", "utf-8")
    res = scaffold(repo, "--no-agents-block")
    assert res.rc == 0, res.stdout
    assert (repo / "AGENTS.md").read_text("utf-8") == "# Project rules\n\nBe kind.\n"
    assert budgets(repo).get("AGENTS.md") == 65, budgets(repo)
    assert any(ln.startswith("sync_config.json: kept AGENTS.md budget")
               for ln in res.lines), res.lines
    out = verify(repo)
    assert out.rc == 0, out.stdout + out.stderr
    assert any(ln.startswith("[PASS] budget AGENTS.md") for ln in out.lines), out.lines


def test_force_after_no_agents_block_restores_the_budget_with_the_file(repo):
    """The two flag paths must not leave each other's invariant broken.

    `--no-agents-block` prunes the AGENTS.md budget because it creates no
    AGENTS.md. A later default `--force` DOES create the file, so it has to
    bring the budget back — which only works while the pruned config is still
    recognisably the untouched template rather than a reflowed JSON dump.
    """
    first = scaffold(repo, "--no-agents-block")
    assert first.rc == 0, first.stdout
    assert "AGENTS.md" not in budgets(repo), budgets(repo)

    res = scaffold(repo, "--force")
    assert res.rc == 0, res.stdout
    assert budgets(repo).get("AGENTS.md") == 65, budgets(repo)
    assert (repo / "AGENTS.md").exists(), res.lines
    assert any(ln.startswith("wrote:") and "sync_config.json" in ln
               for ln in res.lines), res.lines
    out = verify(repo)
    assert out.rc == 0, out.stdout + out.stderr
    assert any(ln.startswith("[PASS] budget AGENTS.md") for ln in out.lines), \
        out.lines


def test_default_install_still_budgets_agents_md(ai_repo):
    cfg = json.loads((ai_repo / ".ai" / "sync_config.json").read_text("utf-8"))
    assert cfg["budgets"]["AGENTS.md"] == 65, cfg


def test_default_install_still_points_claude_at_agents(ai_repo):
    """The other half of D18: the pointer is only written when the file is."""
    claude = (ai_repo / "CLAUDE.md").read_text("utf-8")
    assert "AGENTS.md" in claude, claude
    assert (ai_repo / "AGENTS.md").exists()
    out = verify(ai_repo)
    assert out.rc == 0, out.stdout + out.stderr
