"""Lane V: the checkpoint side of the protocol answers ONE way or says why not.

Three claims this file exists to keep true, each measured at `2796c2f` first:

1. **D23 / V-1 — one required-file list, really.** `ai_common.py` says every
   script imports `DEFAULT_REQUIRED_FILES` "instead of copying it", while
   `checkpoint.cmd_validate` still carried a private list of seven paths that
   omitted `.ai/state/ROLE_POLICY.md`. The reviewer's measurement: with that file
   deleted, `--validate` printed "All state files present and non-empty." at rc 0
   and `sync_verify.py` printed "[FAIL] required .ai/state/ROLE_POLICY.md" at
   rc 1 — two answers to one question, one of them false. The first test below is
   the differential the fix had to be able to pass.
2. **V-2 — a close-out instruction the protocol can actually satisfy.** A default
   install registers no project checks, so the verifier ends
   `== 16/17 checks passed, 1 skipped ==` at rc 0 (spec §4: an unregistered
   governance set is a named SKIP, never a fake green). Any text this tool writes
   into a user's repo, or prints at session start, that demands "all green" is
   therefore unsatisfiable. These pins cover the sites in `scripts/` and
   `templates/`; `SKILL.md` / `README.md` are the doc lane's.
3. **V-5 / V-6 — the state-writing commands and the bytes they print.** The D15
   layout gate lived in `cmd_lock` only, so `--handoff` archived tracked files on
   a checkout `--lock` refused (finding 2.3); and `now_display()` put a localized,
   non-ASCII timezone name into shipped output through the forced-UTF-8 wrapper.

Advisory by design throughout: a refusal here names the layout and offers
`--force`; `--force` then WARNs by name and continues. Nothing enforces.
"""
from __future__ import annotations

import datetime as real_datetime
from pathlib import Path

import pytest

from helpers import SCRIPTS, git, load_ai_common, load_module, load_script, run_python, scaffold

# Loaded under private names (see tests/test_ai_common.py for why registering
# either as its shipped name would poison an in-process load of an INSTALLED
# script), and purged by the same convention the other lanes follow.
ai_common = load_ai_common("_validate_parity_ai_common", keep=True)

# `init_sync.MANAGED_BLOCK` is the text this tool appends to a user's AGENTS.md,
# so the promise it makes is read from the constant rather than guessed from the
# source file (whose docstring legitimately quotes the old wording).
#
# Importing it has a side effect this file must undo: `init_sync` falls back to
# `sys.path.insert(0, <its own directory>)` and `from ai_common import ...`, which
# registers the REPO's `ai_common` under the plain name — precisely the poisoning
# tests/test_ai_common.py guards against. ``load_script`` restores that binding.
init_sync = load_script("init_sync.py", "_validate_parity_init_sync", keep=True)

# The governed file whose absence used to be reported as "all present".
GOVERNANCE = ".ai/state/ROLE_POLICY.md"


def _load_installed(script: Path):
    """Import a `checkpoint.py` copied INTO a fixture repo."""
    return load_module("_validate_parity_checkpoint", script, keep=True)


def _verdict_lines(res):
    """`--validate`'s per-file lines, the only ones that carry a verdict."""
    return [ln for ln in res.lines
            if any(tag in ln for tag in ("OK:", "EMPTY:", "MISSING:",
                                         "UNREADABLE:"))]


def _code_lines(src: str, start: str, stop: str) -> str:
    """A function's CODE lines, comments excluded.

    The scan below is for a re-appearing private list, and a comment explaining
    why the private list went away would otherwise satisfy its own prohibition —
    which is how a source scan stops being a test.
    """
    body = src.split(start, 1)[1].split(stop, 1)[0]
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))


def _worktree_install(ai_repo, tmp_path) -> Path:
    """A linked worktree with its own install — the D15 shape on disk.

    `ai_repo` does not commit the install, so the worktree is scaffolded the
    supported way (same approach and same self-check as
    tests/test_worktree_refusal.py).
    """
    wt = tmp_path / "wt"
    git(ai_repo, "worktree", "add", "-q", "-b", "side-v", str(wt))
    assert (wt / ".git").is_file(), f"not a linked worktree: {wt}"
    res = scaffold(wt)
    assert res.rc == 0, res.stdout + res.stderr
    assert (wt / ".ai" / "handoff" / "LATEST.md").is_file(), (
        "the fixture has no handoff to archive, so the refusal assertion below "
        "would pass vacuously")
    return wt


# --------------------------------------------------------------------------
# V-1: the differential. One question, one answer, from both enforcement
# commands — and neither of them allowed to say "clean" about a tree that is not.
# --------------------------------------------------------------------------

def test_validate_and_the_verifier_refuse_the_same_missing_file(ai_repo, cp, sv):
    """The reviewer's measurement, now pinned in both directions.

    RED at `2796c2f`: `--validate` exited 0 with "All state files present and
    non-empty." here while `sync_verify.py` exited 1 on the same tree. `rc == 0`
    is never sufficient, and "not in my list" was never "not required".
    """
    (ai_repo / ".ai" / "state" / "ROLE_POLICY.md").unlink()
    verdict = run_python(cp, ["--validate"], cwd=ai_repo)
    health = run_python(sv, [], cwd=ai_repo)
    assert verdict.rc == 1, verdict.stdout + verdict.stderr
    assert "All state files present and non-empty." not in verdict.stdout, (
        verdict.stdout)
    assert any("ROLE_POLICY.md" in ln and "MISSING" in ln
               for ln in verdict.lines), verdict.lines
    assert health.rc == 1, health.stdout + health.stderr
    assert f"[FAIL] required {GOVERNANCE}" in health.stdout, health.stdout
    assert f"FAILED: required {GOVERNANCE}" in health.stdout, health.stdout
    # Both commands, one verdict: neither may be the lone optimist.
    assert (verdict.rc == 0) == (health.rc == 0), (verdict.stdout, health.stdout)


def test_validate_walks_the_shared_list_and_nothing_else(ai_repo, cp):
    """The list is imported, not restated: same entries, same count, same order.

    A second copy is what made D23, so the pin is structural: one verdict line
    per shared entry. Red at `2796c2f`, where `--validate` printed seven lines and
    `DEFAULT_REQUIRED_FILES` holds eight.
    """
    res = run_python(cp, ["--validate"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    walked = _verdict_lines(res)
    assert len(walked) == len(ai_common.DEFAULT_REQUIRED_FILES), (
        walked, ai_common.DEFAULT_REQUIRED_FILES)
    for entry, line in zip(ai_common.DEFAULT_REQUIRED_FILES, walked):
        assert entry.rsplit("/", 1)[-1] in line, (entry, line)
    src = (SCRIPTS / "checkpoint.py").read_text("utf-8")
    # Lane T11: the window starts at the helper, not at `cmd_validate`. The
    # config read moved one function up, and a window that began at
    # `cmd_validate` would scan a body that no longer names the constant while
    # the law it pins (imported, never restated) still held two lines earlier.
    body = _code_lines(src, "def _declared_required_files", "\ndef install_layout")
    assert "DEFAULT_REQUIRED_FILES" in body, body
    assert "STATE_DIR /" not in body and "PROTOCOL_DIR /" not in body, (
        "cmd_validate is back to spelling paths out instead of importing them")


def test_an_empty_shared_list_is_refused_not_certified(cp, monkeypatch):
    """§4's emptiness law, applied to the command that just learned to import.

    `--validate` reads one list, so a list that came back empty would let it
    certify a tree it never looked at.
    """
    mod = _load_installed(cp)
    mod._set_paths(cp.parent.parent)
    # RE-SCOPED in lane T11, with the reason stated instead of the assertion
    # deleted: patching the shipped CONSTANT no longer reaches the verdict, and
    # that IS the fix. Once `--validate` reads `config["required_files"]` the way
    # the verifier does (lane V's residual), the constant is only the fallback
    # for a repo that has no config at all, so the derivation is the seam that
    # still answers "may an empty list certify a tree?". The law survives; its
    # code moves from 2 to 1, because an empty declaration walks the floor and
    # lands on the same rc the verifier prints for its `required-file list` FAIL
    # -- two commands, one answer, which is what D23 was about.
    monkeypatch.setattr(mod, "_declared_required_files",
                        lambda: ([], [], None))
    with pytest.raises(SystemExit) as exc:
        mod.cmd_validate(None)
    assert exc.value.code == 1, exc.value.code


# --------------------------------------------------------------------------
# V-2: no shipped text may demand a green the verifier is designed not to give.
# --------------------------------------------------------------------------

def test_prime_prints_a_gate_a_fresh_install_can_meet(ai_repo, cp):
    """`--prime` is the session-start instruction; it must not promise green.

    RED at `2796c2f`: this line read "python .ai/scripts/sync_verify.py must be
    all green", which a default install can never print.
    """
    res = run_python(cp, ["--prime"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert "all green" not in res.stdout, res.stdout
    assert "no FAILED" in res.stdout, res.stdout
    assert "[SKIP]" in res.stdout, res.stdout
    assert "--unlock --agent" in res.stdout, res.stdout


def test_no_installed_instruction_demands_all_green(ai_repo):
    """The texts this tool writes into a user's repo, in their installed form.

    `AGENTS.md`'s managed block and `.ai/SYNC_PROMPT.md` are read by every
    harness on every machine, so a false sentence there ships even when no doc in
    this repo is wrong.
    """
    prompt = (ai_repo / ".ai" / "SYNC_PROMPT.md").read_text("utf-8")
    template = (SCRIPTS.parent / "templates" / "SYNC_PROMPT.md").read_text("utf-8")
    for name, text in ((".ai/SYNC_PROMPT.md", prompt),
                       ("templates/SYNC_PROMPT.md", template),
                       ("init_sync.MANAGED_BLOCK", init_sync.MANAGED_BLOCK)):
        assert "all green" not in text, (name, text)
        assert "FAILED:" in text, (name, text)
        assert "[SKIP]" in text, (name, text)
    # The gate stays attached to the step it gates, and the close-out still names
    # the agent on the line that mentions the unlock (tests/test_install_budget.py
    # scans installed sources for the bare form).
    unlock_lines = [ln for ln in init_sync.MANAGED_BLOCK.splitlines()
                    if "--unlock" in ln]
    assert unlock_lines, init_sync.MANAGED_BLOCK
    assert all("--agent" in ln for ln in unlock_lines), unlock_lines
    assert all(("commit" in ln and "push" in ln) for ln in unlock_lines), (
        unlock_lines)
    # The block's cost is fixed prose in `templates/AGENTS.md` ("it adds 16
    # lines"): rewording may not silently change what the cap was raised for.
    assert len(init_sync.MANAGED_BLOCK.splitlines()) == 14, (
        init_sync.MANAGED_BLOCK.splitlines())
    assert init_sync.BLOCK_APPEND_SPAN == 16, init_sync.BLOCK_APPEND_SPAN


def test_installer_next_steps_states_the_gate_it_cannot_certify(ai_repo):
    """V-2 + V-4: the installer's own closing line, on a run that SUCCEEDED.

    RED at `2796c2f`: `3. python .ai/scripts/sync_verify.py -> should be all
    green.` (observed in this lane's first run of this file).
    """
    res = scaffold(ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert "all green" not in res.stdout, res.stdout
    assert "no FAILED" in res.stdout, res.stdout
    assert "[SKIP]" in res.stdout, res.stdout


def test_a_failed_install_prints_no_success_instructions(tmp_path):
    """V-4: a promise about next steps is not a verdict on this run.

    RED at `2796c2f`: an install whose FILE_MAP reported
    `ERROR (missing source template)` still printed the four-step Next-steps
    block, step 3 being "should be all green", and exited 1.
    """
    skill_dir = tmp_path / "skill"
    for rel in ("scripts", "templates"):
        (skill_dir / rel).mkdir(parents=True)
    for name in ("ai_common.py", "checkpoint.py", "sync_verify.py",
                 "init_sync.py"):
        (skill_dir / "scripts" / name).write_text(
            (SCRIPTS / name).read_text("utf-8"), "utf-8")
    for src in (SCRIPTS.parent / "templates").iterdir():
        if src.is_file():
            (skill_dir / "templates" / src.name).write_bytes(src.read_bytes())
    (skill_dir / "templates" / "DECISIONS.md").unlink()
    target = make_repo_outside(tmp_path)
    res = run_python(skill_dir / "scripts" / "init_sync.py",
                     [str(target), "--no-agents-block"], cwd=target)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("ERROR (missing source template)")
               for ln in res.lines), res.lines
    assert "Next steps:" not in res.stdout, res.stdout
    assert "all green" not in res.stdout, res.stdout
    assert "Install incomplete" in res.stdout, res.stdout
    assert "exits 1" in res.stdout, res.stdout


def make_repo_outside(tmp_path) -> Path:
    """A throwaway repo, built through helpers' own inside-this-checkout guard."""
    from helpers import make_repo
    return make_repo(tmp_path / "target")


# --------------------------------------------------------------------------
# V-5: the layout gate covers the state writers, not just the lock.
# --------------------------------------------------------------------------

def test_handoff_in_a_linked_worktree_is_refused_before_it_archives(ai_repo,
                                                                    tmp_path):
    """RED at `2796c2f`: this archived a tracked file and exited 0.

    `install_layout()` was reached only from `cmd_lock`, so the invariant "a
    per-worktree lock coordinates nobody" was enforced on one of the five
    commands that can create state.
    """
    wt = _worktree_install(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    res = run_python(cp, ["--handoff", "--agent", "codex"], cwd=wt)
    assert res.rc == 1, res.stdout
    assert "REFUSED: this checkout is a linked git worktree" in res.stdout, (
        res.stdout)
    assert not (wt / ".ai" / "runtime" / "STATUS.json").exists(), (
        "refused the layout and wrote state anyway")
    archived = list((wt / ".ai" / "handoff" / "archive").glob("*.md"))
    assert not archived, f"refused the layout and archived a handoff: {archived}"


def test_bare_checkpoint_in_a_linked_worktree_is_refused(ai_repo, tmp_path):
    """The other state writer: the bare checkpoint, same gate, same verdict."""
    wt = _worktree_install(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    res = run_python(cp, [], cwd=wt)
    assert res.rc == 1, res.stdout
    assert "REFUSED: this checkout is a linked git worktree" in res.stdout, (
        res.stdout)
    assert not (wt / ".ai" / "runtime" / "STATUS.json").exists(), res.stdout


def test_force_overrides_with_a_warn_that_says_what_it_did_not_record(ai_repo,
                                                                      tmp_path):
    """Advisory, and honest about being advisory: `--force` continues at rc 0 and
    must name the layout plus the fact that a state write leaves no record.
    """
    wt = _worktree_install(ai_repo, tmp_path)
    cp = wt / ".ai" / "scripts" / "checkpoint.py"
    res = run_python(cp, ["--handoff", "--agent", "codex", "--force"], cwd=wt)
    assert res.rc == 0, res.stdout
    assert "WARN handoff:" in res.stdout, res.stdout
    assert "linked-worktree" in res.stdout, res.stdout
    assert "no WRITER_LOCK.json entry" in res.stdout, res.stdout
    assert "REFUSED" not in res.stdout, res.stdout
    assert (wt / ".ai" / "runtime" / "STATUS.json").exists(), res.stdout


def test_a_normal_install_still_writes_state(ai_repo, cp):
    """The gate must not swallow the common case (same pin B7a left for --lock).

    Regression pin: already green at `2796c2f`.
    """
    res = run_python(cp, ["--handoff", "--agent", "codex"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert "Handoff prepared" in res.stdout, res.stdout


# --------------------------------------------------------------------------
# V-6: a timestamp that survives an ASCII console.
# --------------------------------------------------------------------------

class _LocalizedZone(real_datetime.tzinfo):
    """A zone whose NAME is not ASCII and whose OFFSET is — the host the
    reviewer measured (zh Windows: `澳大利亚东部标准时间`, UTC+10:00).

    `datetime.tzname()` is locale-dependent, so the name cannot be the carrier;
    `utcoffset()` can.
    """

    def __init__(self, hours, minutes=0, name="澳大利亚东部标准时间"):
        self._delta = real_datetime.timedelta(hours=hours, minutes=minutes)
        self._name = name

    def utcoffset(self, dt):
        return self._delta

    def tzname(self, dt):
        return self._name

    def dst(self, dt):
        return real_datetime.timedelta(0)


@pytest.mark.parametrize("hours,minutes,expect", [
    (10, 0, "UTC+10:00"),
    (-5, -30, "UTC-05:30"),
    (0, 0, "UTC+00:00"),
])
def test_a_localised_zone_name_never_reaches_the_timestamp(cp, hours, minutes,
                                                           expect):
    """`now_display()` goes through `protect_stdio()` into shipped output."""
    mod = _load_installed(cp)
    real_now = real_datetime.datetime(2026, 9, 21, 9, 2, 52)
    zone = _LocalizedZone(hours, minutes)
    mod.now_dt = lambda: real_now.replace(tzinfo=zone)
    line = mod.now_display()
    assert line.isascii(), line
    assert expect in line, line
    assert "2026-09-21 09:02:52" in line, line


def test_an_ascii_zone_name_is_still_kept_and_the_host_offset_is_real(cp):
    """The label is derived from the host, not invented: a real run must carry
    the same offset `datetime.now().astimezone().utcoffset()` reports, and a host
    whose zone name is ASCII keeps it.
    """
    mod = _load_installed(cp)
    local = mod.now_dt()
    delta = local.utcoffset() or real_datetime.timedelta(0)
    total = int(delta.total_seconds())
    sign = "-" if total < 0 else "+"
    total = abs(total)
    expect = f"UTC{sign}{total // 3600:02d}:{total % 3600 // 60:02d}"
    line = mod.now_display()
    assert expect in line, (line, expect)
    name = local.tzname() or ""
    assert name.isascii() or name not in line, (line, name)


def test_a_real_state_write_prints_an_ascii_timestamp(ai_repo, cp):
    """End to end: the line that lands on stdout must be console-safe bytes, not
    forced-UTF-8 mojibake for a code page the console is not.
    """
    res = run_python(cp, ["--agent", "codex"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    stamped = [ln for ln in res.lines if "Checkpoint #" in ln]
    assert stamped, res.stdout
    assert stamped[0].isascii(), stamped[0]
    assert "UTC" in stamped[0], stamped[0]
    assert res.stdout_raw.decode("ascii") == res.stdout, "non-ASCII bytes printed"
