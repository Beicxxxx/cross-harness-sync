"""Task 5: you cannot release someone else's pen (D2, D8-adjacent).

`cmd_unlock` only looked at the holder when `--agent` happened to be passed, so
a bare `--unlock` — the exact command `--prime` and `--handoff` told users to
run — silently dropped a live holder and freed the pen for a second writer.
These tests pin the authority rule (rc 2 for the missing name, rc 1 for the
wrong one) and the advertised command form.
"""
import json

from helpers import run_python, write_lock


def held(agent="codex"):
    return json.dumps({"agent": agent, "reason": "x",
                       "acquired_at": "2026-09-21T10:00:00+10:00",
                       "expires_at": "2099-01-01T00:00:00+10:00",
                       "released_at": None})


def test_bare_unlock_refused_against_live_lock(ai_repo, cp):
    """D2: --prime told users to run exactly this command."""
    write_lock(ai_repo, held())
    res = run_python(cp, ["--unlock"], cwd=ai_repo)
    assert res.rc == 2, res.stdout
    assert "--agent" in res.stdout, res.stdout
    assert json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                      .read_text("utf-8-sig"))["released_at"] is None


def test_owner_may_unlock(ai_repo, cp):
    write_lock(ai_repo, held())
    res = run_python(cp, ["--unlock", "--agent", "codex"], cwd=ai_repo)
    assert res.rc == 0
    assert json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                      .read_text("utf-8-sig"))["released_at"]


def test_non_owner_may_not_unlock(ai_repo, cp):
    write_lock(ai_repo, held())
    res = run_python(cp, ["--unlock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1 and "not claude-code" in res.stdout


def test_prime_and_handoff_advertise_the_safe_form(ai_repo, cp):
    for args in ([], ["--handoff", "--agent", "codex"]):
        res = run_python(cp, args, cwd=ai_repo) if args else \
            run_python(cp, ["--prime"], cwd=ai_repo)
        assert res.rc == 0, res.stdout
        assert "--unlock --agent" in res.stdout, (args, res.stdout)
        assert "release the lock (--unlock)" not in res.stdout


def test_the_reason_law_does_not_reach_the_release_path(ai_repo, cp):
    """Negative partner for C1's gate: `--force` must name a reason when it TAKES
    a pen, because that is the act the record has to explain. Putting one back
    needs no explanation, and asking for it would be the hard enforcement this
    protocol deliberately refuses (spec 4: advisory, and a release can only help
    the next writer).

    Regression pin rather than a fix: green at HEAD, and it is what keeps a later
    widening of the gate from silently swallowing the unlock.
    """
    write_lock(ai_repo, held(agent="codex"))
    res = run_python(cp, ["--unlock", "--agent", "claude-code", "--force"],
                     cwd=ai_repo)
    assert res.rc == 0, res.stdout
    record = json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                        .read_text("utf-8-sig"))
    assert record["released_by"] == "claude-code", record
    assert record["released_at"], record
