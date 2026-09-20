"""Task 4: the lock parser is a state machine whose error state is HELD (D1, D10).

`WRITER_LOCK.json` is tracked on purpose, so two machines locking it is a
guaranteed merge conflict. The conflict used to make `read_json` return `{}`,
which every consumer read as "no lock", so both agents were told the pen was
free. An unparseable or absent `expires_at` used to mean "never expires" for
`--prime` while `--lock` treated it as expired.

Each assertion below is positive (it names the text it expects); the one
negative assertion rides alongside a positive one in the same test.
"""
import json

from helpers import run_python, write_lock


def live(agent="codex", **over):
    rec = {"agent": agent, "reason": "t", "acquired_at": "2026-09-21T10:00:00+10:00",
           "expires_at": "2099-01-01T00:00:00+10:00", "released_at": None}
    rec.update(over)
    return json.dumps(rec)


def test_merge_conflict_lock_is_reported_as_held(ai_repo, cp):
    write_lock(ai_repo, "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other\n")
    res = run_python(cp, ["--status"], cwd=ai_repo)
    assert "CONFLICT" in res.stdout.upper(), res.stdout
    assert "none" not in res.stdout.split("Writer Lock")[1].split("\n")[0]


def test_corrupt_lock_blocks_acquisition(ai_repo, cp):
    write_lock(ai_repo, "not json at all")
    res = run_python(cp, ["--lock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "cannot parse" in res.stdout.lower(), res.stdout


def test_missing_expires_at_does_not_last_forever(ai_repo, cp):
    write_lock(ai_repo, json.dumps({"agent": "codex", "released_at": None}))
    res = run_python(cp, ["--prime"], cwd=ai_repo)
    assert res.rc == 0
    line = [ln for ln in res.lines if ln.startswith("Writer lock")][0]
    assert "no expiry" in line, line


def test_z_suffix_expires_at_parses(ai_repo, cp):
    write_lock(ai_repo, live(expires_at="2099-01-01T00:00:00Z"))
    res = run_python(cp, ["--lock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1, res.stdout


def test_naive_expires_at_is_treated_as_local(ai_repo, cp):
    write_lock(ai_repo, live(expires_at="2099-01-01 00:00:00"))
    res = run_python(cp, ["--status"], cwd=ai_repo)
    assert "HELD" in res.stdout, res.stdout


def test_valid_held_lock_still_refuses(ai_repo, cp):
    write_lock(ai_repo, live())
    res = run_python(cp, ["--lock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1 and "LOCK CONFLICT" in res.stdout


# The three guards below cover the parts of the new state machine that the
# (lock, holder, expired) triple could not express: `expired` used to be the
# only non-holder path, and `error` has no override at all until it is asked
# for twice.

def test_expired_lock_is_still_free_to_acquire(ai_repo, cp):
    """Refactoring holder into LockStatus must not make an expired lock a wall."""
    write_lock(ai_repo, live(expires_at="2020-01-01T00:00:00+10:00"))
    res = run_python(cp, ["--lock", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert "Writer lock acquired by claude-code" in res.stdout, res.stdout


def test_force_alone_does_not_discard_an_unreadable_lock(ai_repo, cp):
    write_lock(ai_repo, "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other\n")
    res = run_python(cp, ["--lock", "--agent", "claude-code", "--force"],
                     cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "--discard-lock" in res.stdout, res.stdout


def test_force_with_discard_lock_replaces_the_unreadable_record(ai_repo, cp):
    write_lock(ai_repo, "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other\n")
    res = run_python(cp, ["--lock", "--agent", "claude-code", "--force",
                          "--discard-lock"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert "Writer lock acquired by claude-code" in res.stdout, res.stdout
    assert "git history" in res.stdout, res.stdout
    record = json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                        .read_text("utf-8-sig"))
    assert record["agent"] == "claude-code", record
