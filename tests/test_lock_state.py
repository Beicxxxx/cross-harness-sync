"""Task 4: the lock parser is a state machine whose error state is HELD (D1, D10).

`WRITER_LOCK.json` is tracked on purpose, so two machines locking it is a
guaranteed merge conflict. The conflict used to make `read_json` return `{}`,
which every consumer read as "no lock", so both agents were told the pen was
free. An unparseable or absent `expires_at` used to mean "never expires" for
`--prime` while `--lock` treated it as expired.

Each assertion below is positive (it names the text it expects); the one
negative assertion rides alongside a positive one in the same test.
"""
import importlib.util
import json
from pathlib import Path

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


def load(cp_path):
    """Import the checkpoint.py that was copied INTO this fixture repo.

    B6/F1: the reader has to be denied a syscall, and a subprocess cannot be told
    to do that portably — `chmod 0o000` leaves the file readable on Windows,
    which is the only host this wave runs on. So the predicate is pinned at the
    function boundary against the real install layout instead of with a
    permission test that would pass vacuously.

    checkpoint.py does `from ai_common import ...` at import time, which would
    leave `ai_common` registered for the rest of the session — and
    tests/test_ai_common.py pins that an installed script's shared module is NOT
    the one in sys.modules. Its own globals keep the references it took, so the
    entry is dropped again here rather than left for a later lane's test to trip
    over.
    """
    import sys

    had_common = "ai_common" in sys.modules
    spec = importlib.util.spec_from_file_location("cp_under_test", str(cp_path))
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        if not had_common:
            sys.modules.pop("ai_common", None)
        sys.modules.pop("cp_under_test", None)
    return module


def test_denied_lock_read_is_error_and_not_free(ai_repo, cp, monkeypatch):
    """F1: `Path.exists()` returns False when the stat behind it raises
    PermissionError, so a live, unreadable lock became {} with no error.

    The three states are asserted in order, all positively: absent is still
    absent (so the fix cannot collapse everything into "error"), a readable
    record is still HELD, and a DENIED read of that same record is "error", not
    "free".
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")

    absent = mod.lock_state()
    assert (absent.state, absent.detail) == ("free", "no lock file"), absent

    lock = write_lock(ai_repo, live())
    assert mod.lock_state().state == "held", mod.lock_state()

    def deny(self):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_bytes", deny)
    data, err = mod.read_json_or_error(lock)
    assert data == {}, data
    assert err and "cannot read" in err, err
    assert "denied" in err.lower(), err
    status = mod.lock_state()
    assert status.state == "error", status
    assert status.detail == err, status


def test_unlock_never_overwrites_a_record_it_could_not_parse(ai_repo, cp,
                                                            monkeypatch, capsys):
    """F2: cmd_unlock decided from one read and then re-read for the write,
    throwing the error away, so a record that turned unparseable in between was
    replaced by a `released_at`/`released_by` stub — which the next read reports
    as free. That is the evidence-erasing behaviour this batch exists to stop.

    The second read is made to return conflict markers, which is the exact
    mid-flight race (another machine's merge landing between the check and the
    write). Either honest answer passes: abort with a named error and a nonzero
    exit, or write back the record that was actually validated. What may NOT
    happen is a stub that keeps only the release fields.
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")
    lock = write_lock(ai_repo, live())
    real_read = Path.read_bytes
    reads = []

    def second_read_conflicts(self):
        reads.append(self.name)
        if len(reads) > 1:
            return b"<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other\n"
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", second_read_conflicts)

    class Args:
        agent = "codex"
        force = False

    try:
        mod.cmd_unlock(Args())
    except SystemExit as exc:
        assert exc.code, "unlock aborted with exit code 0"
    out = capsys.readouterr().out
    assert ("UNLOCK ABORTED" in out) or (len(reads) == 1), (out, reads)
    written = json.loads(lock.read_text("utf-8-sig"))
    assert written.get("agent") == "codex", (
        f"the validated record was erased; the file now holds: {written}")
    assert written.get("expires_at"), written


# F3: the state writers never looked at the lock. A conflicted record means HELD
# (this batch's own definition), so an agent that skipped --lock could still
# rewrite runtime/STATUS.json beside it. The lock stays advisory, so the two
# cases are treated differently on purpose: unreadable blocks, another agent's
# live hold is named out loud and then proceeds.

CONFLICT = "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other\n"


def test_checkpoint_refuses_to_write_over_an_unreadable_lock(ai_repo, cp):
    status = ai_repo / ".ai" / "runtime" / "STATUS.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text('{"current_task": "DO-NOT-CLOBBER"}', encoding="utf-8")
    write_lock(ai_repo, CONFLICT)
    res = run_python(cp, ["--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "CHECKPOINT REFUSED" in res.stdout, res.stdout
    assert "unreadable" in res.stdout, res.stdout
    assert "--force" in res.stdout, res.stdout
    assert json.loads(status.read_text("utf-8-sig")) == {
        "current_task": "DO-NOT-CLOBBER"}, status.read_text("utf-8-sig")


def test_validate_and_handoff_name_another_holders_lock_and_proceed(ai_repo, cp):
    """Advisory, not enforced: a live hold by somebody else is warned by name and
    the command still runs, because nothing here may require a server."""
    write_lock(ai_repo, live(agent="codex"))
    for args, marker in ((["--handoff", "--agent", "claude-code"],
                          "Handoff prepared"),
                         (["--validate"], "state files")):
        res = run_python(cp, args, cwd=ai_repo)
        assert "WARN" in res.stdout, (args, res.stdout)
        assert "codex" in res.stdout, (args, res.stdout)
        assert marker in res.stdout, (args, res.stdout)
    status = json.loads((ai_repo / ".ai" / "runtime" / "STATUS.json")
                        .read_text("utf-8-sig"))
    assert status["status"] == "handed-off", status


def test_owner_sees_no_warning_and_force_still_writes(ai_repo, cp):
    """The guard must not nag the holder, and --force keeps its existing
    override behaviour through an unreadable record."""
    write_lock(ai_repo, live(agent="claude-code"))
    mine = run_python(cp, ["--agent", "claude-code"], cwd=ai_repo)
    assert mine.rc == 0, mine.stdout
    assert "WARN" not in mine.stdout.split("Checkpoint #")[0], mine.stdout
    assert "Checkpoint #" in mine.stdout, mine.stdout

    write_lock(ai_repo, CONFLICT)
    forced = run_python(cp, ["--agent", "claude-code", "--force"], cwd=ai_repo)
    assert forced.rc == 0, forced.stdout
    assert "WARN" in forced.stdout and "unreadable" in forced.stdout, forced.stdout
    status = json.loads((ai_repo / ".ai" / "runtime" / "STATUS.json")
                        .read_text("utf-8-sig"))
    assert status["status"] == "active", status
