"""N1 — the swarm boundary. The protocol mandates "one stage = one
authorization file" and SKILL.md declares concurrent swarms out of scope, yet
before this check a directory holding TWO accepted authorizations verified
green: every other check reads one file at a time, so nothing asked how many
authorizations were live at once. That is the gap N1 closes, and the red line
below is the whole point of the check.

A record with no `## Governance` block is the spec-6 legacy degradation: it is
named as a WARN/SKIP and never counted as accepted, so it also makes the
concurrency count undecidable rather than quietly PASSing. A block that parses
but names no `verdict:` is the same hole wearing better clothes, and it is named
too.
"""
from helpers import run_python


def _auth(repo, name, verdict="accepted", editable=("src/app.py",)):
    adir = repo / ".ai" / "state" / "authorizations"
    adir.mkdir(parents=True, exist_ok=True)
    text = (f"# Authorization — {name}\n\n## Editable files\n\n"
            + "".join(f"- `{p}`\n" for p in editable))
    if verdict is not None:
        text += ("\n## Governance\n\n```governance\n"
                 "tier: T2\nexecutor: harness-a/model-1\n"
                 f"reviewer: harness-b/model-2\nverdict: {verdict}\n```\n")
    (adir / f"{name}.md").write_text(text, encoding="utf-8")


def test_two_accepted_authorizations_are_a_named_fail(ai_repo, sv):
    _auth(ai_repo, "stage-a")
    _auth(ai_repo, "stage-b")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    fails = [ln for ln in res.lines if ln.startswith("[FAIL] swarm boundary:")]
    assert len(fails) == 1, res.lines
    # The exact count phrase and BOTH record names: `"2" in line` was satisfied
    # by any line carrying the digit 2 anywhere — a window sha, a byte count, a
    # "1 more" tail — so it never proved the boundary was the thing that broke.
    assert "2 concurrent accepted authorizations" in fails[0], fails[0]
    assert "stage-a.md" in fails[0], fails[0]
    assert "stage-b.md" in fails[0], fails[0]
    assert "out of scope" in fails[0], fails[0]


def test_one_accepted_authorization_passes_naming_the_count(ai_repo, sv):
    _auth(ai_repo, "stage-a")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    passes = [ln for ln in res.lines if ln.startswith("[PASS] swarm boundary:")]
    assert len(passes) == 1, res.lines
    assert "1 accepted authorization(s) of 1 record(s)" in passes[0], passes[0]


def test_no_records_at_all_passes_with_zero(ai_repo, sv):
    adir = ai_repo / ".ai" / "state" / "authorizations"
    # The installer creates the canonical home (spec 6); an empty one holds no
    # live stage record, which is the zero the boundary is satisfied by.
    assert not list(adir.glob("*.md")), list(adir.iterdir())
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    passes = [ln for ln in res.lines if ln.startswith("[PASS] swarm boundary:")]
    assert len(passes) == 1, res.lines
    assert passes[0] == ("[PASS] swarm boundary: 0 accepted authorizations: "
                         "no stage record in .ai/state/authorizations, so "
                         "nothing is live and nothing can be concurrent"), \
        passes[0]


def test_declined_and_pending_records_are_not_accepted(ai_repo, sv):
    _auth(ai_repo, "a", verdict="declined")
    _auth(ai_repo, "b", verdict="pending")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] swarm boundary:") for ln in res.lines), \
        res.lines


def test_a_legacy_record_without_a_governance_block_never_passes(ai_repo, sv):
    """spec 4/6: the absent block is a named WARN, so the concurrency question
    stays open instead of booking a PASS over a record nobody can count."""
    _auth(ai_repo, "accepted-stage")
    _auth(ai_repo, "legacy-stage", verdict=None)
    res = run_python(sv, cwd=ai_repo)
    assert not any(ln.startswith("[PASS] swarm boundary:")
                   for ln in res.lines), res.lines
    skips = [ln for ln in res.lines if ln.startswith("[SKIP] swarm boundary:")]
    assert len(skips) == 1, res.lines
    assert "legacy-stage" in skips[0], skips[0]


def test_a_second_accepted_record_beside_a_legacy_one_is_still_a_fail(ai_repo, sv):
    """The legacy record must not become a way to hide a swarm: the count that
    IS decidable already breaks the boundary."""
    _auth(ai_repo, "stage-a")
    _auth(ai_repo, "stage-b")
    _auth(ai_repo, "legacy", verdict=None)
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    assert any(ln.startswith("[FAIL] swarm boundary:") for ln in res.lines), \
        res.lines


def test_a_broken_governance_block_halts_the_count(ai_repo, sv):
    """Duplicate keys are fatal in audit data (no last-wins), so a record that
    cannot be parsed cannot be counted either: FAIL naming why, not a skip."""
    adir = ai_repo / ".ai" / "state" / "authorizations"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "broken.md").write_text(
        "# Authorization — broken\n\n## Governance\n\n```governance\n"
        "tier: T2\nexecutor: a/1\nreviewer: b/2\nverdict: accepted\n"
        "verdict: declined\n```\n", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout + res.stderr
    fails = [ln for ln in res.lines if ln.startswith("[FAIL] swarm boundary:")]
    assert len(fails) == 1, res.lines
    assert "broken.md" in fails[0], fails[0]


def test_a_block_that_names_no_verdict_is_never_a_zero_pass(ai_repo, sv):
    """The other face of the legacy hole: a `## Governance` block that parses
    cleanly — no duplicate key, no placeholder — but carries no `verdict:` line.

    `parse_governance_block` returns it as a well-formed dict, so the record fell
    through `broken`, `legacy` and `accepted` without joining any of them and the
    check printed `PASS 0 accepted authorization(s) of 1 record(s)`: a green
    booked by the one file whose status is unknown, and a hiding place for a
    second accepted record. Spec 4 allows a degradation to be only a named
    WARN/SKIP, so an undecided record is named and never counted.
    """
    adir = ai_repo / ".ai" / "state" / "authorizations"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "no-verdict.md").write_text(
        "# Authorization — no verdict\n\n## Editable files\n\n- `src/app.py`\n\n"
        "## Governance\n\n```governance\n"
        "tier: T2\nexecutor: harness-a/model-1\n"
        "reviewer: harness-b/model-2\n```\n", encoding="utf-8")
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert not any(ln.startswith("[PASS] swarm boundary:")
                   for ln in res.lines), res.lines
    skips = [ln for ln in res.lines if ln.startswith("[SKIP] swarm boundary:")]
    assert len(skips) == 1, res.lines
    assert "no-verdict.md" in skips[0], skips[0]
    assert "no-verdict:" in skips[0], skips[0]
    assert "0 accepted" not in skips[0], skips[0]

