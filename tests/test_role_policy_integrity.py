"""spec 6.2 — `ROLE_POLICY.md` is required (lane B3's list) AND its SHA-256 is
pinned in config, so changing the governance document requires a config edit,
which is a diff a human actually reads.

Anchor-string grepping was rejected by the design (a `"T1" in text` test is
satisfied by "R12" and survives deleting the table it is supposed to prove), so
this check asks exactly one decidable question: do the bytes on disk hash to the
bytes config promises? An unpinned install gets a named SKIP, never a PASS for
having nothing to compare.
"""
import hashlib
import json

from helpers import run_python

REL = ".ai/state/ROLE_POLICY.md"


def _policy_path(repo):
    return repo / ".ai" / "state" / "ROLE_POLICY.md"


def _sha(repo):
    return hashlib.sha256(_policy_path(repo).read_bytes()).hexdigest()


def _set_sha(repo, value):
    path = repo / ".ai" / "sync_config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["role_policy_sha256"] = value
    path.write_text(json.dumps(cfg), encoding="utf-8")


def test_nothing_pinned_is_a_named_skip(ai_repo, sv):
    _set_sha(ai_repo, "")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    skips = [ln for ln in res.lines
             if ln.startswith("[SKIP] role policy integrity:")]
    assert len(skips) == 1, res.lines
    assert "no-sha-pinned" in skips[0], skips[0]
    assert not any(ln.startswith("[PASS] role policy integrity:")
                   for ln in res.lines), res.lines


def test_a_matching_digest_passes(ai_repo, sv):
    _set_sha(ai_repo, _sha(ai_repo))
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] role policy integrity:")
               for ln in res.lines), res.lines


def test_a_rewritten_policy_fails_the_pinned_digest(ai_repo, sv):
    pinned = _sha(ai_repo)
    _set_sha(ai_repo, pinned)
    _policy_path(ai_repo).write_text("# Role policy — quietly rewritten\n",
                                     encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    fails = [ln for ln in res.lines
             if ln.startswith("[FAIL] role policy integrity:")]
    assert len(fails) == 1, res.lines
    assert pinned[:12] in fails[0] or "digest" in fails[0], fails[0]


def test_a_missing_policy_with_a_pinned_digest_fails(ai_repo, sv):
    """No silent skip: the file is a required one, and its absence is exactly
    what a pinned digest exists to catch. `required ...` names presence for the
    default path, and here the pinned promise is broken regardless."""
    pinned = _sha(ai_repo)
    _set_sha(ai_repo, pinned)
    _policy_path(ai_repo).unlink()
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] role policy integrity:")
               and REL in ln for ln in res.lines), res.lines


def test_a_digest_that_is_not_sha256_is_refused(ai_repo, sv):
    for bad in ("nope", "A" * 64, "a" * 63):
        _set_sha(ai_repo, bad)
        res = run_python(sv, cwd=ai_repo)
        assert res.rc == 2, (bad, res.stdout + res.stderr)
        assert any("malformed:" in ln and "role_policy_sha256" in ln
                   for ln in res.lines), (bad, res.lines)
