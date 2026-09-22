"""spec 6.3 — the omission coverage walk over `protected_paths`.

The claim being verified is narrow and falsifiable: every commit in the governed
window that touches a protected path must be covered by an ACCEPTED
authorization whose existing `## Editable files` list names that path. Coverage
comes from the field the v2.0 template already has, so a skipped review stays
visible in history for anyone who re-runs the verifier — and the walk HALTS
(FAIL, never green) whenever git cannot answer.

Two passes are required by spec 6.3, and the merge test below is the one that
proves the second pass is live rather than decorative: a merge commit's OWN diff
(an evil merge / conflict resolution) is exactly what an agent produces when two
machines edit the same file under contention, and it never appears in a
`--no-merges` traversal.

THE CONTINUATION AND THE HALT ARE PINNED, NOT JUST THE HAPPY PATH. A commit that
touches two protected paths arrives from `git log` as one header record plus one
record per later path, so a walk that keeps only the first path of a commit still
reports a PASS over work nobody authorised; two tests below exist to make that
impossible. The shallow/indeterminate halt cannot be reproduced with a real
shallow clone on every host (`git clone --depth 1 file://…` is POSIX-only), so
the halt is pinned by patching the probe on this host and, as a separate
POSIX-marked test, end to end.
"""
import importlib.util
import json
import sys

import pytest
from helpers import SCRIPTS, git, run_python


# A file name that IS 40 hex characters: exactly what `--pretty=format:%H` puts
# in front of a commit's paths, so a record parser that sniffs for "40 chars, all
# hex" reads this path as a commit header and drops the path with it.
HEX_NAME = "deadbeef" * 5


def _cfg(repo, **kv):
    """Write the config LAST in each test: uncommitted config still governs the
    run (sync_verify reads the working tree), and keeping it out of the commits
    under test means a branch switch cannot revert it."""
    path = repo / ".ai" / "sync_config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(kv)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _auth(repo, name, editable, verdict="accepted", pinned=(), base=None,
          status=None):
    adir = repo / ".ai" / "state" / "authorizations"
    adir.mkdir(parents=True, exist_ok=True)
    lines = [f"# Authorization — {name}", "", "## Editable files", ""]
    lines += [f"- `{p}`" for p in editable]
    if pinned:
        lines += ["", "## Pinned baselines", ""]
        lines += [f"- `{p}`: SHA-256 `{'a' * 64}`" for p in pinned]
    text = "\n".join(lines) + "\n"
    if verdict is not None:
        block = ("tier: T2\nexecutor: harness-a/model-1\n"
                 "reviewer: harness-b/model-2\n"
                 f"verdict: {verdict}\n")
        if base:
            block += f"window_start_commit: {base}\n"
        if status:
            block += f"status: {status}\n"
        text += f"\n## Governance\n\n```governance\n{block}```\n"
    (adir / f"{name}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def sv_mod(ai_repo):
    """`sync_verify` AND the `ai_common` it imports, loaded from inside the
    fixture install so patching a probe reaches the copy the check calls.

    The copy is the one `install_layout()` accepts and the one an operator runs;
    patching `mod.ai_common` instead of `mod`'s own name is deliberate:
    `check_coverage_walk` calls `ai_common.is_shallow(ROOT)` through the module,
    so that is the seam the answer has to be written on. `SCRIPTS` is off `sys.path`
    for the whole load (the installed `ai_common` would otherwise be shadowed by
    this checkout's), which is why the import bookkeeping is not optional.
    """
    name = "_sv_under_test_coverage_walk"
    saved_ai_common = sys.modules.pop("ai_common", None)
    saved_scripts = None
    scripts = str(SCRIPTS)
    if scripts in sys.path:
        sys.path.remove(scripts)
        saved_scripts = scripts
    try:
        spec = importlib.util.spec_from_file_location(
            name, str(ai_repo / ".ai" / "scripts" / "sync_verify.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        mod.ROOT = ai_repo
        mod.AI_DIR = ai_repo / ".ai"
        mod.RESULTS.clear()
        yield mod
    finally:
        sys.modules.pop(name, None)
        del mod.RESULTS[:]
        sys.modules.pop("ai_common", None)
        if saved_ai_common is not None:
            sys.modules["ai_common"] = saved_ai_common
        if saved_scripts is not None:
            sys.path.insert(0, saved_scripts)


def test_uncovered_protected_commit_is_a_named_fail(ai_repo, sv):
    window = git(ai_repo, "rev-parse", "HEAD")
    (ai_repo / "protected").mkdir()
    (ai_repo / "protected" / "model.py").write_text("x = 1\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "touch a protected path")
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    fails = [ln for ln in res.lines
             if ln.startswith("[FAIL] path coverage:")]
    assert len(fails) == 1, res.lines
    assert "uncovered" in fails[0], fails[0]
    # The evidence must name WHICH commit and WHICH path, or the operator has
    # nothing to go and authorise.
    assert "protected/model.py" in fails[0], fails[0]


def test_protected_commit_covered_by_accepted_authorization_passes(ai_repo, sv):
    window = git(ai_repo, "rev-parse", "HEAD")
    _auth(ai_repo, "stage-one", ["protected/*"])
    (ai_repo / "protected").mkdir()
    (ai_repo / "protected" / "model.py").write_text("x = 1\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "touch a protected path")
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] path coverage:")
               for ln in res.lines), res.lines
    assert not any(ln.startswith("[FAIL] path coverage:")
                   for ln in res.lines), res.lines


def test_non_accepted_authorization_does_not_cover(ai_repo, sv):
    """`verdict: pending` is not an authorization; counting it would be the
    fail-open this gate exists to close."""
    window = git(ai_repo, "rev-parse", "HEAD")
    _auth(ai_repo, "stage-one", ["protected/*"], verdict="pending")
    (ai_repo / "protected").mkdir()
    (ai_repo / "protected" / "model.py").write_text("x = 1\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "touch a protected path")
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] path coverage:") and "uncovered" in ln
               for ln in res.lines), res.lines


def test_merge_only_protected_touch_fails(ai_repo, sv):
    """The protected path is introduced BY THE MERGE COMMIT and by no parent.

    Nothing in the `--no-merges` pass can see this shape, so a green run here
    would mean the second pass was never wired in.
    """
    window = git(ai_repo, "rev-parse", "HEAD")
    git(ai_repo, "checkout", "-q", "-b", "side")
    (ai_repo / "side_only.md").write_text("side work\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "side work")
    git(ai_repo, "checkout", "-q", "main")
    (ai_repo / "main_only.md").write_text("main work\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "main work")
    git(ai_repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    (ai_repo / "protected").mkdir()
    (ai_repo / "protected" / "evil.md").write_text("only in the merge\n",
                                                   encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "merge side, evil resolution")
    row = git(ai_repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(row) == 3, f"HEAD is not a merge commit: {row}"
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] path coverage:") and "protected/evil.md"
               in ln for ln in res.lines), res.lines
    # And the same shape DOES become green once authorised, so the red above is
    # the missing authorization and not the walk failing to run at all.
    _auth(ai_repo, "merge-stage", ["protected/evil.md"])
    again = run_python(sv, cwd=ai_repo)
    assert again.rc == 0, again.stdout + again.stderr
    assert any(ln.startswith("[PASS] path coverage:")
               for ln in again.lines), again.lines


def test_empty_protected_paths_skips_by_name(ai_repo, sv):
    """spec 7: the default is an EMPTY list, and that is a named SKIP rather
    than a pretending-to-govern PASS."""
    _cfg(ai_repo, protected_paths=[],
         governance={"window_start_commit": git(ai_repo, "rev-parse", "HEAD")})
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    skip = [ln for ln in res.lines if ln.startswith("[SKIP] path coverage:")]
    assert len(skip) == 1, res.lines
    assert "no-protected-paths" in skip[0], skip[0]


def test_unset_or_no_history_window_skips_by_name(ai_repo, sv):
    for governance, marker in (({}, "unset"),
                               ({"window_start_commit": ""}, "unset"),
                               ({"window_start_commit": "NO_HISTORY"},
                                "NO_HISTORY")):
        _cfg(ai_repo, protected_paths=["protected/*"], governance=governance)
        res = run_python(sv, cwd=ai_repo)
        assert res.rc == 0, (governance, res.stdout + res.stderr)
        skip = [ln for ln in res.lines
                if ln.startswith("[SKIP] path coverage:")]
        assert len(skip) == 1, (governance, res.lines)
        assert "no-window" in skip[0] and marker in skip[0], (governance, skip)


def test_an_unresolvable_window_halts_the_walk(ai_repo, sv):
    """UNKNOWN halts: an absent window sha is a FAIL naming the walk, never the
    `0 protected touches covered` a silently empty log would print."""
    (ai_repo / "protected").mkdir()
    (ai_repo / "protected" / "model.py").write_text("x\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "protected work")
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": "0" * 40})
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] path coverage:") and "walk halted" in ln
               for ln in res.lines), res.lines


def test_a_malformed_case_policy_is_refused(ai_repo, sv):
    """D14: the case policy is recorded in config, and only the two named
    policies mean anything, so a third value cannot govern by accident."""
    _cfg(ai_repo, protected_paths_case="folded")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 2, res.stdout + res.stderr
    assert any("malformed:" in ln and "protected_paths_case" in ln
               for ln in res.lines), res.lines


# ------------------------------------------------- the continuation --------
def test_a_multi_path_commit_must_cover_every_path_it_touches(ai_repo, sv):
    """TWO protected paths in ONE commit: authorising only the first is the
    incident this test exists for.

    `git log --name-only -z` returns the commit as a header record glued to its
    first path and one record per later path, so a walk that keeps only the
    first line of each commit sees `protected/a.py`, calls the commit covered,
    and prints a PASS over `protected/b.py` — the unauthorised half of the work
    disappears instead of turning red. The red line below therefore names the
    SECOND path, its own commit's short sha, and the measured total; the green
    half then shows the same commit certifying once both are authorised, so the
    red cannot be the walk failing to run at all.
    """
    window = git(ai_repo, "rev-parse", "HEAD")
    prot = ai_repo / "protected"
    prot.mkdir()
    (prot / "a.py").write_text("a = 1\n", encoding="utf-8")
    (prot / "b.py").write_text("b = 1\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "two protected paths, one commit")
    touch = git(ai_repo, "rev-parse", "HEAD")
    _auth(ai_repo, "stage-one", ["protected/a.py"])
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    fails = [ln for ln in res.lines if ln.startswith("[FAIL] path coverage:")]
    assert len(fails) == 1, res.lines
    assert "protected/b.py" in fails[0], fails[0]
    # Both paths reached the walk (2 touches), one of them is bare (1 uncovered),
    # and the bare one is still parented to the commit that made it.
    assert "1 uncovered of 2 protected touches" in fails[0], fails[0]
    assert touch[:8] in fails[0], fails[0]
    assert not any(ln.startswith("[PASS] path coverage:")
                   for ln in res.lines), res.lines

    _auth(ai_repo, "stage-one", ["protected/a.py", "protected/b.py"])
    again = run_python(sv, cwd=ai_repo)
    assert again.rc == 0, again.stdout + again.stderr
    assert any(ln.startswith("[PASS] path coverage: 2 protected touches covered")
               for ln in again.lines), again.lines


def test_a_file_whose_name_is_40_hex_chars_survives_as_a_path(ai_repo, sv):
    """The fail-open the header sniff used to book: a REAL top-level file whose
    name is exactly 40 hex characters, listed after another path in one commit.

    Such a path arrives as a continuation record — a single line, no header — and
    "40 characters, all hex" is the whole test the old parser used to decide a
    line was a commit id. It therefore ate the file name as a sha and dropped the
    path with it: an unauthorised change to that file verified green. The
    assertion is the survival itself: the name is counted as a touch, named as
    the uncovered one, and parented to the commit that touched it.
    """
    window = git(ai_repo, "rev-parse", "HEAD")
    (ai_repo / "aaa.py").write_text("a = 1\n", encoding="utf-8")
    (ai_repo / HEX_NAME).write_text("h = 1\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "a real file named like a commit id")
    touch = git(ai_repo, "rev-parse", "HEAD")
    _auth(ai_repo, "stage-one", ["aaa.py"])
    _cfg(ai_repo, protected_paths=["aaa.py", HEX_NAME],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    fails = [ln for ln in res.lines if ln.startswith("[FAIL] path coverage:")]
    assert len(fails) == 1, res.lines
    assert HEX_NAME in fails[0], fails[0]
    assert "1 uncovered of 2 protected touches" in fails[0], fails[0]
    assert touch[:8] in fails[0], fails[0]

    _auth(ai_repo, "stage-one", ["aaa.py", HEX_NAME])
    again = run_python(sv, cwd=ai_repo)
    assert again.rc == 0, again.stdout + again.stderr
    assert any(ln.startswith("[PASS] path coverage: 2 protected touches covered")
               for ln in again.lines), again.lines


# -------------------------------------------------------- the halt ---------
def _governed_covered_touch(repo):
    """One protected commit with an authorization that covers it, returning the
    window sha. Everything the walk can certify IS certified, so the only thing
    left that can make it red is history it cannot see."""
    window = git(repo, "rev-parse", "HEAD")
    (repo / "protected").mkdir()
    (repo / "protected" / "model.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "protected work")
    _auth(repo, "stage-one", ["protected/*"])
    return window


@pytest.mark.parametrize("answer,halting", [("TRUE", True), ("UNKNOWN", True),
                                            ("FALSE", False)])
def test_the_shallow_or_indeterminate_halt_is_pinned_on_this_host(
        ai_repo, sv_mod, monkeypatch, capsys, answer, halting):
    """`is_shallow != "FALSE"` halts: TRUE means the history is truncated, and
    UNKNOWN means git could not even say, so a bounded walk may not book a green
    either way (spec 6: `UNKNOWN` halts).

    Patched rather than cloned because the real thing needs `git clone --depth 1
    file://…`, which this host cannot run — see the POSIX-marked test below. The
    FALSE row is the control that keeps this from passing vacuously: the same
    tree, the same config and the same records DO certify green the moment
    history is complete, so the red on the other two rows is the probe's answer
    and nothing else.
    """
    window = _governed_covered_touch(ai_repo)
    monkeypatch.setattr(sv_mod.ai_common, "is_shallow", lambda root: answer)
    cfg = sv_mod.load_config(sv_mod.AI_DIR / "sync_config.json")[0]
    cfg["protected_paths"] = ["protected/*"]
    cfg["protected_paths_case"] = "case-sensitive"
    cfg["governance"] = {"window_start_commit": window}
    sv_mod.RESULTS.clear()

    sv_mod.check_coverage_walk(cfg)

    printed = [ln for ln in capsys.readouterr().out.splitlines()
               if ln.startswith(("[PASS] path coverage:",
                                 "[FAIL] path coverage:",
                                 "[SKIP] path coverage:"))]
    assert len(sv_mod.RESULTS) == 1, sv_mod.RESULTS
    assert len(printed) == 1, printed
    name, ok, evidence = sv_mod.RESULTS[0]
    assert name == "path coverage", name
    if not halting:
        assert printed[0] == "[PASS] path coverage: 1 protected touches " \
                             "covered", printed[0]
        assert ok is True, evidence
        return
    assert printed[0].startswith("[FAIL] path coverage:"), printed[0]
    assert "shallow/indeterminate" in printed[0], printed[0]
    assert f"shallow/indeterminate history ({answer.lower()})" in evidence, \
        evidence
    assert "cannot certify coverage" in evidence, evidence
    assert "protected touches covered" not in evidence, evidence
    assert ok is False, f"{answer} must halt the walk, and it said: {evidence}"


@pytest.mark.posix
def test_a_real_shallow_clone_halts_the_walk(ai_repo, sv):
    """The same red line reached through git instead of through a patch.

    In a `--depth 1` clone the whole window is missing, so a walk that answered
    "0 protected touches" would be certifying coverage from history that was
    never fetched. Skipped on a host that cannot build the clone — which is
    precisely why the patched test above is the one that governs here.
    """
    window = _governed_covered_touch(ai_repo)
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": window})
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "install the verifier and its records")
    shallow = ai_repo.parent / "shallow-clone"
    git(ai_repo.parent, "clone", "-q", "--depth", "1", "--",
        ai_repo.as_uri(), str(shallow))
    script = shallow / ".ai" / "scripts" / "sync_verify.py"
    assert script.is_file(), "the shallow clone carried no installed verifier"

    res = run_python(script, cwd=shallow)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] path coverage:")
               and "shallow/indeterminate" in ln
               for ln in res.lines), res.lines
    assert not any(ln.startswith("[PASS] path coverage:")
                   for ln in res.lines), res.lines


# ------------------------------------------------ the anchor's SHAPE (I-1) --
#
# Final review I-1, MEASURED on this host: with a real protected commit and no
# covering authorization, `window_start_commit: "HEAD"` printed
# `[PASS] path coverage: 0 protected touches covered` at rc 0. `git log
# HEAD..HEAD` is a permanently empty range, so the walk governed nothing and
# booked the line a walk over a genuinely empty window would have booked. The
# predicate that refuses such an anchor already existed — in `init_sync`, as a
# private `_window_is_valid`, so only the writer of the field ever enforced it.
# `ai_common.window_is_valid` is that one predicate, now read by both.


@pytest.mark.parametrize("anchor", ["HEAD", "main", "a" * 39, "A" * 40,
                                    "HEAD~1", "not-a-rev"])
def test_a_non_commit_window_anchor_fails_rather_than_governing_nothing(
        ai_repo, sv, anchor):
    """A malformed anchor is an unreadable window, not an empty one (I-1).

    `A`*40 is in the set on purpose: git resolves an uppercase id happily, and the
    migrator still refuses to WRITE one, so a verifier that accepted it would
    certify a field the tooling calls corrupt — and a short prefix would certify a
    range that resolves to a different commit on a host with more history.
    """
    (ai_repo / "protected").mkdir()
    (ai_repo / "protected" / "model.py").write_text("x\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "protected work nobody authorised")
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": anchor})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, (anchor, res.stdout + res.stderr)
    fails = [ln for ln in res.lines if ln.startswith("[FAIL] path coverage:")]
    assert len(fails) == 1, (anchor, res.lines)
    assert "window anchor is not a commit id" in fails[0], fails[0]
    assert anchor in fails[0], fails[0]
    assert not any(ln.startswith("[PASS] path coverage:")
                   for ln in res.lines), (anchor, res.lines)


def test_a_valid_anchor_still_governs_the_same_tree(ai_repo, sv):
    """The control the test above needs: the SAME tree and records, the anchor
    spelled as a 40-hex id, reaches the real uncovered FAIL — so the red above is
    the anchor's shape and not the walk never running."""
    window = git(ai_repo, "rev-parse", "HEAD")
    (ai_repo / "protected").mkdir()
    (ai_repo / "protected" / "model.py").write_text("x\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "protected work nobody authorised")
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] path coverage:") and "uncovered" in ln
               for ln in res.lines), res.lines


# ------------------------------------------------ the CASE POLICY (I-2) ----
#
# Final review I-2, MEASURED on this host: `protected_paths: ["SRC/*"]` with
# `protected_paths_case: "case-insensitive"` printed `[PASS] path coverage: 0
# protected touches covered` over a commit that touched `src/engine.py`, while
# `glob_match` — the same D14 policy — said that file IS protected. The policy
# only ever filtered the EDITABLE side, so the candidate set came from git with a
# case-SENSITIVE pathspec and the governed work never reached the check at all:
# under-govern, and read green. `:(icase)` is git's own case-insensitive pathspec
# magic, and it is what makes the recorded policy mean the same thing on the
# candidate side that it means on the editable side.


def _case_fixture(repo):
    """One commit touching `src/engine.py`, window anchored, no authorization."""
    window = git(repo, "rev-parse", "HEAD")
    (repo / "src").mkdir()
    (repo / "src" / "engine.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "protected work under a folded pattern")
    return window


def test_case_insensitive_policy_reaches_the_candidate_set(ai_repo, sv):
    """D14 honoured on BOTH sides of the comparison (I-2)."""
    window = _case_fixture(ai_repo)
    _cfg(ai_repo, protected_paths=["SRC/*"], protected_paths_case="case-insensitive",
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    fails = [ln for ln in res.lines if ln.startswith("[FAIL] path coverage:")]
    assert len(fails) == 1, res.lines
    assert "src/engine.py" in fails[0], fails[0]
    assert "uncovered" in fails[0], fails[0]
    assert not any(ln.startswith("[PASS] path coverage:")
                   for ln in res.lines), res.lines


def test_case_insensitive_policy_covers_once_the_record_says_so(ai_repo, sv):
    """Positive control: the red above is the missing authorization, and the
    folded pattern still matches when a record lists the path — so the fix did not
    turn the policy into a permanent FAIL."""
    window = _case_fixture(ai_repo)
    _auth(ai_repo, "folded-stage", ["src/*"])
    _cfg(ai_repo, protected_paths=["SRC/*"], protected_paths_case="case-insensitive",
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] path coverage:")
               and "1 protected touches covered" in ln
               for ln in res.lines), res.lines


# ------------------------------------------------ the VOID SET (I-2 guard) --
#
# The same walk over a protected set that names no tracked file at all — a typo,
# a renamed directory, a pattern written for a different layout — is permanently
# green for exactly the same reason: zero candidates, zero touches, one PASS.
# Spec 4: a degradation is a named WARN/SKIP, never a PASS.


def test_a_protected_set_matching_no_tracked_file_is_a_named_warn(ai_repo, sv):
    window = _case_fixture(ai_repo)
    _cfg(ai_repo, protected_paths=["src/core/*", "nope/**"],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    cov = [ln for ln in res.lines
           if ln.startswith(("[PASS] path coverage:", "[FAIL] path coverage:",
                             "[SKIP] path coverage:"))]
    assert len(cov) == 1, res.lines
    assert cov[0].startswith("[SKIP] path coverage:"), cov[0]
    assert "void-protected-set" in cov[0], cov[0]
    assert any(ln.startswith("[WARN] path coverage:") for ln in res.lines), \
        res.lines
    assert res.rc == 0, res.stdout + res.stderr


def test_a_protected_set_that_does_match_tracked_files_books_the_pass(ai_repo, sv):
    """Control for the guard above: a real governed file, untouched in the window,
    still certifies green — so the SKIP above is the void set and not a walk that
    simply never finds anything."""
    (ai_repo / "src").mkdir()
    (ai_repo / "src" / "engine.py").write_text("x = 1\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "the governed file, landed before the window")
    window = git(ai_repo, "rev-parse", "HEAD")
    _cfg(ai_repo, protected_paths=["src/*"],
         governance={"window_start_commit": window})

    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] path coverage:")
               and "0 protected touches covered" in ln
               for ln in res.lines), res.lines


def test_an_indeterminate_void_check_cannot_book_the_pass(ai_repo, sv_mod,
                                                          monkeypatch, capsys):
    """If git cannot say whether the protected set is empty, the walk does not get
    to answer "covered" either.

    Final-review re-review NEW-1: this arm printed its `[WARN]` and fell through
    to the PASS below it, so a `git ls-files` that timed out or could not read the
    index booked `[PASS] path coverage: 0 protected touches covered` at rc 0 —
    spec 4's forbidden shape, and the same empty-window that the void-set test
    above SKIPs by name. The control is that same tree unpatched, which DOES pass:
    only the probe's answer changed.
    """
    (ai_repo / "src").mkdir()
    (ai_repo / "src" / "engine.py").write_text("x = 1\n", encoding="utf-8")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "the governed file, landed before the window")
    window = git(ai_repo, "rev-parse", "HEAD")
    cfg = sv_mod.load_config(sv_mod.AI_DIR / "sync_config.json")[0]
    cfg["protected_paths"] = ["src/*"]
    cfg["protected_paths_case"] = "case-sensitive"
    cfg["governance"] = {"window_start_commit": window}
    sv_mod.RESULTS.clear()

    real_run_git = sv_mod.ai_common.run_git

    def failing_ls_files(root, args, **kw):
        if args and args[0] == "ls-files":
            return sv_mod.ai_common.GitResult(
                rc=128, stdout=b"",
                stderr=b"unable to read index: simulated", timed_out=False)
        return real_run_git(root, args, **kw)

    monkeypatch.setattr(sv_mod.ai_common, "run_git", failing_ls_files)

    sv_mod.check_coverage_walk(cfg)

    printed = capsys.readouterr().out.splitlines()
    assert not [ln for ln in printed if ln.startswith("[PASS] path coverage:")], \
        printed
    assert any(ln.startswith("[WARN] path coverage:") for ln in printed), printed
    assert len(sv_mod.RESULTS) == 1, sv_mod.RESULTS
    name, ok, evidence = sv_mod.RESULTS[0]
    assert (name, ok) == ("path coverage", None), sv_mod.RESULTS
    assert "void-check-unavailable" in evidence, evidence
    assert "unable to read index" in evidence, evidence




# --------------------------------------- THE NARROWING GUARD (wave 1d Q2) ----
#
# `governance.window_start_commit` is one config line, and the walk's reach is
# exactly that line: moving it forward drops the commits before it out of the
# range, where they read as neither covered nor uncovered because nothing looks
# at them any more. The release face closed this in wave 1c (C4-19/C4-20) by
# asking each accepted record to declare the base it started from and refusing an
# anchor that has passed one; the runtime face had no such question to ask until
# runtime records carried `window_start_commit:` too. These four pin the guard
# and — E-4, the one that keeps an old install working — what it deliberately
# does NOT do.


def _narrowing_tree(repo):
    """(base, anchor) around one protected commit that only the wider window sees.

    The protected work lands in the commit BEFORE `anchor`, so `anchor..HEAD`
    walks an empty range: the shape that reads green today and is the whole
    defect. `base` is what an honest record declares as where its stage began.
    """
    base = git(repo, "rev-parse", "HEAD")
    (repo / "protected").mkdir()
    (repo / "protected" / "model.py").write_text("x\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "protected work nobody re-authorised")
    git(repo, "commit", "--allow-empty", "-q", "-m", "the commit a narrowed anchor starts at")
    return base, git(repo, "rev-parse", "HEAD")


def test_an_anchor_past_a_live_records_base_is_a_named_fail(ai_repo, sv):
    base, anchor = _narrowing_tree(ai_repo)
    _auth(ai_repo, "live-stage", ["protected/*"], base=base)
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": anchor})
    res = run_python(sv, cwd=ai_repo)
    fails = [ln for ln in res.lines if ln.startswith("[FAIL] path coverage:")]
    assert len(fails) == 1, res.lines
    assert "live-stage.md" in fails[0], fails[0]
    assert "not at-or-after" in fails[0], fails[0]
    assert not any(ln.startswith("[PASS] path coverage:") for ln in res.lines), \
        res.lines


def test_an_anchor_at_its_records_base_still_walks(ai_repo, sv):
    """The control: the red above is the anchor's position, not a guard that
    cannot read a window at all. Same tree, same record, honest anchor."""
    base, _anchor = _narrowing_tree(ai_repo)
    _auth(ai_repo, "live-stage", ["protected/*"], base=base)
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": base})
    res = run_python(sv, cwd=ai_repo)
    assert any(ln.startswith("[PASS] path coverage: 1 protected touches covered")
               for ln in res.lines), res.lines
    assert not any(ln.startswith("[FAIL] path coverage:") for ln in res.lines), \
        res.lines


def test_a_closed_record_does_not_bind_the_window_forever(ai_repo, sv):
    """W24's finding, mirrored onto the runtime walk: re-anchoring at a new wave is
    the lifecycle, and holding a finished stage's base in the window for good makes
    the next wave red with "edit an approved record" as its only exit — strictly
    worse than the hole it closes. So `status: closed` steps out, and this test
    exists to keep that exemption from being quietly widened to live records.
    """
    base, anchor = _narrowing_tree(ai_repo)
    _auth(ai_repo, "finished-stage", ["protected/*"], base=base,
          status="closed")
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": anchor})
    res = run_python(sv, cwd=ai_repo)
    assert any(ln.startswith("[PASS] path coverage: 0 protected touches covered")
               for ln in res.lines), res.lines


def test_a_record_that_declares_no_base_bounds_nothing(ai_repo, sv):
    """The asymmetry against the release face, pinned rather than assumed.

    `release authorization` FAILs an accepted live record that states no base,
    because that field is new and the template has required it from the first
    release record. Runtime records predate it by three versions, and an accepted
    one cannot be edited to add a line it never carried — so a missing base here
    is no claim, and refusing the walk would make every existing install red for
    its own history. What that leaves unguarded is named in
    `docs/evidence/wave1d-queue.md` rather than hidden behind this PASS.
    """
    _base, anchor = _narrowing_tree(ai_repo)
    _auth(ai_repo, "older-stage", ["protected/*"])
    _cfg(ai_repo, protected_paths=["protected/*"],
         governance={"window_start_commit": anchor})
    res = run_python(sv, cwd=ai_repo)
    assert any(ln.startswith("[PASS] path coverage: 0 protected touches covered")
               for ln in res.lines), res.lines
