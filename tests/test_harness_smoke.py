import ast
import os
import re
from pathlib import Path

from helpers import SCRIPTS, git, make_repo, run_python, scaffold

# The arrow init_sync.py prints in its own "Next steps" evidence text, and the
# character Task 6's non-ASCII path test depends on. Used to pin the harness's
# encoding contract (see test_non_ascii_evidence_needs_an_explicit_child_encoding).
ARROW = "→"

# Anything that reads like a degradation notice. sync_verify.py emits a bare
# `WARNING: cannot read ...` line for an unreadable config (scripts/sync_verify.py
# load_config), which no bracketed assertion can ever see.
WARNISH = re.compile(r"\bWARN(ING|ED)?\b", re.IGNORECASE)


def test_scripts_dir_exists_and_is_stdlib_only():
    names = {p.name for p in SCRIPTS.glob("*.py")}
    assert {"checkpoint.py", "sync_verify.py", "init_sync.py"} <= names


def test_scaffold_into_git_repo_exits_zero(ai_repo):
    assert (ai_repo / ".ai" / "protocol" / "VERSION").exists()


def test_fresh_scaffold_verifies_all_green(ai_repo):
    """Baseline for later tasks: every check that ran passed, none were skipped,
    warned about, or silent. Deliberately NOT a literal count — Tasks 3, 6 and 7
    each change the check set, and a hard-coded number turns every legitimate
    change into a re-edit of this test. The final count is pinned once, in Task 12.

    Assertions are positive for a reason. `not any(startswith("[FAIL]"))` and
    `not any(startswith("[SKIP]"))` are both satisfied by a `[WARN]` line — and
    by no output at all — so the harness would have blessed exactly what the
    plan's design law forbids: a degradation reported as green.

    Lane S2 (r1 finding 12): `all(ln.startswith("[PASS]"))` was the assertion a
    legitimate fresh-install SKIP contradicts, so the accepted set is now "PASS,
    or one of the NAMED skips". The shipped template registers no `extra_checks`
    and no `secret_mirrors`, and finding 2 turns that emptiness into a named
    line: the run may no longer book `N/N` for a governance set nobody
    registered. Wave 1b adds three more names to that same set, all of them the
    spec-7 defaults rather than a machine that failed to look: `[SKIP] path
    coverage` (`protected_paths` defaults to empty, spec 7), `[SKIP] pin
    violation` (no authorization records yet), `[SKIP] role policy integrity`
    (no SHA pinned yet). `swarm boundary` is the fourth new check and it PASSes
    here with a count of zero. FAIL, WARN, silence, a SECOND skip of the same
    name, and any skip outside this list are still breaks, and the summary's own
    skip tail is pinned against the SKIP lines actually printed.
    """
    res = run_python(ai_repo / ".ai" / "scripts" / "sync_verify.py", cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert res.stdout_raw, "verifier exited 0 without writing any output"
    checks = [ln for ln in res.lines if ln.startswith("[")]
    assert checks, res.lines
    # Lane S2 finding 2's unregistered-governance-set SKIP, then the wave-1b
    # named governance SKIPs. Add a name here only with a spec section behind it.
    allowed_skip = ("[SKIP] registered project checks:",
                    "[SKIP] path coverage:",
                    "[SKIP] pin violation:",
                    "[SKIP] role policy integrity:")
    not_green = [ln for ln in checks if not ln.startswith("[PASS]")
                 and not ln.startswith(allowed_skip)]
    assert not not_green, not_green
    skips = [ln for ln in checks if ln.startswith(allowed_skip)]
    # One line per named degradation: a SECOND `[SKIP] path coverage:` would mean
    # a check was wired into the run twice, and a duplicate of any other name
    # means the same thing. Still exactly one unknown skip allowed: zero.
    names = [ln.split(":", 1)[0] for ln in skips]
    assert len(names) == len(set(names)), skips
    unbracketed = [ln for ln in res.lines if not ln.startswith("[")]
    assert not [ln for ln in unbracketed if WARNISH.search(ln)], unbracketed
    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1, res.lines
    if skips:
        assert f", {len(skips)} skipped" in summary[0], (summary[0], skips)
    else:
        assert "skipped" not in summary[0], summary[0]


def test_scaffold_is_idempotent(ai_repo):
    first = (ai_repo / ".ai" / "state" / "CURRENT.md").read_text(encoding="utf-8")
    res = scaffold(ai_repo)
    assert res.rc == 0
    assert (ai_repo / ".ai" / "state" / "CURRENT.md").read_text(
        encoding="utf-8") == first
    assert not any("wrote:" in ln and "CURRENT" in ln for ln in res.lines), res.lines
    # Positive, count-free proof the second scaffold reported anything at all:
    # a real idempotent run names every pre-existing path as skipped. Without
    # this, a scaffold that emitted nothing satisfies rc == 0, the content
    # equality above, and the vacuous `not any(...)` guard.
    assert sum(1 for ln in res.lines if "SKIP (exists)" in ln) >= 3, res.lines


def test_non_ascii_evidence_needs_an_explicit_child_encoding(tmp_path):
    """Pin the harness's encoding contract instead of hiding it (D5 class).

    The runner decodes raw bytes as UTF-8/surrogateescape and never forces the
    child's encoding, so a non-ASCII evidence line round-trips exactly only
    when the test declares it. Under a legacy code page the same bytes decode
    to lone surrogates: no exception, just a comparison that can never match.
    Task 6's cp936 test depends on this staying reachable, so it is documented
    here rather than defaulting PYTHONUTF8 on for everyone.
    """
    assert ARROW in (SCRIPTS / "init_sync.py").read_text(encoding="utf-8")
    probe = tmp_path / "emit_evidence.py"
    probe.write_text(f"print('secret ignored: {ARROW} .env')\n", encoding="utf-8")

    declared = run_python(probe, cwd=tmp_path,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert declared.rc == 0, declared.stderr
    assert declared.lines == [f"secret ignored: {ARROW} .env"], declared.lines
    assert ARROW.encode("utf-8") in declared.stdout_raw

    legacy = run_python(probe, cwd=tmp_path,
                        env=dict(os.environ, PYTHONIOENCODING="cp936"))
    assert legacy.rc == 0, legacy.stderr
    assert ARROW.encode("cp936") == b"\xa1\xfa"
    assert b"\xa1\xfa" in legacy.stdout_raw
    assert not any(ARROW in ln for ln in legacy.lines), legacy.lines
    assert "\udca1\udcfa" in legacy.stdout, repr(legacy.stdout)


def test_git_helpers_ignore_ambient_git_state(tmp_path, monkeypatch):
    """A pytest run started from a git hook must not touch the developer's repo.

    The fixture repo's own config is the only one a test may write.
    """
    outer = tmp_path / "outer"
    outer.mkdir()
    developer_config = tmp_path / "developer.gitconfig"
    developer_config.write_text(
        "[user]\n\temail = real@example.invalid\n", encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(outer / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outer))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(developer_config))

    repo = make_repo(tmp_path / "scratch")

    assert git(repo, "config", "user.email") == "t@example.invalid"
    assert not (outer / ".git").exists(), "ambient GIT_DIR reached the outer repo"
    text = developer_config.read_text(encoding="utf-8")
    assert "real@example.invalid" in text and "t@example.invalid" not in text, text


# The identity helpers.hermetic_env must put in the child's environment. Kept as
# a literal here (not imported) so a future change to helpers cannot make both
# sides of this assertion agree with each other.
FIXTURE_IDENTITY = "Test Human <t@example.invalid>"


def test_commit_works_inside_a_plain_clone(tmp_path):
    """A clone must be commit-capable, not just config-protected (fix round 2).

    `hermetic_env` pins GIT_CONFIG_GLOBAL/SYSTEM to the null device, and
    `git clone` does not copy the source repo's repo-local `[user]` block, so a
    clone has no identity from any config file. Tasks 7 and 12 commit inside
    clones: without GIT_AUTHOR_*/GIT_COMMITTER_* in the environment the commit
    dies with rc 128 "Author identity unknown" and reads as a product defect.
    The assertion is on the identity the commit RECORDS, so quietly falling back
    to the developer's own name/email (this host's global config resolves to a
    real address) cannot pass.
    """
    src = make_repo(tmp_path / "scratch")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(src), str(clone))

    # The clone really has no repo-local identity: the env vars must be what
    # saves it, otherwise this test would pass for the wrong reason.
    cfg = (clone / ".git" / "config").read_text(encoding="utf-8")
    assert "[user]" not in cfg, cfg

    (clone / "HANDOFF.md").write_text("cloned work\n", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "commit made inside a clone")
    assert git(clone, "log", "-1", "--format=%an <%ae>") == FIXTURE_IDENTITY
    assert git(clone, "log", "-1", "--format=%cn <%ce>") == FIXTURE_IDENTITY


def test_explicit_env_must_not_bypass_the_git_scrub(tmp_path, monkeypatch):
    """`env=` used to be applied verbatim, re-opening the leak the scrub exists
    to close: `dict(os.environ, PYTHONIOENCODING=...)` carries GIT_DIR and the
    developer's own GIT_AUTHOR_EMAIL straight into the child.

    Contract is a merge, not a switch: hermetic base first, then the caller's
    dict wins on keys the caller set *deliberately* (SOMETHING below; Task 6's
    PYTHONIOENCODING; a later task's empty PATH) — while values merely copied
    from the ambient environment are dropped.
    """
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "outer" / ".git"))
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "real@example.invalid")
    probe = tmp_path / "show_env.py"
    probe.write_text(
        "import os\n"
        "for k in ('GIT_DIR', 'GIT_AUTHOR_EMAIL', 'SOMETHING'):\n"
        "    print(k, repr(os.environ.get(k)))\n",
        encoding="utf-8")

    res = run_python(probe, cwd=tmp_path, env=dict(os.environ, SOMETHING="x"))
    assert res.rc == 0, res.stderr
    seen = dict(ln.split(" ", 1) for ln in res.lines)
    assert seen["GIT_DIR"] == "None", seen
    assert seen["GIT_AUTHOR_EMAIL"] == repr("t@example.invalid"), seen
    assert seen["SOMETHING"] == repr("x"), seen


def _annotations(tree: ast.AST) -> list[ast.expr]:
    out: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            out.append(node.annotation)
        elif isinstance(node, ast.AnnAssign):
            out.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node.returns)
    return [a for a in out if a is not None]


def test_modules_using_pep604_unions_defer_annotation_evaluation():
    """Python 3.9 floor, enforced structurally because no 3.9 interpreter is
    guaranteed on a given host.

    Without `from __future__ import annotations` the unions below are evaluated
    when the def/class body runs, so on 3.9 `import helpers` raises TypeError
    and every collected test errors — a whole-suite fail-open. Checked as a test
    so deleting the future import breaks the suite for the right reason.

    `scripts/*.py` are in scope for the same reason, one level up: a shipped
    module that fails to import is a broken install on every 3.9 machine, and
    Task 1's `ai_common.py` is exactly that shape (PEP 604 unions in both
    function signatures and module-level path globals).
    """
    offenders, deferred = [], []
    paths = sorted(Path(__file__).parent.glob("*.py")) + sorted(SCRIPTS.glob("*.py"))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        unions = [n for a in _annotations(tree)
                  for n in ast.walk(a)
                  if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)]
        if not unions:
            continue
        deferred.append(path.name)
        head = [s for s in tree.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                        and isinstance(s.value.value, str))]
        first = head[0] if head else None
        if (isinstance(first, ast.ImportFrom) and first.module == "__future__"
                and any(n.name == "annotations" for n in first.names)):
            continue
        offenders.append(f"{path.name}: {len(unions)} evaluated PEP 604 union(s)")

    # The anchor is the point: an empty `deferred` or one reduced to a single
    # file would let the rest of them leave this guard's scope in silence
    # (finding J). `checkpoint.py` belongs in this set too, and is held back
    # only while another lane owns that file — see task-1-report.md.
    assert {"helpers.py", "ai_common.py"} <= set(deferred), \
        f"guard went vacuous: {deferred}"
    assert not offenders, offenders


def test_cp_fixture_alone_implies_an_installed_script(cp):
    """`cp` promises an install, so it must pull `ai_repo` in by itself.

    Requesting `cp` and nothing else is the case that matters: under the old
    `cp(repo)` wiring the path did not exist, `run_python` returned rc 2 with
    empty stdout, and every negative assertion downstream passed vacuously.
    """
    assert cp.exists(), cp
    assert cp.read_text(encoding="utf-8").strip(), cp


def test_sv_fixture_alone_implies_a_runnable_verifier(sv):
    assert sv.exists(), sv
    res = run_python(sv, cwd=sv.parents[2])
    assert res.rc == 0, res.stdout + res.stderr
    assert res.stdout_raw, "sync_verify exited 0 without writing any output"
