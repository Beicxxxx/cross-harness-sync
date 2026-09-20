"""Task 8 (batch B4): scaffolding must not destroy live state (D7, D24).

Two defects in `init_sync.py`, both about writing where the user's work lives:

  D7  `--force` replaced a live `.ai/state/CURRENT.md` (and TASK/DECISIONS and
      the config) with an empty template while refreshing the scripts. In a tool
      where `.ai/state` *is* the work state, that is data loss.
  D24 `copy_file` never checked that its source existed, so one deleted template
      aborted the install mid-way with a traceback and a half-built tree.

The guard, not the flag, is the thing under test: `test_force_*` therefore
compares FILE CONTENT, so simply deleting the "is this an untouched template?"
heuristic breaks them, while a merely misspelled flag would not. Everything is
asserted positively (a named line we expect to see, a file we expect to hold
what we wrote) rather than by "not in stdout", which an empty run satisfies.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from helpers import REPO_ROOT, SCRIPTS, TEMPLATES_DIR, make_repo, run_python, scaffold

# Every destination init owns that holds the caller's work rather than the
# skill's own files. Pinned here as a literal list (not imported from
# init_sync) so the implementation cannot quietly narrow its own protection.
PROTECTED = (
    ".ai/state/CURRENT.md",
    ".ai/state/TASK.md",
    ".ai/state/BLOCKERS.md",
    ".ai/state/ROLE_POLICY.md",
    ".ai/state/DECISIONS.md",
    ".ai/state/DECISIONS_INDEX.md",
    ".ai/handoff/LATEST.md",
    ".ai/handoff/NEXT_PROMPT.md",
    ".ai/SYNC_PROMPT.md",
    ".ai/sync_config.json",
)


def _load_init_sync():
    spec = importlib.util.spec_from_file_location("init_sync_t8",
                                                  SCRIPTS / "init_sync.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def edited(repo: Path, rel: str, text: str) -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def read(repo: Path, rel: str) -> str:
    return (repo / rel).read_text("utf-8")


def template_text(rel: str) -> str:
    return (TEMPLATES_DIR / rel).read_text("utf-8")


def staged_skill(tmp_path: Path, *missing_templates: str) -> Path:
    """A throwaway copy of this skill with the named templates deleted.

    The real `templates/` is shared with the other lanes and with git, so the
    deleted-template scenario is built in a copy: `SKILL_DIR` is derived from
    `__file__`, so the copy is a working skill missing one file.
    """
    stage = tmp_path / "skill"
    shutil.copytree(REPO_ROOT, stage, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", ".pytest_cache", ".superpowers", "docs", "tests"))
    for rel in missing_templates:
        (stage / rel).unlink()
    return stage


# --------------------------------------------------------------------------
# D7: --force must not destroy live state


def test_force_does_not_overwrite_edited_state(ai_repo):
    """D7: --force used to replace live CURRENT.md with an empty template."""
    keep = "# Current state\n\nReal work in progress, 47 lines of it.\n"
    edited(ai_repo, ".ai/state/CURRENT.md", keep)
    res = scaffold(ai_repo, "--force")
    assert res.rc == 0, res.stdout
    assert (ai_repo / ".ai" / "state" / "CURRENT.md").read_text(
        "utf-8") == keep
    assert any(ln.startswith("KEEP (edited)") for ln in res.lines), res.lines


def test_force_keeps_a_state_file_whose_placeholders_were_filled(ai_repo):
    """The realistic edit: the template is still there, one line is now work.

    A heuristic that only asks "does this file still contain `<...>`?" calls
    this an untouched template and destroys it, so this case is pinned
    separately from the wholesale rewrite above.
    """
    live = template_text("CURRENT.md").replace("<one line>",
                                               "wave 1a batch B4 in review", 1)
    assert live != template_text("CURRENT.md")
    edited(ai_repo, ".ai/state/CURRENT.md", live)
    res = scaffold(ai_repo, "--force")
    assert res.rc == 0, res.stdout
    assert read(ai_repo, ".ai/state/CURRENT.md") == live, read(
        ai_repo, ".ai/state/CURRENT.md")
    assert any(ln.startswith("KEEP (edited)") and "CURRENT.md" in ln
               for ln in res.lines), res.lines
    # ...and the guard is per file: the untouched siblings still refresh.
    assert any(ln.startswith("wrote:") and "TASK.md" in ln
               for ln in res.lines), res.lines


def test_force_still_refreshes_untouched_templates(ai_repo):
    res = scaffold(ai_repo, "--force")
    assert any(ln.startswith("wrote:") and "TASK.md" in ln
               for ln in res.lines), res.lines
    # Nothing on an untouched install is reported as edited work.
    assert not [ln for ln in res.lines if ln.startswith("KEEP (edited)")], res.lines
    for rel in PROTECTED:
        name = rel.rsplit("/", 1)[-1]
        assert any(ln.startswith("wrote:") and name in ln
                   for ln in res.lines), (rel, res.lines)


def test_clobber_is_the_explicit_escape_hatch(ai_repo):
    """The only way to overwrite edited state is the flag that warns about it."""
    keep = "# Current state\n\nReal work in progress, 47 lines of it.\n"
    edited(ai_repo, ".ai/state/CURRENT.md", keep)
    res = scaffold(ai_repo, "--clobber")
    assert res.rc == 0, res.stdout
    assert read(ai_repo, ".ai/state/CURRENT.md") == template_text("CURRENT.md")
    assert any(ln.startswith("wrote:") and "CURRENT.md" in ln
               for ln in res.lines), res.lines
    assert any("commit" in ln for ln in res.lines), res.lines


# --------------------------------------------------------------------------
# --scripts-only: refresh the plumbing, touch nothing else


def test_scripts_only_leaves_state_alone(ai_repo):
    keep = "# Current state\n\nwork\n"
    edited(ai_repo, ".ai/state/CURRENT.md", keep)
    edited(ai_repo, ".ai/sync_config.json", '{"budgets": {"x": 1}}')
    ignore_before = read(ai_repo, ".gitignore")
    res = scaffold(ai_repo, "--force", "--scripts-only")
    assert res.rc == 0, res.stdout
    assert (ai_repo / ".ai" / "state" / "CURRENT.md").read_text("utf-8") == keep
    assert (ai_repo / ".ai" / "sync_config.json").read_text("utf-8") \
        == '{"budgets": {"x": 1}}'
    assert read(ai_repo, ".gitignore") == ignore_before
    assert any("scripts" in ln for ln in res.lines), res.lines
    for name in ("ai_common.py", "checkpoint.py", "sync_verify.py"):
        assert any(ln.startswith("wrote:") and name in ln
                   for ln in res.lines), res.lines
    # Positive half of "only": every file it claims to have written is plumbing.
    written = [ln.split("wrote:", 1)[1].strip()
               for ln in res.lines if ln.startswith("wrote:")]
    stray = [w for w in written
             if Path(w).parent.name != "scripts" and Path(w).name != "VERSION"]
    assert not stray, stray


def test_scripts_only_refreshes_without_needing_force(ai_repo):
    """V-3: the flag does the job its docstring and its `--help` both promise.

    RED at `2796c2f`, measured by the cross-lane reviewer and re-measured here:
    `--scripts-only` printed `SKIP (exists)` three times, wrote no VERSION,
    changed nothing and exited 0 — so the one path that upgrades the scripts on
    an EXISTING install (exactly what wave 1a breaks) was a silent no-op wearing a
    success code, and needed a second, undocumented flag to do anything.

    The pin this replaces (`test_scripts_only_without_force_reports_skips`)
    asserted the no-op: `not any(wrote:)`. Its discipline of pinning the positive
    line FIRST is kept, and so is the positive half of "only": the run must be
    shown to have refreshed the three scripts and VERSION and nothing else.
    """
    scripts = ai_repo / ".ai" / "scripts"
    pristine = {name: (scripts / name).read_bytes()
                for name in ("ai_common.py", "checkpoint.py", "sync_verify.py")}
    for name in pristine:
        (scripts / name).write_bytes(b"# stale v2.0 copy\n")
    version = ai_repo / ".ai" / "protocol" / "VERSION"
    version.write_text("1.9.0\n", encoding="utf-8")
    keep = "# Current state\n\nreal work, not a template\n"
    (ai_repo / ".ai" / "state" / "CURRENT.md").write_text(keep, encoding="utf-8")
    cfg_before = (ai_repo / ".ai" / "sync_config.json").read_bytes()
    ignore_before = (ai_repo / ".gitignore").read_bytes()
    agents_before = (ai_repo / "AGENTS.md").read_bytes()

    res = scaffold(ai_repo, "--scripts-only")
    assert res.rc == 0, res.stdout + res.stderr
    for name, blob in pristine.items():
        assert any(ln.startswith("wrote:") and name in ln
                   for ln in res.lines), res.lines
        assert (scripts / name).read_bytes() == blob, (
            f"{name} reported as written but still holds the stale copy")
    assert not [ln for ln in res.lines if ln.startswith("SKIP (exists)")
                and ln.endswith(".py")], res.lines
    assert version.read_text("utf-8").strip() == \
        _load_init_sync().PROTOCOL_VERSION, res.stdout
    # Non-destructive where it must stay non-destructive: state, config,
    # AGENTS.md and .gitignore are not read, written or created by this flag.
    assert (ai_repo / ".ai" / "state" / "CURRENT.md").read_text("utf-8") == keep
    assert (ai_repo / ".ai" / "sync_config.json").read_bytes() == cfg_before
    assert (ai_repo / ".gitignore").read_bytes() == ignore_before
    assert (ai_repo / "AGENTS.md").read_bytes() == agents_before
    written = [ln.split("wrote:", 1)[1].strip()
               for ln in res.lines if ln.startswith("wrote:")]
    stray = [w for w in written
             if Path(w).parent.name != "scripts" and Path(w).name != "VERSION"]
    assert not stray, stray


def test_scripts_only_on_an_uninstalled_repo_installs_scripts(repo):
    """"Scripts only" must be a real install of the scripts, not a no-op.

    An empty run would satisfy the rc check and every content check below, so
    the paths it must produce are asserted first.
    """
    (repo / ".ai" / "state").mkdir(parents=True, exist_ok=True)
    (repo / ".ai" / "state" / "CURRENT.md").write_text("# mine\n", "utf-8")
    res = scaffold(repo, "--scripts-only")
    assert res.rc == 0, res.stdout
    for name in ("ai_common.py", "checkpoint.py", "sync_verify.py"):
        assert (repo / ".ai" / "scripts" / name).exists(), name
    assert (repo / ".ai" / "protocol" / "VERSION").exists()
    assert read(repo, ".ai/state/CURRENT.md") == "# mine\n"
    assert not (repo / "AGENTS.md").exists(), res.lines
    assert not (repo / "CLAUDE.md").exists(), res.lines
    assert not (repo / ".gitignore").exists(), res.lines


# --------------------------------------------------------------------------
# D24: a missing source template is a named error, not a traceback


def test_copy_file_names_a_missing_source(tmp_path):
    mod = _load_init_sync()
    msg = mod.copy_file(tmp_path / "no-such-template.md",
                        tmp_path / "out" / "COPY.md", force=True)
    assert msg.startswith("ERROR (missing source template):"), msg
    assert "no-such-template.md" in msg, msg
    assert not (tmp_path / "out" / "COPY.md").exists()


def test_missing_template_is_a_named_error_not_a_traceback(tmp_path):
    """D24: the install continues, names the failure, and exits non-zero."""
    skill = staged_skill(tmp_path, "templates/DECISIONS.md")
    target = make_repo(tmp_path / "target")
    res = run_python(skill / "scripts" / "init_sync.py",
                     [str(target), "--no-agents-block"], cwd=target)
    assert res.stdout_raw, "init exited without writing any output"
    assert any(ln.startswith("ERROR (missing source template):")
               and "DECISIONS.md" in ln for ln in res.lines), res.lines
    assert "Traceback" not in res.stderr, res.stderr
    assert res.rc == 1, res.stdout + res.stderr
    # Half-built is the defect: the files before and after the missing one in
    # the install order must still have been written.
    assert (target / ".ai" / "state" / "CURRENT.md").exists()
    assert (target / ".ai" / "sync_config.json").exists()
    assert not (target / ".ai" / "state" / "DECISIONS.md").exists()


# --------------------------------------------------------------------------
# the predicate the task produces as an interface


def test_is_template_shaped_answers_for_the_shipped_templates():
    mod = _load_init_sync()
    for rel in ("CURRENT.md", "TASK.md", "BLOCKERS.md", "DECISIONS.md",
                "DECISIONS_INDEX.md", "handoff/LATEST.md"):
        assert mod.is_template_shaped(template_text(rel)) is True, rel
    assert mod.is_template_shaped(template_text("sync_config.json")) is True


def test_is_template_shaped_refuses_caller_written_text():
    mod = _load_init_sync()
    assert mod.is_template_shaped(
        "# Current state\n\nReal work in progress, 47 lines of it.\n") is False
    assert mod.is_template_shaped(
        template_text("CURRENT.md").replace(
            "<one line>", "wave 1a batch B4 in review", 1)) is False
    assert mod.is_template_shaped('{"budgets": {"x": 1}}') is False
    # An empty or whitespace-only file is not "an untouched template": nothing
    # was preserved by calling it one, and clobbering it is not the point.
    assert mod.is_template_shaped("") is False
    assert mod.is_template_shaped("\n  \n") is False


def test_the_shipped_flags_are_documented_in_help():
    """A flag nobody can discover is a flag nobody passes."""
    res = run_python(SCRIPTS / "init_sync.py", ["--help"], cwd=REPO_ROOT)
    assert res.rc == 0, res.stdout + res.stderr
    for flag in ("--scripts-only", "--clobber", "--force", "--no-agents-block"):
        assert any(ln.strip().startswith(flag) for ln in res.lines), res.lines
