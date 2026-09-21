"""B5 (N1/D27, N2, N5): the install must not break the budget it installs.

Three defects, all about what `init_sync.py` leaves behind in a repo that
already had files of its own:

  N1/D27  The managed block adds exactly 16 lines, so any pre-existing
          `AGENTS.md` of 50+ lines is pushed past the configured 65-line cap by
          *installing the tool that sets the cap*: measured 60 -> 76.
          `sync_verify.py` then reports `[FAIL] budget AGENTS.md` forever while
          init's own next-steps block says "should be all green". This is the
          same permanently-red class as D18, reached from the other direction.
          Fix: raise the configured AGENTS.md cap at install time by the block's
          line count (a derived, idempotent value, never a per-run increment) and
          say so in the printed result.
  N2      Both markers were matched by exact string including `v:1`, so one
          marker edit turned every later run into another appended block:
          +16 lines per run, unbounded, duplicating contradictory protocol text
          into the file every harness auto-loads. Fix: match the marker family,
          collapse duplicates, refuse to append beside an unterminated block.
  N5      `GITIGNORE_LINES` omitted `__pycache__/` and `*.pyc`, so the
          `git add -A && git push` the installed instructions tell every agent
          to run at close-out committed the bytecode the installed scripts
          generate — and pushed it to the other machine.
  N6      The managed block and `templates/SYNC_PROMPT.md` still taught a bare
          `--unlock`, which Task 5 turns into exit 2: the installed canonical
          instructions would order every agent to run a command the installed
          tool refuses.

Every assertion here is over file content, a config value, a `git` listing or a
named printed line. Nothing asserts on the absence of subprocess output.
"""
from __future__ import annotations

import json
from pathlib import Path

from helpers import SCRIPTS, git, run_python, scaffold

OWN_AGENTS_CAP = 65
BLOCK_SPAN = 16  # two blank separator lines + the 14-line managed block


def budgets(repo: Path) -> dict:
    cfg = json.loads((repo / ".ai" / "sync_config.json").read_text("utf-8"))
    return cfg.get("budgets", {})


def verify(repo: Path):
    return run_python(repo / ".ai" / "scripts" / "sync_verify.py", cwd=repo)


def agents_lines(n: int) -> list[str]:
    """A caller-written AGENTS.md of exactly `n` lines: no managed block, no
    copy of the shipped template, nothing that reads as template prose."""
    lines = ["# Project rules"]
    while len(lines) < n:
        lines.append(f"- Rule {len(lines)}: keep the public API stable.")
    return lines


def write_agents(repo: Path, n: int) -> Path:
    path = repo / "AGENTS.md"
    path.write_text("\n".join(agents_lines(n)) + "\n", encoding="utf-8")
    return path


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def marker_count(path: Path, needle: str) -> int:
    return path.read_text(encoding="utf-8").count(needle)


# --------------------------------------------------------------------------
# N1 / D27 — the block has to fit inside the budget it installs


def test_install_leaves_a_58_line_agents_md_inside_its_own_budget(repo):
    """D27: 58 lines of the caller's rules + the block used to verify red forever."""
    write_agents(repo, 58)
    assert line_count(repo / "AGENTS.md") == 58

    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    text = (repo / "AGENTS.md").read_text("utf-8")
    assert text.splitlines()[:58] == agents_lines(58), text
    assert line_count(repo / "AGENTS.md") == 58 + BLOCK_SPAN, line_count(
        repo / "AGENTS.md")
    assert budgets(repo).get("AGENTS.md") == OWN_AGENTS_CAP + BLOCK_SPAN, budgets(
        repo)
    out = verify(repo)
    assert out.rc == 0, out.stdout + out.stderr
    assert any(ln.startswith("[PASS] budget AGENTS.md")
               and f"(cap {OWN_AGENTS_CAP + BLOCK_SPAN})" in ln
               for ln in out.lines), out.lines


def test_the_budget_raise_is_named_in_the_printed_result(repo):
    """Silently moving the goalposts is as bad as leaving them wrong: the run has
    to say which number changed, by how much, and what it was for."""
    write_agents(repo, 58)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    lines = [ln for ln in res.lines if ln.startswith("sync_config.json:")]
    assert lines, res.lines
    bump = [ln for ln in lines if "AGENTS.md budget" in ln]
    assert bump, res.lines
    said = bump[0]
    assert f"{OWN_AGENTS_CAP} -> {OWN_AGENTS_CAP + BLOCK_SPAN}" in said, said
    assert str(BLOCK_SPAN) in said, said
    # The cap on the caller's own text is not what moved.
    assert f"{OWN_AGENTS_CAP}-line" in said, said


def test_a_repo_the_block_still_cannot_fit_is_named_not_promised_green(repo):
    """The raise covers the block, it does not launder the caller's own overrun.

    A 200-line AGENTS.md is over budget on its own content, so the install has
    to name that instead of printing its unconditional "should be all green"
    claim over a verification that is about to fail.
    """
    write_agents(repo, 200)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    warned = [ln for ln in res.lines
              if ln.startswith("WARNING:") and "AGENTS.md" in ln and "budget" in ln]
    assert warned, res.lines
    out = verify(repo)
    assert out.rc == 1, out.stdout
    assert any(ln.startswith("[FAIL] budget AGENTS.md") for ln in out.lines), \
        out.lines


def test_the_raise_is_idempotent_across_reinstalls(repo):
    """The cap is derived from the block, never incremented per run — otherwise
    `--force` on an upgrade walks the budget to infinity."""
    write_agents(repo, 58)
    first = scaffold(repo)
    assert first.rc == 0, first.stdout
    cap = budgets(repo).get("AGENTS.md")
    assert cap == OWN_AGENTS_CAP + BLOCK_SPAN, cap

    for _ in range(2):
        again = scaffold(repo, "--force")
        assert again.rc == 0, again.stdout + again.stderr
        assert budgets(repo).get("AGENTS.md") == cap, budgets(repo)
        assert line_count(repo / "AGENTS.md") == 58 + BLOCK_SPAN
        assert marker_count(repo / "AGENTS.md", "BEGIN CROSS-HARNESS-SYNC") == 1
        assert any("managed block" in ln and "already" in ln
                   for ln in again.lines), again.lines
    out = verify(repo)
    assert out.rc == 0, out.stdout + out.stderr


def test_no_budget_change_when_the_full_template_is_installed(repo):
    """No block was added, so nothing may be excused: a repo with no AGENTS.md
    gets the template (61 lines, measured from `templates/agents.md` at
    `ef749b9`) under the shipped 65-line cap.

    Nothing pins that 61 — deliberately. The protection is indirect and it is
    real: this test installs the shipped template and requires `[PASS] budget
    AGENTS.md` at rc 0, so any edit that pushes the template past the 65-line
    default turns a permanent red on every install, with 4 lines of headroom.
    A literal length assertion here would only add a second thing to update
    when the template legitimately changes.
    """
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert budgets(repo).get("AGENTS.md") == OWN_AGENTS_CAP, budgets(repo)
    assert not [ln for ln in res.lines if ln.startswith("sync_config.json:")], \
        res.lines
    out = verify(repo)
    assert out.rc == 0, out.stdout + out.stderr
    assert any(ln.startswith("[PASS] budget AGENTS.md")
               and "(cap 65)" in ln for ln in out.lines), out.lines


def test_scripts_only_never_touches_the_budget(ai_repo):
    """`--scripts-only` promises to write nothing but `.ai/scripts/`; the budget
    line lives in the config, so it must not move either."""
    before = (ai_repo / ".ai" / "sync_config.json").read_text("utf-8")
    res = scaffold(ai_repo, "--force", "--scripts-only")
    assert res.rc == 0, res.stdout + res.stderr
    assert (ai_repo / ".ai" / "sync_config.json").read_text("utf-8") == before
    assert any(ln.startswith("wrote:") and "sync_verify.py" in ln
               for ln in res.lines), res.lines


# --------------------------------------------------------------------------
# N2 — marker drift must not duplicate the block


def test_a_drifted_marker_does_not_duplicate_the_block(repo):
    """`v:1` was part of the matched literal, so retyping one character turned
    every later install into another full copy of the protocol text."""
    write_agents(repo, 8)
    assert scaffold(repo).rc == 0
    path = repo / "AGENTS.md"
    text = path.read_text("utf-8")
    assert "BEGIN CROSS-HARNESS-SYNC v:1" in text
    path.write_text(text.replace("BEGIN CROSS-HARNESS-SYNC v:1",
                                 "BEGIN CROSS-HARNESS-SYNC v:2"),
                    encoding="utf-8")

    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert line_count(path) == 8 + BLOCK_SPAN, line_count(path)
    assert marker_count(path, "BEGIN CROSS-HARNESS-SYNC") == 1, path.read_text("utf-8")
    assert marker_count(path, "END CROSS-HARNESS-SYNC") == 1, path.read_text("utf-8")
    assert marker_count(path, "## Cross-Harness Continuity (managed block") == 1
    assert budgets(repo).get("AGENTS.md") == OWN_AGENTS_CAP + BLOCK_SPAN
    assert any("AGENTS.md:" in ln for ln in res.lines), res.lines
    out = verify(repo)
    assert out.rc == 0, out.stdout + out.stderr


def test_whitespace_drift_in_the_markers_is_normalised_too(repo):
    """A merge conflict or a formatter touches the comment, not just the tag."""
    write_agents(repo, 8)
    assert scaffold(repo).rc == 0
    path = repo / "AGENTS.md"
    text = path.read_text("utf-8")
    text = text.replace("<!-- BEGIN CROSS-HARNESS-SYNC v:1 -->",
                        "<!--    BEGIN CROSS-HARNESS-SYNC   v:9   -->")
    text = text.replace("<!-- END CROSS-HARNESS-SYNC -->",
                        "<!-- END CROSS-HARNESS-SYNC -->  ")
    path.write_text(text, encoding="utf-8")

    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert marker_count(path, "BEGIN CROSS-HARNESS-SYNC") == 1, path.read_text("utf-8")
    assert line_count(path) == 8 + BLOCK_SPAN, line_count(path)


def test_duplicated_blocks_collapse_into_one_without_losing_user_text(repo):
    """The growth already happened in the wild (three runs, three blocks): the
    fix has to fold them back and keep the caller's own lines around them.

    Text *between* two blocks is preserved — it may be the caller's — so the
    collapse is pinned as "one block remains and the file is back to the size a
    single install produces", not as a byte-for-byte rewrite.
    """
    write_agents(repo, 8)
    assert scaffold(repo).rc == 0
    path = repo / "AGENTS.md"
    lines = path.read_text("utf-8").splitlines()
    begin = next(k for k, ln in enumerate(lines) if ln.startswith("<!-- BEGIN"))
    end = next(k for k, ln in enumerate(lines) if ln.startswith("<!-- END"))
    assert begin == 10 and end == 23, lines[:12]
    drifted = [lines[begin].replace("v:1", "v:2")] + lines[begin + 1:end + 1]
    path.write_text("\n".join(lines) + "\n" + "\n".join(drifted) + "\n",
                    encoding="utf-8")
    assert marker_count(path, "BEGIN CROSS-HARNESS-SYNC") == 2
    grown = line_count(path)
    assert grown == 8 + BLOCK_SPAN + 14, grown

    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    after = path.read_text("utf-8").splitlines()
    assert marker_count(path, "BEGIN CROSS-HARNESS-SYNC") == 1, after
    assert marker_count(path, "END CROSS-HARNESS-SYNC") == 1, after
    assert sum("Cross-Harness Continuity (managed block" in ln
               for ln in after) == 1, after
    assert after[:8] == agents_lines(8), after
    assert len(after) == 8 + BLOCK_SPAN, after
    assert any("collaps" in ln.lower() for ln in res.lines), res.lines
    out = verify(repo)
    assert out.rc == 0, out.stdout + out.stderr


def test_an_unterminated_block_is_a_named_refusal_not_an_append(repo):
    """A damaged END marker used to send the install down the append branch,
    which is how a single merge conflict became two live protocol blocks."""
    write_agents(repo, 8)
    assert scaffold(repo).rc == 0
    path = repo / "AGENTS.md"
    before = path.read_text("utf-8")
    damaged = before.replace("<!-- END CROSS-HARNESS-SYNC -->",
                             "<!-- damaged by a merge conflict -->")
    assert damaged != before
    path.write_text(damaged, encoding="utf-8")

    res = scaffold(repo)
    assert any(ln.startswith("AGENTS.md: ERROR") for ln in res.lines), res.lines
    assert res.rc == 1, res.stdout + res.stderr
    # Non-destructive: nothing was appended beside the unterminated block and
    # the caller's file is byte-for-byte what it was before the run.
    assert path.read_text("utf-8") == damaged
    assert marker_count(path, "BEGIN CROSS-HARNESS-SYNC") == 1
    assert "damaged by a merge conflict" in path.read_text("utf-8")


# --------------------------------------------------------------------------
# N6 — the installed instructions must not teach a command the tool refuses


UNLOCK_SITES = (
    SCRIPTS / "init_sync.py",
    SCRIPTS.parent / "templates" / "AGENTS.md",
    SCRIPTS.parent / "templates" / "SYNC_PROMPT.md",
    SCRIPTS.parent / "templates" / "ROLE_POLICY.md",
)


def test_no_installed_instruction_prints_a_bare_unlock():
    """Task 5 makes a bare `--unlock` exit 2 unless the holder is named, so the
    text this tool writes into the user's repo has to name the agent too.

    The scan is bounded to the files this batch owns — the same bare form is
    still in README.md / SKILL.md / reference.md, which are the doc lane's to
    change (reported in batch-B5-report.md).
    """
    hits = []
    for path in UNLOCK_SITES:
        text = path.read_text("utf-8")
        for ln in text.splitlines():
            if "--unlock" in ln:
                hits.append((path.name, ln.strip()))
    assert len(hits) >= 2, hits
    bare = [h for h in hits if "--agent" not in h[1] and "--force" not in h[1]]
    assert not bare, bare


def test_the_installed_sync_prompt_carries_the_agent_scoped_unlock(ai_repo):
    text = (ai_repo / ".ai" / "SYNC_PROMPT.md").read_text("utf-8")
    assert "--unlock --agent" in text, text
    assert "release the lock (`--unlock`)" not in text, text


def test_the_managed_block_carries_the_agent_scoped_unlock(repo):
    write_agents(repo, 8)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    text = (repo / "AGENTS.md").read_text("utf-8")
    assert "--unlock --agent" in text, text
    assert line_count(repo / "AGENTS.md") == 8 + BLOCK_SPAN, line_count(
        repo / "AGENTS.md")


# --------------------------------------------------------------------------
# N5 — the protocol's own bytecode must not reach the shared repo


def test_gitignore_covers_the_caches_the_installed_scripts_create(repo):
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    lines = (repo / ".gitignore").read_text("utf-8").splitlines()
    assert "__pycache__/" in lines, lines
    assert "*.pyc" in lines, lines
    assert lines.count("# cross-harness-sync") == 1, lines


def test_a_real_pycache_from_the_installed_scripts_is_not_staged(repo):
    """The behaviour that matters: the close-out `git add -A` the installed
    instructions order every agent to run must not pick the junk up."""
    scaffold(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "install")
    cache = repo / ".ai" / "scripts" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "ai_common.cpython-314.pyc").write_bytes(b"\xf0\x0d junk")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "helpers.cpython-314.pyc").write_bytes(b"junk")
    (repo / "loose.pyc").write_bytes(b"junk")
    # The control: a real file in the same directory the junk sits in, so an
    # empty staging list can only mean "ignored", never "git add did nothing".
    (repo / "KEEPME.txt").write_text("real work\n", encoding="utf-8")

    git(repo, "add", "-A")
    staged = git(repo, "diff", "--cached", "--name-only").splitlines()
    assert "KEEPME.txt" in staged, staged
    assert not [p for p in staged if p.endswith(".pyc") or "__pycache__" in p], staged
    assert git(repo, "check-ignore", "-q", ".ai/scripts/__pycache__/x.pyc") == ""


def test_gitignore_entries_are_still_appended_only_when_absent(repo):
    """N5 must not regress Task 9's append-only-what-is-missing behaviour."""
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\nnode_modules/\n",
                                     encoding="utf-8")
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    lines = (repo / ".gitignore").read_text("utf-8").splitlines()
    assert lines.count("__pycache__/") == 1, lines
    assert lines.count("*.pyc") == 1, lines
    assert "node_modules/" in lines, lines
    appended = [ln for ln in res.lines if ln.startswith(".gitignore: appended")]
    assert appended, res.lines
    assert int(appended[0].split("appended ")[1].split(" ")[0]) == len(lines) - 3, \
        (appended, lines)
    again = scaffold(repo)
    assert any(ln == ".gitignore: already up to date" for ln in again.lines), \
        again.lines
    assert (repo / ".gitignore").read_text("utf-8").splitlines() == lines


def test_the_installed_agents_template_tells_the_truth_about_the_cap():
    """templates/AGENTS.md states the cap in prose; it must not promise a number
    the installer then contradicts."""
    text = (SCRIPTS.parent / "templates" / "AGENTS.md").read_text("utf-8")
    assert "65 lines" in text, text
    assert "managed block" in text, text
