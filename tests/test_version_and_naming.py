"""Lane T11: D22 (version skew becomes measurable) and D25/D26 (two false names).

RED at base `f6dd2f4` for the reason each defect exists: `ai_common` had no
`parse_version`/`compare_version` at all, `init_sync.PROTOCOL_VERSION` stamped
"2.0.0" on a v2.1 tree and nothing ever compared it with the installed
`.ai/protocol/VERSION`, four places pointed at an L2 milestone log that no
component creates, and the verifier's budget check was named for a unit it does
not count (`line_count()` returns `len(splitlines())`).

Also here, because lane V left it as a residual and it is the same "two answers,
one question" class as D23: `checkpoint.py --validate` now walks the MERGED
config list plus the floor, exactly like `sync_verify.py`, instead of the shipped
default alone.

Deliberately NOT in this file: the repo-wide token-vs-line wording sweep. The
texts that still carry it (`SKILL.md`, `README.md`, `reference.md`, `templates/`)
are Task 12's, so the grep for that phrase ships there — restricted to tracked
files (`git grep`), never `rglob`, which would read git-ignored scratch.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from helpers import SCRIPTS, run_python

REPO = SCRIPTS.parent

# Loaded under private names, and the plain `ai_common` binding that
# `init_sync`'s own import creates is restored: registering the repo copy under
# its shipped name is the poisoning tests/test_ai_common.py exists to prevent
# (an in-process load of an INSTALLED script would then import this object
# instead of the copy next to it). Same convention as test_validate_parity.py.
_spec = importlib.util.spec_from_file_location("_t11_ai_common",
                                               SCRIPTS / "ai_common.py")
ai_common = importlib.util.module_from_spec(_spec)
sys.modules["_t11_ai_common"] = ai_common
_spec.loader.exec_module(ai_common)

_PRIOR_AI_COMMON = sys.modules.get("ai_common")
_ispec = importlib.util.spec_from_file_location("_t11_init_sync",
                                                SCRIPTS / "init_sync.py")
init_sync = importlib.util.module_from_spec(_ispec)
sys.modules["_t11_init_sync"] = init_sync
_ispec.loader.exec_module(init_sync)
if _PRIOR_AI_COMMON is None:
    sys.modules.pop("ai_common", None)
else:  # pragma: no cover - only if a sibling file already registered it
    sys.modules["ai_common"] = _PRIOR_AI_COMMON

# The D25 needle, spelled so that THIS file — a tracked file the sweep below
# reads — does not contain the string it hunts for. Without this the grep can
# only ever find its own test.
D25_NEEDLE = "MILE" + "STONES"

VERSION_PATH = ".ai/protocol/VERSION"


def _version_file(root: Path) -> Path:
    return root / ".ai" / "protocol" / "VERSION"


def _config(root: Path) -> dict:
    return json.loads((root / ".ai" / "sync_config.json").read_text("utf-8"))


def _write_config(root: Path, cfg: dict) -> None:
    (root / ".ai" / "sync_config.json").write_text(json.dumps(cfg, indent=2) + "\n",
                                                   "utf-8")


# ---------------------------------------------------------------------------
# D22, part 1: versions are values, and values are comparable.
# ---------------------------------------------------------------------------

def test_parse_version_semver_tuple_not_string():
    """String comparison put `2.10.0` BELOW `2.9.0`; a tuple cannot lie."""
    assert ai_common.parse_version("2.10.0") > ai_common.parse_version("2.9.0")
    assert ai_common.compare_version("2.1.0", "2.1.0") == 0
    assert ai_common.compare_version("2.1.0", "2.0.0") == 1


def test_unparseable_version_is_refused():
    """"Cannot tell" is not "clean": a junk stamp must raise, never return None.

    The signature is `tuple[int, int, int]`, not an optional — a caller that got
    `None` back would have to remember to check, which is the fail-open shape
    D5 exists to end.
    """
    for raw in ("v2.0", "", "2.1", "a.b.c", "2.1.0-rc1", "2..1", None):
        try:
            ai_common.parse_version(raw)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {raw!r}")


def test_the_stamped_version_is_the_tree_it_ships_from():
    """D22's user-visible half: a v2.1 tree stamped and advertised 2.0.0.

    Pinned as a range, not a literal: the point is that the stamp names the
    protocol it belongs to, so the next minor release moves it deliberately.
    """
    stamped = ai_common.parse_version(init_sync.PROTOCOL_VERSION)
    assert stamped[:2] == (2, 1), init_sync.PROTOCOL_VERSION


def test_a_fresh_install_stamps_the_file_with_the_scripts_own_version(ai_repo):
    """The two numbers the skew check compares must start out equal."""
    assert _version_file(ai_repo).read_text("utf-8").strip() == \
        init_sync.PROTOCOL_VERSION, ai_repo


# ---------------------------------------------------------------------------
# D22, part 2: the installer compares, reports, and refuses before it writes.
# ---------------------------------------------------------------------------

def test_install_reports_newer_local_scripts(ai_repo):
    """The acceptance row in spec D22: VERSION hand-edited to `9.9.9`.

    RED at `f6dd2f4`: the install ran to completion at rc 0 and never read the
    file it was about to overwrite.
    """
    _version_file(ai_repo).write_text("9.9.9\n", "utf-8")
    res = run_python(SCRIPTS / "init_sync.py", [str(ai_repo)], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("VERSION MISMATCH") for ln in res.lines), res.lines
    assert "9.9.9" in res.stdout
    assert init_sync.PROTOCOL_VERSION in res.stdout, res.stdout
    # The remedy named to the user must be the remedy that works: `--force` is
    # refused on this path (see the test below), so suggesting it is a lie.
    assert "--force" not in res.stdout, res.stdout


def test_downgrade_is_refused(ai_repo):
    """`--force` does not buy a downgrade: it is refused with the flag on."""
    res = run_python(SCRIPTS / "init_sync.py", [str(ai_repo)], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    _version_file(ai_repo).write_text("99.0.0\n", "utf-8")
    res = run_python(SCRIPTS / "init_sync.py", [str(ai_repo), "--force"],
                     cwd=ai_repo)
    assert res.rc == 1 and "downgrade" in res.stdout.lower(), res.stdout


def test_the_refusal_happens_before_any_write(ai_repo):
    """Refusing after the clobber would be reporting damage, not preventing it."""
    (ai_repo / ".ai" / "protocol" / "VERSION").write_text("99.0.0\n", "utf-8")
    state = ai_repo / ".ai" / "state" / "CURRENT.md"
    work = "# Current state\n\nreal work, not a template\n"
    state.write_text(work, "utf-8")
    scripts = ai_repo / ".ai" / "scripts"
    stale = (scripts / "checkpoint.py").read_bytes()
    (scripts / "checkpoint.py").write_bytes(b"# stale v2.0 copy\n")

    res = run_python(SCRIPTS / "init_sync.py",
                     [str(ai_repo), "--clobber"], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert state.read_text("utf-8") == work, res.stdout
    assert (scripts / "checkpoint.py").read_bytes() == b"# stale v2.0 copy\n", \
        res.stdout
    assert not [ln for ln in res.lines if ln.startswith("wrote:")], res.lines
    assert not [ln for ln in res.lines if ln.startswith("Scaffolding")], res.lines


def test_an_older_install_reports_the_upgrade_path(ai_repo):
    """The other direction is not a refusal — it is how v2.0 installs get here.

    RED at `f6dd2f4`: `1.9.0` and `2.1.0` produced no line naming either number,
    because no line compared them.
    """
    _version_file(ai_repo).write_text("1.9.0\n", "utf-8")
    res = run_python(SCRIPTS / "init_sync.py",
                     [str(ai_repo), "--scripts-only"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("VERSION: 1.9.0 -> " + init_sync.PROTOCOL_VERSION)
               and "upgrade" in ln for ln in res.lines), res.lines
    assert _version_file(ai_repo).read_text("utf-8").strip() == \
        init_sync.PROTOCOL_VERSION, res.stdout


# ---------------------------------------------------------------------------
# D22, part 3: verification reads the stamp too, so a hand-edited junk value
# cannot survive to the next machine.
# ---------------------------------------------------------------------------

def test_the_verifier_reads_the_protocol_stamp(ai_repo, sv):
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] protocol version readable:")
               for ln in res.lines), res.lines


def test_a_junk_stamp_is_caught_by_verification(ai_repo, sv):
    """The installer refuses; this is the check for an install nobody re-ran.

    `required .ai/protocol/VERSION` passes on junk — it only asks for bytes —
    so without this line a corrupt stamp reaches a second machine as "green".
    """
    _version_file(ai_repo).write_text("nightly\n", "utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    named = [ln for ln in res.lines
             if ln.startswith("[FAIL] protocol version readable:")]
    assert named and "nightly" in named[0], res.lines
    assert any(ln.startswith("[PASS] required .ai/protocol/VERSION")
               for ln in res.lines), res.lines
    assert any(ln.startswith("FAILED: protocol version readable")
               for ln in res.lines), res.lines


# ---------------------------------------------------------------------------
# Lane V's residual: `--validate` answers for the PROJECT's list, not the
# shipped default, so one question still has one answer after an override.
# ---------------------------------------------------------------------------

def test_validate_walks_the_project_list_not_the_shipped_default(ai_repo, cp, sv):
    """A repo that declares no decision log must not be certified against one.

    RED at `f6dd2f4`: the config dropped `.ai/state/DECISIONS.md`, the file was
    deleted, `sync_verify.py` agreed with the config and exited 0, and
    `--validate` printed MISSING for it at rc 1 — the same question, two answers,
    now inverted by the very fix that made the list shared.
    """
    cfg = _config(ai_repo)
    cfg["required_files"] = [rel for rel in cfg["required_files"]
                             if rel != ".ai/state/DECISIONS.md"]
    _write_config(ai_repo, cfg)
    (ai_repo / ".ai" / "state" / "DECISIONS.md").unlink()

    verdict = run_python(cp, ["--validate"], cwd=ai_repo)
    health = run_python(sv, cwd=ai_repo)
    assert verdict.rc == 0, verdict.stdout + verdict.stderr
    assert not [ln for ln in verdict.lines if "MISSING" in ln], verdict.lines
    assert (verdict.rc == 0) == (health.rc == 0), (verdict.stdout, health.stdout)


def test_a_project_requirement_the_default_lacks_is_validated(ai_repo, cp, sv):
    """The other half of the same override: config may ADD requirements."""
    cfg = _config(ai_repo)
    cfg["required_files"] = list(cfg["required_files"]) + \
        [".ai/state/AUTHORED.md"]
    _write_config(ai_repo, cfg)

    verdict = run_python(cp, ["--validate"], cwd=ai_repo)
    health = run_python(sv, cwd=ai_repo)
    assert verdict.rc == 1, verdict.stdout
    assert any("MISSING" in ln and "AUTHORED.md" in ln
               for ln in verdict.lines), verdict.lines
    assert any(ln.startswith("[FAIL] required .ai/state/AUTHORED.md: missing")
               for ln in health.lines), health.lines
    assert (verdict.rc == 0) == (health.rc == 0), (verdict.stdout, health.stdout)


def test_an_unusable_required_files_key_bringst_no_verdict(ai_repo, cp):
    """A list this command could not read is not a list it may certify.

    `required_files` merging by REPLACE means a string here would iterate its
    own characters (lane S2 finding 4's shape); rc 2 already means "no verdict"
    in `cmd_validate`, so the degradation is named with the code that carries it.
    """
    cfg = _config(ai_repo)
    cfg["required_files"] = ".ai/state/CURRENT.md"
    _write_config(ai_repo, cfg)
    res = run_python(cp, ["--validate"], cwd=ai_repo)
    assert res.rc == 2, res.stdout
    assert "All state files present and non-empty." not in res.stdout, res.stdout
    assert "required_files" in res.stdout, res.stdout


def test_validate_no_longer_reads_only_the_shipped_constant():
    """Structural pin: the command has to OPEN the config it answers for.

    Same shape as `test_validate_walks_the_shared_list_and_nothing_else`'s source
    scan — a private list is how D23 happened, and a stale default list is how
    lane V's residual survived the fix that removed it.
    """
    src = (SCRIPTS / "checkpoint.py").read_text("utf-8")
    window = chr(10) + "def install_layout"
    body = src.split("def _declared_required_files", 1)[1].split(window, 1)[0]
    assert "sync_config.json" in body, body
    assert "with_required_file_floor" in body, body


# ---------------------------------------------------------------------------
# D25: the L2 milestone log is referenced in four places and created by none.
# ---------------------------------------------------------------------------

def test_no_milestones_references_remain():
    """docs/superpowers is excluded on purpose: the spec and this plan discuss the
    D25 removal by name, so a bare git grep could never pass."""
    out = subprocess.run(["git", "grep", "-l", D25_NEEDLE, "--",
                          ":!docs/superpowers"], cwd=str(REPO),
                         capture_output=True, text=True).stdout
    assert out.strip() == "", out


def test_prime_still_names_the_archives_that_do_exist(ai_repo, cp):
    """D25 removes a promise, not the retrieval rule: the L2 line must still
    say what is retrieval-only, including `state/archive/`, which it omitted."""
    res = run_python(cp, ["--prime"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert res.stdout_raw.decode("ascii") == res.stdout, "non-ASCII in --prime"
    line = " ".join(ln for ln in res.lines if "read in full" in ln.lower()
                    or "DECISIONS_INDEX" in ln)
    for name in ("DECISIONS.md", "handoff/archive", "state/archive",
                 "DECISIONS_INDEX.md"):
        assert name in line, (name, res.lines)


# ---------------------------------------------------------------------------
# D26: the budget check counts LINES; saying "token" is a false claim, not a
# cosmetic one, in a protocol that permits CJK state files.
# ---------------------------------------------------------------------------

def test_the_budget_check_is_named_for_the_unit_it_counts():
    """The function, its call site and the docstring check-list, and nothing else."""
    src = (SCRIPTS / "sync_verify.py").read_text("utf-8")
    assert "def check_line_budgets(" in src
    assert "check_" + "token" + "_budgets" not in src
    # What is banned is the CLAIM about the unit. The one surviving use of the
    # word is the docstring sentence saying a line is a WEAK proxy for tokens in
    # CJK state files (D26's disclosure), and the next test pins that nothing the
    # verifier PRINTS still claims it. The needle is concatenated so this file
    # stays clean under the repo-wide grep Task 12 adds: a wording test whose own
    # test file needs an exclusion is a wording test that can be bypassed.
    assert "token " + "budget" not in src.lower()


def test_renaming_the_check_renamed_no_printed_name(ai_repo, sv):
    """D26's own boundary: `budget <path>` is a name agents and docs quote."""
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    for name in ("[PASS] budget AGENTS.md:",
                 "[PASS] budget .ai/state/CURRENT.md:",
                 "[PASS] budget .ai/handoff/LATEST.md:",
                 "[PASS] budget .ai/handoff/NEXT_PROMPT.md:",
                 "[PASS] budget .ai/state/DECISIONS_INDEX.md:",
                 "[PASS] budget DECISIONS active entries:"):
        assert any(ln.startswith(name) for ln in res.lines), (name, res.lines)
    # The claim is gone from the output even though the check still runs.
    assert not [ln for ln in res.lines if "token" in ln.lower()], res.lines
