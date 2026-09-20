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

import pytest
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
    """One wall, both flags (ruling 3): the pair, not the flag, clears the wall.

    C1 correction: `--reason` joins the command because `--force` now names a
    reason on EVERY path (ruling 1). Without it this command is refused by the
    gate two lines earlier and the `--discard-lock` assertion below would be
    proving the gate's wording instead of the pair's requirement.
    """
    write_lock(ai_repo, "<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other\n")
    res = run_python(cp, ["--lock", "--agent", "claude-code", "--force",
                          "--reason", "T12 handoff"], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "--discard-lock" in res.stdout, res.stdout


def test_force_with_discard_lock_replaces_the_unreadable_record(ai_repo, cp):
    """The pin batch-B7a left behind, corrected: it ran `--force` with NO
    `--reason` and asserted rc 0, which is the behaviour ruling 1 removes.

    Same command plus the reason, same rc 0 and the same replaced record — the
    discard path is unchanged apart from having to say why.
    """
    write_lock(ai_repo, CONFLICT)
    res = run_python(cp, ["--lock", "--agent", "claude-code", "--force",
                          "--discard-lock", "--reason", "T12 takeover"],
                     cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert "Writer lock acquired by claude-code" in res.stdout, res.stdout
    assert "git history" in res.stdout, res.stdout
    record = json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                        .read_text("utf-8-sig"))
    assert record["agent"] == "claude-code", record
    assert record["reason"] == "T12 takeover", record
    # The displaced half could not be parsed, so nothing was copied out of it:
    # the gap is named instead of invented.
    assert "merge conflict markers" in record["forced_over_unreadable"], record


# ---------------------------------------------------------------------------
# C1 ruling 1: `--force` on `--lock` requires `--reason` on EVERY path, not
# only over the D15 layouts batch-B7a landed. A takeover that does not say why
# is indistinguishable, in the record it leaves, from an accident — and the
# record is the only thing the next machine reads. Advisory: nothing here
# enforces the lock, it only refuses to take one silently.


def test_force_without_a_reason_is_refused_before_any_write(ai_repo, cp):
    """Red at HEAD as written: the discard path accepted a reasonless override."""
    lock = write_lock(ai_repo, CONFLICT)
    res = run_python(cp, ["--lock", "--agent", "claude-code", "--force",
                          "--discard-lock"], cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert "--force must name a --reason" in res.stdout, res.stdout
    assert "does not resolve" in res.stdout.lower(), res.stdout
    assert lock.read_text("utf-8-sig") == CONFLICT, (
        "refused the override and replaced the record anyway: "
        f"{lock.read_text('utf-8-sig')!r}")


def test_a_blank_reason_is_not_a_reason(ai_repo, cp):
    """`--reason " "` satisfies argparse and empties under strip(); it must not
    satisfy the gate, or the flag becomes a way to answer the question."""
    write_lock(ai_repo, live(agent="codex"))
    blank = run_python(cp, ["--lock", "--agent", "claude-code", "--force",
                            "--reason", "   "], cwd=ai_repo)
    assert blank.rc == 1, blank.stdout
    assert "--force must name a --reason" in blank.stdout, blank.stdout
    # The positive partner: the gate is a sentence, not a wall.
    named = run_python(cp, ["--lock", "--agent", "claude-code", "--force",
                            "--reason", "T12 takeover, recorded in the handoff"],
                       cwd=ai_repo)
    assert named.rc == 0, named.stdout


def test_a_named_takeover_records_whose_pen_it_took(ai_repo, cp):
    """Regression pin, green at HEAD: the takeover stays auditable.

    `forced_over` is copied from the displaced record so the second machine can
    see the split in git history; `epoch` is wave 1b's schema, written here and
    read by nothing in this lane's decisions.
    """
    write_lock(ai_repo, live(agent="codex", epoch=4))
    res = run_python(cp, ["--lock", "--agent", "claude-code", "--force",
                          "--reason", "T12 takeover"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    record = json.loads((ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json")
                        .read_text("utf-8-sig"))
    assert record["agent"] == "claude-code", record
    assert record["reason"] == "T12 takeover", record
    assert record["forced_over"] == {
        "agent": "codex", "epoch": 4,
        "acquired_at": "2026-09-21T10:00:00+10:00"}, record


def test_the_printed_override_is_a_command_that_works(ai_repo, cp):
    """The hints must survive their own gate.

    Red at HEAD: the conflict hint told the user to `re-run with --force`, which
    the gate then refuses — an honest agent following the printed advice gets a
    second error and no clue that the missing word is `--reason`.
    """
    write_lock(ai_repo, live(agent="codex"))
    conflict = run_python(cp, ["--lock", "--agent", "claude-code"], cwd=ai_repo)
    assert conflict.rc == 1, conflict.stdout
    assert "LOCK CONFLICT" in conflict.stdout, conflict.stdout
    assert "--force --reason" in conflict.stdout, conflict.stdout

    write_lock(ai_repo, CONFLICT)
    unreadable = run_python(cp, ["--lock", "--agent", "claude-code"],
                            cwd=ai_repo)
    assert unreadable.rc == 1, unreadable.stdout
    assert "--force --discard-lock --reason" in unreadable.stdout, \
        unreadable.stdout


def test_force_help_names_the_reason_it_requires(ai_repo, cp):
    """`--help` is the only usage text this command prints, so the gate has to
    be in it: a flag whose refusal the help does not predict is a surprise.

    The probe is one hyphenated token because argparse rewraps help text to the
    terminal width — a two-word phrase can land across a line break and the
    assertion would then depend on COLUMNS.
    """
    res = run_python(cp, ["--help"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert "reason-required" in res.stdout, res.stdout


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

    B6/6: the same argument applies to `sys.path`. Line 43 of checkpoint.py
    inserts the fixture's `.ai/scripts/` at position 0 at import time, and
    3bf7578 restored only `sys.modules`, so the deleted tmp dir stayed on the
    search path for the rest of the session — a later lane's bare
    `import ai_common` could resolve into it. Snapshot and restore the path
    list too, the way tests/test_config_merge.py:40-52 does for modules.
    """
    import sys

    had_common = "ai_common" in sys.modules
    spec = importlib.util.spec_from_file_location("cp_under_test", str(cp_path))
    module = importlib.util.module_from_spec(spec)
    saved_path = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved_path
        if not had_common:
            sys.modules.pop("ai_common", None)
        sys.modules.pop("cp_under_test", None)
    return module


def test_loader_leaves_no_fixture_path_behind(ai_repo, cp):
    """B6/6: `load()` restored sys.modules but not sys.path.

    Positive partner first: the load itself has to work, and the module it
    returns has to be usable — closing the leak must not break the import.
    """
    import sys

    before = sys.path[:]
    mod = load(cp)
    try:
        assert mod.LOCK_PATH is None, "the fixture module did not even import"
        assert str(cp.parent) not in sys.path, (
            f"load() left {cp.parent} on sys.path for the rest of the session: "
            f"{sys.path[:3]}")
        assert sys.path == before, sys.path[:3]
    finally:
        sys.path[:] = before


def test_denied_lock_read_is_error_and_not_free(ai_repo, cp, monkeypatch):
    """F1: `Path.exists()` answered "absent" for a lock the OS refused to stat,
    so a live, unreadable lock became {} with no error.

    The three states are asserted in order, all positively: absent is still
    absent (so the fix cannot collapse everything into "error"), a readable
    record is still HELD, and a DENIED read of that same record is "error", not
    "free".

    B6/4: denying `read_bytes` alone pinned the NEW boundary, not the bug's
    route — re-inserting `if not path.exists(): return {}, None` above the
    `try` kept this green, because on a real host the file does exist and only
    `exists()` was lying. So the denial is now applied to the probe as well as
    the read: the record exists, every way of looking at it fails, and the
    answer must still be "error". Under that fixture the guard order is what
    decides the outcome — with an `exists()` short-circuit back in
    `read_json_or_error` the call returns {} with NO error and this test goes
    red, which is the mutation this fixture exists to catch.

    `Path.exists` is patched rather than the underlying `stat` because
    pathlib's own `exists()` no longer routes through `Path.stat` on this
    host's interpreter (3.14 calls `os.stat` directly, and EACCES is not in
    its ignore list, so it re-raises instead of lying). The lie is the thing
    under test, so it is pinned at the predicate, the same way the denied read
    is pinned at the read.
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")

    absent = mod.lock_state()
    assert (absent.state, absent.detail) == ("free", "no lock file"), absent

    lock = write_lock(ai_repo, live())
    assert mod.lock_state().state == "held", mod.lock_state()

    real_exists = Path.exists

    def deny(self):
        raise PermissionError(13, "Permission denied", str(self))

    def lies(self):
        return False if self == lock else real_exists(self)

    monkeypatch.setattr(Path, "read_bytes", deny)
    monkeypatch.setattr(Path, "exists", lies)
    # The probe lying and the read failing must BOTH be true: the historical
    # shape is a file that is really there.
    assert lies(lock) is False and real_exists(lock) is True
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


def test_handoff_names_another_holders_lock_and_proceeds(ai_repo, cp):
    """Advisory, not enforced: a live hold by somebody else is warned by name and
    the command still runs, because nothing here may require a server.

    B6/5: the loop this came from asserted the marker "state files", which occurs
    in BOTH of --validate's terminal lines, and never asserted `res.rc`, so the
    validate half proved nothing beyond the WARN. The two commands are separate
    tests now, each naming the one line it means.
    """
    write_lock(ai_repo, live(agent="codex"))
    res = run_python(cp, ["--handoff", "--agent", "claude-code"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert "WARN handoff:" in res.stdout, res.stdout
    assert "codex" in res.stdout, res.stdout
    assert "Handoff prepared" in res.stdout, res.stdout
    status = json.loads((ai_repo / ".ai" / "runtime" / "STATUS.json")
                        .read_text("utf-8-sig"))
    assert status["status"] == "handed-off", status


def test_validate_reports_its_own_documented_verdict(ai_repo, cp):
    """B6/5 + B6/3: the terminal line and the exit code are the contract.

    `--validate` writes nothing, so the only thing it owns is its verdict: rc 0
    with "All state files present and non-empty.", rc 1 with "Some files are
    missing or empty." (`checkpoint.py:10`, `SKILL.md:85`). Both branches are
    asserted with their code here, because a test that only matched the
    substring "state files" could not tell the two apart.
    """
    write_lock(ai_repo, live(agent="codex"))
    res = run_python(cp, ["--validate"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    terminal = [ln for ln in res.lines if not ln.startswith("  ")]
    assert terminal == ["All state files present and non-empty."], res.lines
    assert "WARN validate" not in res.stdout, res.stdout

    (ai_repo / ".ai" / "state" / "BLOCKERS.md").unlink()
    dropped = run_python(cp, ["--validate"], cwd=ai_repo)
    assert dropped.rc == 1, dropped.stdout
    assert "Some files are missing or empty." in dropped.stdout, dropped.stdout
    assert "MISSING: " in dropped.stdout, dropped.stdout


def test_validate_is_not_gated_by_an_unreadable_lock(ai_repo, cp):
    """B6/3: `--validate` writes nothing, so it must not inherit a writer's rc 1.

    Its documented exit code means "state files missing or empty"; after the F3
    gate it ALSO meant "the lock was unreadable and nothing was checked", which
    overloads the code and reports a verdict the command never reached.
    """
    write_lock(ai_repo, CONFLICT)
    res = run_python(cp, ["--validate"], cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert "All state files present and non-empty." in res.stdout, res.stdout
    assert "REFUSED" not in res.stdout, res.stdout
    assert "WARN" not in res.stdout, res.stdout


def test_a_state_write_demands_the_same_flags_as_a_lock(ai_repo, cp):
    """B6/2: `--force` alone let a state writer through while `--lock` needed
    `--force --discard-lock`.

    An honest agent that obeyed the printed hint therefore cleared the wall and
    left the TRACKED, still-conflicted record sitting in the tree, which the
    close-out `git add -A` commits. The asymmetry, not `--force`, is the defect:
    the two paths now demand the same pair, and the refusal says out loud what
    `--force` does not do.
    """
    write_lock(ai_repo, CONFLICT)
    status = ai_repo / ".ai" / "runtime" / "STATUS.json"

    forced = run_python(cp, ["--agent", "claude-code", "--force"], cwd=ai_repo)
    assert forced.rc == 1, forced.stdout
    assert "CHECKPOINT REFUSED" in forced.stdout, forced.stdout
    assert "--discard-lock" in forced.stdout, forced.stdout
    assert "does not resolve" in forced.stdout.lower(), forced.stdout
    assert not status.exists(), "plain --force wrote state over a HELD record"

    pair = run_python(cp, ["--agent", "claude-code", "--force", "--discard-lock"],
                      cwd=ai_repo)
    assert pair.rc == 0, pair.stdout
    assert "WARN checkpoint:" in pair.stdout, pair.stdout
    assert "git history" in pair.stdout, pair.stdout
    assert json.loads(status.read_text("utf-8-sig"))["status"] == "active", pair.stdout
    # The pair buys the WRITE, not a resolution: the conflicted record is still
    # there for --lock --force --discard-lock (or a git resolve) to replace.
    assert CONFLICT.strip() in (ai_repo / ".ai" / "runtime" / "WRITER_LOCK.json"
                                ).read_text("utf-8-sig"), pair.stdout


def test_owner_sees_no_warning(ai_repo, cp):
    """The guard must not nag the holder."""
    write_lock(ai_repo, live(agent="claude-code"))
    mine = run_python(cp, ["--agent", "claude-code"], cwd=ai_repo)
    assert mine.rc == 0, mine.stdout
    assert "WARN" not in mine.stdout.split("Checkpoint #")[0], mine.stdout
    assert "Checkpoint #" in mine.stdout, mine.stdout


# ---------------------------------------------------------------------------
# B6/1: the F1 lesson stopped at the lock. Every other probe in this file could
# still answer "no file" for "no answer", and the state writers persisted that.


class _Args:
    """The namespace the in-process commands read, without argparse."""
    agent = None
    task = None
    ttl = 100
    reason = None
    force = False
    discard_lock = False


def _denying(monkeypatch, target, name="read_bytes"):
    """Make `target` deny one Path method, leaving every other path alone."""
    real = getattr(Path, name)

    def probe(self, *a, **kw):
        if self == target:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, name, probe)
    return probe


def test_denied_protocol_version_is_warned_and_not_persisted(ai_repo, cp,
                                                            monkeypatch,
                                                            capsys):
    """B6/1: `get_protocol_version()` answered "unknown" for a VERSION it could
    not read, and `cmd_checkpoint` wrote that lie into STATUS.json with no
    named degradation.

    Denied first, so the omission is observable: a version that could not be
    read is not written at all, and the WARN names it. Then the same command
    with the denial lifted shows what the fix did not take away — a readable
    VERSION still lands in the state file.
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")
    version_file = ai_repo / ".ai" / "protocol" / "VERSION"
    status = ai_repo / ".ai" / "runtime" / "STATUS.json"
    expected = version_file.read_text(encoding="utf-8").strip()
    assert expected and expected != "unknown", expected

    _denying(monkeypatch, version_file)
    version, err = mod.get_protocol_version()
    assert err and "cannot read" in err, (version, err)
    assert version is None, version

    mod.cmd_checkpoint(_Args())
    out = capsys.readouterr().out
    assert "WARN: protocol version not read" in out, out
    written = json.loads(status.read_text("utf-8-sig"))
    assert "protocol_version" not in written, written
    assert "unknown" not in status.read_text("utf-8-sig"), written

    monkeypatch.undo()
    mod.cmd_checkpoint(_Args())
    capsys.readouterr()
    written = json.loads(status.read_text("utf-8-sig"))
    assert written["protocol_version"] == expected, written
    assert written["checkpoint_count"] == 2, written


def test_unreadable_status_file_is_not_restarted_from_zero(ai_repo, cp,
                                                           monkeypatch, capsys):
    """B6/1: `read_json(STATUS.json)` threw the F1 error away, so a denied read
    read as an empty session and the write restarted `checkpoint_count` at 1.

    A count that could not be read is not reset — the write is refused with a
    named error and the file is left exactly as it was.
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")
    status = ai_repo / ".ai" / "runtime" / "STATUS.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    before = {"checkpoint_count": 7, "current_task": "DO-NOT-RESET",
              "status": "active", "protocol_version": "2.1"}
    status.write_text(json.dumps(before), encoding="utf-8")

    _denying(monkeypatch, status)
    args = _Args()
    args.agent = "claude-code"
    with pytest.raises(SystemExit) as exc:
        mod.cmd_checkpoint(args)
    assert exc.value.code, "cmd_checkpoint exited 0 over an unreadable STATUS.json"
    out = capsys.readouterr().out
    assert "CHECKPOINT ABORTED" in out, out
    assert "STATUS.json" in out and "cannot read" in out, out
    assert json.loads(status.read_text("utf-8-sig")) == before, out

    # Positive partner: a genuinely absent STATUS.json IS a new session, and
    # the refusal above must not turn that into an error too.
    monkeypatch.undo()
    status.unlink()
    capsys.readouterr()
    mod.cmd_checkpoint(args)
    fresh = json.loads(status.read_text("utf-8-sig"))
    assert fresh["checkpoint_count"] == 1, fresh
    assert "Checkpoint #1" in capsys.readouterr().out


def test_handoff_aborts_instead_of_rewriting_an_unknown_status(ai_repo, cp,
                                                               monkeypatch,
                                                               capsys):
    """B6/1: the same discarded error sat in front of `cmd_handoff`'s write.

    It does not bump the counter, so the symptom is quieter and worse: the
    rewrite drops every other key the file held and prints "Handoff prepared".
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")
    status = ai_repo / ".ai" / "runtime" / "STATUS.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    before = {"checkpoint_count": 4, "current_task": "KEEP", "status": "active"}
    status.write_text(json.dumps(before), encoding="utf-8")

    _denying(monkeypatch, status)
    with pytest.raises(SystemExit) as exc:
        mod.cmd_handoff(_Args())
    assert exc.value.code
    out = capsys.readouterr().out
    assert "HANDOFF ABORTED" in out, out
    assert "cannot read" in out, out
    assert json.loads(status.read_text("utf-8-sig")) == before, out


def test_denied_stat_is_named_not_reported_missing(ai_repo, cp, monkeypatch,
                                                   capsys):
    """B6/1: `--status` and `--validate` probed with exists()/stat(), so a file
    that exists but cannot be stat'd printed MISSING — the "looks fine"
    inversion, in the read-only direction.
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")
    target = ai_repo / ".ai" / "state" / "CURRENT.md"
    assert target.exists()

    _denying(monkeypatch, target, "stat")
    real_exists = Path.exists

    def lies(self):
        return False if self == target else real_exists(self)

    monkeypatch.setattr(Path, "exists", lies)

    mod.cmd_status(None)
    out = capsys.readouterr().out
    assert "[ERR ] CURRENT.md" in out, out
    assert "[MISS] CURRENT.md" not in out, out
    assert "[OK ] TASK.md" in out, out
    assert "cannot stat" in out, out

    with pytest.raises(SystemExit) as exc:
        mod.cmd_validate(None)
    out = capsys.readouterr().out
    assert "UNREADABLE: " in out, out
    assert "MISSING: " not in out, out
    assert "OK:      " in out, out
    assert exc.value.code == 2, (exc.value.code, out)
    assert "not confirmed" in out.lower(), out


def test_unlock_refuses_to_write_over_a_record_that_changed(ai_repo, cp,
                                                            monkeypatch, capsys):
    """B6/8: F2 closed the PARSE-ERROR half of the read→write window, not the
    window — `os.replace` at the end of `cmd_unlock` could still destroy an
    uncommitted conflict that lands after the record was validated.

    A merge that parses is the harder case: nothing is wrong with the bytes the
    command holds, they are simply no longer the bytes on disk. So the write
    compares the raw bytes it last read against the file and refuses on
    mismatch — bounded, no extra lock file, and no hard enforcement added.

    The patch is a read counter because the race is a read ordering: the third
    look at the record is the one the write is about to trust.
    """
    mod = load(cp)
    mod._set_paths(ai_repo / ".ai")
    lock = write_lock(ai_repo, live(agent="codex"))
    real_read = Path.read_bytes
    # The merge has to LAND, not merely be returned: the assertion below reads
    # the real file to check the command left it alone, and a record naming a
    # different agent would make the positive partner refuse on the holder check
    # instead of exercising the write.
    landed = live(agent="codex", reason="renewed by another machine").encode()
    reads = []

    def merge_lands(self):
        if self != lock:
            return real_read(self)
        reads.append(self.name)
        if len(reads) > 2:
            lock.write_bytes(landed)
            return landed
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", merge_lands)

    args = _Args()
    args.agent = "codex"
    with pytest.raises(SystemExit) as exc:
        mod.cmd_unlock(args)
    assert exc.value.code, "unlock exited 0 over a record it no longer held"
    out = capsys.readouterr().out
    assert "UNLOCK ABORTED" in out, out
    assert "changed" in out, out
    assert real_read(lock) == landed, (
        "the command replaced the record that landed mid-command: "
        f"{real_read(lock)!r}")

    # Positive partner: with no mid-command merge the same code path writes the
    # release, so the staleness check is not a wall.
    monkeypatch.undo()
    capsys.readouterr()
    mod.cmd_unlock(args)
    released = json.loads(real_read(lock).decode("utf-8-sig"))
    assert released["agent"] == "codex", released
    assert released["released_by"] == "codex" and released["released_at"], released
    assert "released" in capsys.readouterr().out
