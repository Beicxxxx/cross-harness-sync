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
"""
import json

from helpers import git, run_python


def _cfg(repo, **kv):
    """Write the config LAST in each test: uncommitted config still governs the
    run (sync_verify reads the working tree), and keeping it out of the commits
    under test means a branch switch cannot revert it."""
    path = repo / ".ai" / "sync_config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(kv)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _auth(repo, name, editable, verdict="accepted", pinned=()):
    adir = repo / ".ai" / "state" / "authorizations"
    adir.mkdir(parents=True, exist_ok=True)
    lines = [f"# Authorization — {name}", "", "## Editable files", ""]
    lines += [f"- `{p}`" for p in editable]
    if pinned:
        lines += ["", "## Pinned baselines", ""]
        lines += [f"- `{p}`: SHA-256 `{'a' * 64}`" for p in pinned]
    text = "\n".join(lines) + "\n"
    if verdict is not None:
        text += ("\n## Governance\n\n```governance\n"
                 "tier: T2\nexecutor: harness-a/model-1\n"
                 f"reviewer: harness-b/model-2\nverdict: {verdict}\n```\n")
    (adir / f"{name}.md").write_text(text, encoding="utf-8")


def _touch(repo, rel, sha_window):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("changed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"touch {rel}")
    return sha_window


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
