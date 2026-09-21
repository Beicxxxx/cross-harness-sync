#!/usr/bin/env python3
"""
Cross-harness continuity checkpoint tool (cross-harness-sync skill).

Usage:
    python .ai/scripts/checkpoint.py                    # Update runtime status
    python .ai/scripts/checkpoint.py --status           # Show current status
    python .ai/scripts/checkpoint.py --prime            # Session-start injection
    python .ai/scripts/checkpoint.py --handoff          # Archive handoff, mark handed-off
    python .ai/scripts/checkpoint.py --validate         # Required files exist & non-empty
    python .ai/scripts/checkpoint.py --lock --agent X # Acquire advisory writer lock
    python .ai/scripts/checkpoint.py --unlock --agent X# Release the writer lock
    python .ai/scripts/checkpoint.py --lock --agent X --force --reason "<why>"
                                        # take a live hold OVER: --force on --lock
                                        # always names a --reason, because the
                                        # reason is the only thing that tells the
                                        # next machine this was a takeover and not
                                        # an accident
    python .ai/scripts/checkpoint.py --lock --agent X --force --discard-lock
                                        --reason "<why>"
                                        # abandon an UNREADABLE lock record: the
                                        # only override for a merged/corrupt one.
                                        # --force takes over, it never resolves:
                                        # the conflicted record stays in the tree
                                        # until this replaces it or git resolves it
    python .ai/scripts/checkpoint.py --lock --agent X --force --reason "<why>"
                                        # the only override for a linked git
                                        # worktree, a symlinked install or an
                                        # undetermined layout (D15); the layout
                                        # is recorded with the reason
    python .ai/scripts/checkpoint.py --handoff --agent X --force
    python .ai/scripts/checkpoint.py --force
                                        # the same D15 layout refusal guards the
                                        # two state-writing commands (--handoff
                                        # and the bare checkpoint), because a
                                        # per-worktree lock coordinates nobody;
                                        # --force overrides with a WARN and,
                                        # there being no lock record to write,
                                        # records nothing about the split

This script handles the MECHANICAL parts of checkpointing:
- runtime/STATUS.json timestamps and counters
- advisory writer lock with TTL (runtime/WRITER_LOCK.json, audit-preserving)
- handoff archiving
- the --prime session-start read list (overridable via .ai/PRIME.md)

It does NOT generate semantic content (CURRENT.md updates, handoff summaries).
That is the coding agent's job.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

# Shared primitives, installed next to this file by init_sync.py. There is
# deliberately no inline fallback: a second copy of that plumbing would be a
# second copy of the wrong-root path this removes (see scripts/ai_common.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from ai_common import (DEFAULT_REQUIRED_FILES, REQUIRED_FILE_FLOOR,
                           RepoError, checkout_layout, protect_stdio,
                           resolve_roots, with_required_file_floor,
                           worktree_listing)
except ImportError:
    print("[FAIL] install layout: ai_common.py is missing from .ai/scripts/ -- "
          "re-run init_sync.py so the shared primitives are copied in")
    sys.exit(2)

# Every path below belongs to main(): resolve_roots() finds `.ai`, _set_paths()
# derives the rest. They are None until then, and each command checks.
AI_DIR: Path | None = None
ROOT: Path | None = None
STATE_DIR: Path | None = None
HANDOFF_DIR: Path | None = None
ARCHIVE_DIR: Path | None = None
RUNTIME_DIR: Path | None = None
PROTOCOL_DIR: Path | None = None
LOCK_PATH: Path | None = None

DEFAULT_TTL_SECONDS = 4 * 3600
# How long a concurrent checkpoint on this machine may keep this one waiting:
# 8 tries doubling from 10ms is ~0.7s, then the error is real and propagates.
RETRY_ON_SHARING = 8


def _set_paths(ai_dir: Path) -> None:
    """Derive every module-level path from a resolved `.ai` directory."""
    global AI_DIR, ROOT, STATE_DIR, HANDOFF_DIR, ARCHIVE_DIR, RUNTIME_DIR, \
        PROTOCOL_DIR, LOCK_PATH
    AI_DIR = ai_dir
    ROOT = ai_dir.parent
    STATE_DIR = ai_dir / "state"
    HANDOFF_DIR = ai_dir / "handoff"
    ARCHIVE_DIR = HANDOFF_DIR / "archive"
    RUNTIME_DIR = ai_dir / "runtime"
    PROTOCOL_DIR = ai_dir / "protocol"
    LOCK_PATH = RUNTIME_DIR / "WRITER_LOCK.json"


def _require_paths() -> None:
    """Refuse to run a command whose install paths were never wired.

    Silent failure was the D19 shape of this bug: paths pointing one directory
    too high still read, wrote and reported — they just reported the wrong tree.
    A command invoked without main() must raise instead.
    """
    if AI_DIR is None:
        raise RuntimeError(
            "install paths not initialised: main() runs resolve_roots() and "
            "_set_paths() before any command; call it instead of cmd_* directly")


def now_dt():
    return datetime.now().astimezone()


def now_iso():
    return now_dt().isoformat(timespec="seconds")


def now_display():
    """A timestamp that is safe to put in a state file: ASCII plus an offset.

    `reference.md`'s "Language and timestamps" asks for an explicit UTC offset,
    and the zone name is the part that cannot be trusted: `datetime.tzname()` is
    the OS's *localized* label, so on a zh host it returned
    `澳大利亚东部标准时间` — non-ASCII bytes that `protect_stdio()` then pushes
    out as forced UTF-8 into a console that is not UTF-8 (finding V-6, the exact
    class the wave's ASCII pass just closed). The offset is therefore computed
    from the host's own `utcoffset()` answer rather than read off a name, and a
    name is printed only when it is ASCII to begin with.
    """
    local = now_dt()
    delta = local.utcoffset() or timedelta(0)
    seconds = int(delta.total_seconds())
    sign = "-" if seconds < 0 else "+"
    seconds = abs(seconds)
    offset = f"UTC{sign}{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"
    zone = local.tzname() or ""
    label = f"{zone}, {offset}" if zone.isascii() else offset
    return f"{local:%Y-%m-%d %H:%M:%S} ({label})"


def _retry_sharing(fn):
    """Run `fn`, retrying the transient sharing violations Windows raises while
    another process is mid-replace on the same path (Errno 13 / WinError 5).

    Both halves of an atomic write need it: retrying only the writer leaves the
    paired read dying under a concurrent checkpoint (D9).
    """
    delay = 0.01
    for left in range(RETRY_ON_SHARING, 0, -1):
        try:
            return fn()
        except PermissionError:
            if left == 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.2)


def _read_raw_or_error(path):
    """The bytes behind one read, as (raw, err): the F1 boundary on its own.

    FileNotFoundError is the ONLY answer that means "absent". Every other
    OSError — the Errno 13 this host raises routinely — is named, never folded
    into "no file". Kept separate from the parsing so a caller that is about to
    write can re-compare bytes without re-decoding them (B6/8).
    """
    try:
        raw = _retry_sharing(path.read_bytes)
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"cannot read: {exc}"
    return raw, None


def read_json_for_update(path):
    """(data, err, raw): the parsed object AND the exact bytes it came from.

    A caller that will write the record back needs `raw` so it can refuse when
    the file changed underneath it. `raw` is None only for a genuinely absent
    file, which is what makes "create it" and "replace what arrived mid-command"
    distinguishable at write time.
    """
    raw, err = _read_raw_or_error(path)
    if err:
        return {}, err, None
    if raw is None:
        return {}, None, None
    if b"<<<<<<<" in raw or b">>>>>>>" in raw:
        return {}, "merge conflict markers", raw
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {}, f"cannot parse: {exc}", raw
    if not isinstance(data, dict):
        return {}, "cannot parse: expected a JSON object", raw
    return data, None, raw


def read_json_or_error(path):
    """Read a JSON object, reporting WHY it could not be read.

    D1: for the writer lock an empty dict is not "no lock", it is "unknown", so
    the caller must be able to tell the two apart. A tracked file plus a merge
    is a guaranteed conflict marker in the record.

    F1: "absent" and "cannot stat / cannot read" are different answers, and the
    old `path.exists()` guard confused them — exists() returns False when the
    stat behind it raises PermissionError, which this host does routinely
    (Errno 13). A live, conflicted lock therefore came back as {} with NO error,
    which lock_state() reported as free and both machines wrote. The file is now
    opened directly and only a genuine FileNotFoundError means absent; anything
    else the OS refuses becomes an error, the same way an unparseable record
    already does.

    B6/1: this is the single error-aware read every state file now goes
    through — the lock, runtime/STATUS.json and protocol/VERSION alike.
    """
    data, err, _raw = read_json_for_update(path)
    return data, err


def _probe(path):
    """One stat, three honest answers: (size,) | None | ("unreadable", err).

    B6/1: `path.exists()` answers False when the stat behind it is refused, so
    `--status` and `--validate` printed MISSING for a file that was there. The
    probe opens with stat() and names a refusal instead of guessing absence.
    """
    try:
        stat_result = _retry_sharing(path.stat)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return "unreadable", f"cannot stat: {exc}"
    return ("ok", stat_result.st_size)


def read_json(path):
    """Best-effort read for the untracked runtime files: {} means "no data".

    Lock consumers must NOT use this — they need the error, which is the whole
    of D1. See read_json_or_error. State WRITERS must not use it either: a
    discarded error is how checkpoint_count restarted from 0 (B6/1).
    """
    data, _err = read_json_or_error(path)
    return data


def _write_json_if_unchanged(path, data, raw, label):
    """Compare-and-write (B6/8): refuse to replace bytes this command never read.

    `raw` is what `read_json_for_update` validated. A file that cannot be read at
    write time counts as changed — overwriting an answer we cannot see is the same
    lie. Bounded and advisory: no extra lock file, no enforcement, and the window
    narrows to the instant between the probe and os.replace.

    This is for the lock's read-modify-write cycle ONLY. runtime/STATUS.json is an
    untracked last-writer-wins runtime file and two local checkpoints racing it is
    the expected case RETRY_ON_SHARING exists for; making that race abort was tried
    in this round and tests/test_write_atomicity.py's concurrent-checkpoint pin
    (every rc 0) says so. Finding 1's ruling there is about the READ, not the write.
    """
    current, err = _read_raw_or_error(path)
    if err or current != raw:
        print(f"{label} ABORTED: {path.name} "
              f"{err or 'changed since it was read'} - the file on disk is not "
              "the one this command validated, so nothing was written.")
        return False
    write_json(path, data)
    return True


def _atomic_write(path, payload):
    """tempfile in the target's own directory -> fsync -> os.replace (D8, D9).

    Plain `os.rename` raises on Windows when the target exists, so the
    convenience wrapper around it degrades to copy+unlink — neither atomic nor
    safe for a tracked file. `os.replace` is the atomic form on both platforms,
    and a unique temp name keeps two local writers from clobbering each other's
    partial file. `payload(handle)` writes the bytes; nothing is left behind if
    it raises.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            payload(handle)
            handle.flush()
            os.fsync(handle.fileno())
        _retry_sharing(lambda: os.replace(tmp, str(path)))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path, data):
    def payload(handle):
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    _atomic_write(path, payload)


def write_text_atomic(path, text):
    """The same discipline for the non-JSON runtime files: a reader must never
    see ACTIVE_AGENT half-written."""
    _atomic_write(path, lambda handle: handle.write(text))


def get_protocol_version():
    """The protocol VERSION, as (value, err) — never "unknown" for "no answer".

    B6/1: the old `version_file.exists() / read_text() / else "unknown"` route
    could not tell "there is no VERSION" from "the OS refused to read it", and
    `cmd_checkpoint` then PERSISTED the "unknown" into runtime/STATUS.json. On
    this host Errno 13 is routine, so a transient denial produced a
    self-consistent-looking state file built on no answer at all, with no named
    degradation. Absent is now the only route to "unknown"; a refusal returns
    (None, "cannot read: …") so the caller can omit the key and say so.
    """
    version_file = PROTOCOL_DIR / "VERSION"
    raw, err = _read_raw_or_error(version_file)
    if err:
        return None, err
    if raw is None:
        return "unknown", None
    try:
        return raw.decode("utf-8").strip(), None
    except UnicodeDecodeError as decode_exc:
        return None, f"cannot read: {decode_exc}"


def parse_ts(raw):
    """Tolerant of Z suffixes (pre-3.11 fromisoformat is not) and naive stamps.

    Returns an aware datetime or None; None means "no usable expiry", which the
    state machine reports rather than treats as never-expiring (D10).
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        # D10: a naive stamp is local time, not UTC midnight and not a crash —
        # comparing it against now_dt() used to raise TypeError.
        stamp = stamp.astimezone()
    return stamp


class LockStatus(NamedTuple):
    state: str           # free | held | expired | error
    holder: str | None
    detail: str


def lock_state():
    """The lock parser, whose error state is HELD and never free.

    Replaces the old (lock, holder, expired) triple, which could not express
    "unreadable" and therefore expressed it as "no lock" (D1).
    """
    lock, err = read_json_or_error(LOCK_PATH)
    if err:
        return LockStatus("error", None, err)
    if not lock:
        return LockStatus("free", None, "no lock file")
    if lock.get("released_at"):
        return LockStatus("free", None, f"released {lock['released_at']}")
    holder = lock.get("agent") or "?"
    expires = parse_ts(lock.get("expires_at"))
    if expires is None:
        return LockStatus("held", holder,
                          "no expiry (malformed or absent expires_at) - do not "
                          "rely on the TTL; release with --unlock --force")
    if now_dt() > expires:
        return LockStatus("expired", holder, f"expired {lock['expires_at']}")
    return LockStatus("held", holder, f"until {lock['expires_at']}")


def _report_file(path, name):
    """One `--status` line: OK, MISS, or ERR — never MISS for a file we could not see."""
    probed = _probe(path)
    if probed is None:
        print(f"  [MISS] {name} (missing)")
    elif probed[0] == "unreadable":
        print(f"  [ERR ] {name} ({probed[1]})")
    else:
        print(f"  [OK ] {name} ({probed[1]} bytes)")


def cmd_status(args):
    _require_paths()
    status, status_err = read_json_or_error(RUNTIME_DIR / "STATUS.json")
    if status_err:
        print(f"WARN: session state not read: runtime/STATUS.json "
              f"{status_err} - unknown, not empty.")
    elif not status:
        print("No active session found (runtime/STATUS.json missing or empty)")
    else:
        version = status.get("protocol_version")
        if not version:
            version, version_err = get_protocol_version()
            if version_err:
                print(f"WARN: protocol version not read ({version_err})")
                version = "not read"
        print(f"Protocol Version : {version or 'not read'}")
        print(f"Active Agent     : {status.get('active_agent', '?')}")
        print(f"Last Checkpoint  : {status.get('last_checkpoint', '?')}")
        print(f"Status           : {status.get('status', '?')}")
        print(f"Current Task     : {status.get('current_task', '?')}")
        print(f"Checkpoints      : {status.get('checkpoint_count', 0)}")

    lock_status = lock_state()
    if lock_status.state == "error":
        print(f"Writer Lock      : CONFLICT/ERROR ({lock_status.detail})"
              " - do NOT write state files; resolve the conflict first")
    elif lock_status.state == "held":
        lock, _err = read_json_or_error(LOCK_PATH)
        print(f"Writer Lock      : HELD by {lock_status.holder} "
              f"{lock_status.detail} (reason: {lock.get('reason', '-')})")
    elif lock_status.state == "expired":
        print(f"Writer Lock      : expired (was {lock_status.holder}, "
              f"{lock_status.detail})")
    else:
        print("Writer Lock      : none")

    print("\nState files:")
    for name in ["CURRENT.md", "TASK.md", "DECISIONS.md", "DECISIONS_INDEX.md",
                 "BLOCKERS.md", "ROLE_POLICY.md"]:
        _report_file(STATE_DIR / name, name)

    print("\nHandoff files:")
    for name in ["LATEST.md", "NEXT_PROMPT.md"]:
        _report_file(HANDOFF_DIR / name, name)

    if ARCHIVE_DIR.exists():
        print(f"\n  Archived handoffs: {len(list(ARCHIVE_DIR.glob('*.md')))}")


def cmd_checkpoint(args):
    _require_paths()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    status_path = RUNTIME_DIR / "STATUS.json"
    # B6/1: a count this command could not read is not a count of 0. The old
    # read_json() discarded the F1 error, so one transient denial restarted the
    # sequence and wrote the reset over the real state — a lie, not a
    # degradation. Refuse the write and leave the file alone.
    status, err = read_json_or_error(status_path)
    if err:
        print(f"CHECKPOINT ABORTED: runtime/STATUS.json {err} - the existing "
              "checkpoint count is unknown, so it is not reset to 0 and no state "
              "file is written.")
        sys.exit(2)
    status["last_checkpoint"] = now_iso()
    status["checkpoint_count"] = status.get("checkpoint_count", 0) + 1
    status["status"] = "active"
    if args.agent:
        status["active_agent"] = args.agent
        write_text_atomic(RUNTIME_DIR / "ACTIVE_AGENT", args.agent + "\n")
    if args.task:
        status["current_task"] = args.task
    version, version_err = get_protocol_version()
    if version_err:
        print(f"WARN: protocol version not read ({version_err}) - the key is "
              'omitted from runtime/STATUS.json rather than recorded as "unknown".')
    else:
        status["protocol_version"] = version
    write_json(status_path, status)
    print(f"Checkpoint #{status['checkpoint_count']} at {now_display()}")


def cmd_prime(args):
    """Session-start injection: lock status + exact read list.

    If .ai/PRIME.md exists, print it INSTEAD of the generated default —
    the project owner curates the override, like Beads' .beads/PRIME.md.
    """
    _require_paths()
    override = AI_DIR / "PRIME.md"
    if override.exists():
        print(override.read_text(encoding="utf-8").strip())
        return

    lock_status = lock_state()
    if lock_status.state == "error":
        lock_line = (f"CONFLICT/ERROR - {lock_status.detail} - do NOT write state "
                     "files; resolve the conflict first.")
    elif lock_status.state == "held":
        # `HELD by <h> {detail}` with no separator: with detail "until <ts>" this
        # reproduces the pre-fix line byte for byte, so anything reading --prime
        # output keeps matching. The no-expiry detail reads awkwardly there — it
        # is a warning line, not prose.
        lock_line = (f"HELD by {lock_status.holder} {lock_status.detail} - "
                     "if that is not you, do NOT write state files.")
    elif lock_status.state == "expired":
        lock_line = f"expired (was {lock_status.holder}) - free to acquire."
    else:
        lock_line = "none - free to acquire."

    status, status_err = read_json_or_error(RUNTIME_DIR / "STATUS.json")
    version, version_err = get_protocol_version()
    last = status.get("last_checkpoint", "never")
    agent = status.get("active_agent", "?")
    if status_err:
        last, agent = "not read", "?"

    print(f"== SESSION PRIME (cross-harness-sync v{version or 'not read'}) ==")
    if version_err:
        print(f"WARN: protocol version not read ({version_err}) - the protocol in "
              "use is not confirmed.")
    if status_err:
        print(f"WARN: session state not read: runtime/STATUS.json {status_err} - "
              "the last checkpoint is not confirmed, and 'never' would be a lie.")
    print(f"Writer lock: {lock_line}")
    print(f"Last checkpoint: {last} by {agent}")
    print()
    print("READ NOW (L0, in order, nothing else at startup):")
    print("  1. .ai/state/CURRENT.md")
    print("  2. .ai/state/TASK.md")
    print("  3. .ai/state/BLOCKERS.md")
    print("If continuing prior work, also read: .ai/handoff/LATEST.md")
    print()
    print("Do NOT read in full: DECISIONS.md, handoff/archive/, state/archive/.")
    print("Retrieve single entries via .ai/state/DECISIONS_INDEX.md or grep.")
    print()
    print("Before writing any state file:")
    print("  python .ai/scripts/checkpoint.py --lock --agent <your-harness-name>")
    print("At close-out: python .ai/scripts/sync_verify.py must print no FAILED")
    print("line - a named [SKIP] is expected on a default install, silence is")
    print("not. Then --unlock --agent <your-name>, commit, and push.")


def cmd_handoff(args):
    _require_paths()
    status_path = RUNTIME_DIR / "STATUS.json"
    # B6/1: the same discarded error sat in front of this write, and its symptom
    # is quieter and worse than the checkpoint one — the rewrite drops every
    # other key the file held and still prints "Handoff prepared". Read first and
    # abort before archiving, so a refusal leaves no trace at all.
    status, err = read_json_or_error(status_path)
    if err:
        print(f"HANDOFF ABORTED: runtime/STATUS.json {err} - the state on disk is "
              "unknown, so it is not rewritten and no handoff is prepared.")
        sys.exit(2)

    latest = HANDOFF_DIR / "LATEST.md"
    if latest.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        agent = args.agent or "unknown"
        archive_name = f"{timestamp}-{agent}-HANDOFF.md"
        shutil.copy2(str(latest), str(ARCHIVE_DIR / archive_name))
        print(f"Archived previous handoff -> {archive_name}")

    status["status"] = "handed-off"
    status["last_checkpoint"] = now_iso()
    if args.agent:
        status["active_agent"] = args.agent
    write_json(status_path, status)

    print(f"Handoff prepared at {now_display()}")
    print()
    print("The coding agent must still update these files manually:")
    print(f"  1. {STATE_DIR / 'CURRENT.md'} - final state snapshot (<= budget lines)")
    print(f"  2. {HANDOFF_DIR / 'LATEST.md'} - 6 sections: Done / Not done /")
    print("     Evidence pointers / Warnings / Next step / Must-read list")
    print(f"  3. {HANDOFF_DIR / 'NEXT_PROMPT.md'} - next agent's starting prompt")
    print()
    print("Then run sync_verify.py, release the lock "
          "(--unlock --agent <name>), commit, and push.")


def _declared_required_files():
    """`(declared, notes, unusable)` — the list THIS project declared, not the
    shipped default.

    Lane V's residual, and the same defect class as D23: V-1 replaced this
    command's private seven-path list with `ai_common.DEFAULT_REQUIRED_FILES`,
    which fixed the reviewer's measurement, but it left `--validate` reading a
    CONSTANT while `sync_verify.py` reads `config["required_files"]` with
    `REQUIRED_FILE_FLOOR` unioned back in after the key's REPLACE policy. So one
    legal config line — a repo that keeps no decision log, or one that adds an
    authorization record — made the two enforcement commands answer different
    questions again, the residual being quieter than the original because it
    needs an override to exist.

    Only the one key is read: `required_files` merges by REPLACE, so no other
    default participates in its value, and the floor union is shared through
    `ai_common.with_required_file_floor` rather than re-derived here. Shape is
    checked before use — a `required_files` holding a STRING would otherwise be
    iterated character by character (lane S2 finding 4's shape, one command
    deeper) — and `notes` carries whatever the read had to say about itself.
    """
    path = AI_DIR / "sync_config.json"
    if not path.is_file():
        return list(DEFAULT_REQUIRED_FILES), [
            f"  CONFIG:  {path.relative_to(AI_DIR)} is not installed, so the "
            "built-in default required-file list was used (sync_verify.py "
            "reports the same fact as `[FAIL] config readable` and stops)"], None
    try:
        cfg = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, [f"  CONFIG:  {path.relative_to(AI_DIR)}: "
                      f"{type(exc).__name__}: {exc}"], "the config cannot be read"
    if not isinstance(cfg, dict):
        return None, [f"  CONFIG:  {path.relative_to(AI_DIR)} holds "
                      f"{type(cfg).__name__}, not a JSON object"], \
            "the config is not an object"
    if "required_files" not in cfg:
        return list(DEFAULT_REQUIRED_FILES), [
            "  CONFIG:  no `required_files` key in .ai/sync_config.json, so the "
            "built-in default list was used (the same list sync_verify.py "
            "merges over its own defaults)"], None
    declared = cfg["required_files"]
    if not isinstance(declared, list) or not all(
            isinstance(item, str) and item.strip() for item in declared):
        return None, [f"  CONFIG:  `required_files` must be a list of path "
                      f"strings, got {type(declared).__name__}"], \
            "`required_files` is not a list of paths"
    return list(declared), None, None


def cmd_validate(args):
    _require_paths()
    # Finding V-1, then lane V's residual on top of it. V-1 made this command
    # import the shared list instead of restating one; this makes it import the
    # shared CONFIG KEY, which is the thing a project is allowed to change. The
    # floor union and the emptiness law are applied to the derived list rather
    # than to a constant, so "this command checked nothing" cannot survive by
    # pointing at a default nobody configured.
    declared, notes, unusable = _declared_required_files()
    for line in notes or []:
        print(line)
    if unusable:
        print("\nValidation not confirmed: the required-file list could not be "
              f"read ({unusable}), so no verdict was reached about a list this "
              "command did not have. rc 2 means 'no verdict'; rc 1 still means "
              "'files missing or empty'.")
        sys.exit(2)
    to_walk, _floor_only = with_required_file_floor(declared)
    required_files = []
    for rel in to_walk:
        parts = [p for p in str(rel).split("/") if p and p != "."]
        if parts and parts[0] == AI_DIR.name:
            parts = parts[1:]
        required_files.append(AI_DIR.joinpath(*parts) if parts else AI_DIR)
    if not required_files:
        # Empty is not "nothing wrong": it is "this command checked nothing", and
        # the verdict it prints would be unearned (same law as the verifier's
        # `required-file floor`, which refuses a declared list of zero).
        print("Validation refused: no required-file list could be derived, so "
              "this command would certify a tree it never looked at.")
        sys.exit(2)
    all_ok = True
    unreadable = []
    for path in required_files:
        rel = path.relative_to(AI_DIR)
        probed = _probe(path)
        if probed is None:
            print(f"  MISSING: {rel}")
            all_ok = False
        elif probed[0] == "unreadable":
            # B6/1: exists() answered False for a refused stat, so a file that
            # was present printed MISSING — "looks fine" inverted into the
            # read-only direction. A file we cannot see is neither present nor
            # absent, so it gets its own line and its own exit code.
            print(f"  UNREADABLE: {rel} ({probed[1]})")
            unreadable.append(str(rel))
        else:
            size = probed[1]
            if size == 0:
                print(f"  EMPTY:   {rel}")
                all_ok = False
            else:
                print(f"  OK:      {rel} ({size} bytes)")
    if unreadable:
        print(f"\nValidation not confirmed: {len(unreadable)} required file(s) "
              "could not be read, so their presence was neither confirmed nor "
              "denied. rc 2 means 'no verdict'; rc 1 still means 'files missing "
              "or empty'.")
        sys.exit(2)
    if not declared:
        # The emptiness law at the code the verifier uses for it: a config that
        # declares zero required files gets a FAIL line there
        # (`required-file list`), so an empty declaration may not be certified as
        # a complete tree here either. The floor entries were still walked, so the
        # evidence is on screen; only the verdict changes.
        print("  LIST:    config declares zero required_files; the floor entries "
              "were walked anyway, and a narrowed list is a recorded act, not a "
              "clean answer")
        all_ok = False
    print("\nAll state files present and non-empty." if all_ok
          else "\nSome files are missing or empty.")
    sys.exit(0 if all_ok else 1)


def install_layout():
    """This checkout's `(kind, detail)`, read from the two directions that lie.

    `checkout_layout(ROOT)` covers a linked worktree and a symlink inside the
    install. It cannot see the one case this process created itself:
    `resolve_roots()` calls `Path.resolve()`, which follows symlinks, so an
    invoked `.ai` that IS a symlink leaves ROOT pointing at the target's parent
    — a different tree that then looks perfectly ordinary from the inside. The
    unresolved invocation path is the only witness, so it is compared here.
    """
    # invocation_layout lives in ai_common so the verifier's install-layout check
    # can call the same pair instead of a link-blind one (finding B7a-6), and it
    # is imported here rather than in the module header on purpose: the header's
    # try/except names a missing primitive that EVERY command needs, and this one
    # has a single call path. What it adds is the unresolved invocation path as a
    # witness, trusted only in the shape it claims (finding B7a-4): reading
    # parent.parent of a scripts directory as "not a link, therefore normal" was
    # the fail-open this replaces.
    from ai_common import invocation_layout
    return invocation_layout(ROOT, __file__)


def _layout_refusal(kind, detail, command="lock"):
    """What a refused layout prints: the name, the why, the way out.

    `command` names the flag the operator actually typed. R4 finding 4
    (MINOR): `cmd_unlock` reused this helper verbatim, so an agent told to
    release a pen was told to re-run `--lock --force` -- to acquire a lock in
    order to release one. The remedy is the same override on the SAME command,
    and `--reason` belongs to `--lock` alone: it is the only one that records a
    reason in WRITER_LOCK.json (see `cmd_lock`'s `force_reason`).
    """
    if kind == "linked-worktree":
        head = (f"REFUSED: this checkout is a linked git worktree ({detail}).\n"
                "WRITER_LOCK.json lives on disk per worktree, so locking here "
                "does not stop another worktree from writing.")
        where = "Work in the main checkout, or"
    elif kind == "symlinked":
        head = (f"REFUSED: part of this install is relocated by a link (a "
                f"symlink or, on Windows, a junction) ({detail}).\n"
                "The state and the lock behind that link are not files this "
                "checkout versions, so they do not travel by git pull and are "
                "not the ones another harness reads.")
        where = "Work on the real checkout, or"
    elif kind == "not-repository-root":
        head = (f"REFUSED: this install is not at the root of the repository it "
                f"is inside ({detail}).\n"
                "The tracked lock written here travels by git pull of the OUTER "
                "repository, which is not the history of this install: one "
                "install root per checkout, at its top level.")
        where = "Move the install to the repository root, or"
    else:
        head = (f"REFUSED: the checkout layout could not be determined "
                f"({kind}: {detail}).\n"
                "An install that cannot say where it is may not claim a "
                "single-writer lock: not-determined is an error state, not a "
                "clean one.")
        where = "Fix the repository location (or run inside the project's git " \
                "work tree), or"
    print(head)
    other, err = worktree_listing(ROOT)
    if err:
        print(f"  other worktrees: not enumerated ({err})")
    elif len(other) > 1:
        print("  worktrees of this repository: "
              + ", ".join(p for p in other))
    reason = ' --reason "<why>"' if command == "lock" else ""
    visible = ("the takeover is visible in git." if command == "lock"
               else "the release is visible in git.")
    print(f"{where} run\n"
          f"  python .ai/scripts/checkpoint.py --{command} --agent <name> "
          f"--force{reason}\nonly after recording the split in the handoff: "
          "the lock stays advisory, and the\noverride is written into "
          f"WRITER_LOCK.json so {visible}")


def _next_epoch(prev, err):
    """(epoch, reason): one past the displaced record's epoch, or None plus why.

    `epoch` is wave 1b's schema; starting to write it now is additive. None is
    what a record that could not be read leaves behind — the key is omitted and
    the gap named, rather than a first epoch asserted over an unknown history.
    """
    # B7a-3: an epoch of null, "abc" or a dict used to land in the except and
    # come back as a confident 1 with no WARN, which is "cannot determine"
    # wearing the shape of a clean number - the form spec section 4 forbids. It
    # now returns None plus its own reason, so the caller names the gap.
    if err:
        return None, f"the previous lock record was not read ({err})"
    raw = prev.get("epoch", 0)
    try:
        return int(raw) + 1, None
    except (TypeError, ValueError):
        return None, f"the epoch in the previous record is not a number: {raw!r}"


def cmd_lock(args):
    _require_paths()
    if not args.agent:
        print("--lock requires --agent <harness-name>")
        sys.exit(2)
    # D15: classify BEFORE anything is written — including the runtime directory
    # this command creates on its way to the lock file.
    kind, detail = install_layout()
    force_reason = (getattr(args, "reason", None) or "").strip()
    # C1/ruling 1, the gate batch-B7a left: EVERY --force on --lock names a
    # --reason, not only the one over a D15 layout. The lock stays ADVISORY —
    # nothing here is enforced against an agent that never asks for the pen —
    # but an override that does not say why is indistinguishable, in the record
    # it leaves for the next machine, from an accident. rc 1 rather than 2: a
    # reasonless --force over a linked worktree already exited 1 here, and one
    # omission gets one verdict.
    if args.force and not force_reason:
        print("--force must name a --reason: an override that does not say why "
              "is indistinguishable, in the record it leaves, from an accident.")
        if kind != "normal":
            print(f"  this checkout is {kind} ({detail}), so the split itself "
                  "has to be recorded alongside the reason.")
        print("--force takes a lock OVER: the displaced record stays in the "
              "tree and in git history. It does not RESOLVE a conflicted record "
              "- that needs --discard-lock here, or a git resolve.")
        # R2 adjudication 4 overturns the rc batch C1 chose. A missing required
        # companion argument is a USAGE error in this CLI, which exits 2 for
        # "--lock requires --agent", for "--unlock requires --agent <name>" and
        # via argparse; rc 1 is reserved for refusals reached after a verdict was
        # possible (LOCK CONFLICT, LAYOUT REFUSED, CHECKPOINT REFUSED). One
        # omission gets one usage verdict, whatever the layout turned out to be.
        sys.exit(2)
    forced_layout = False
    if kind != "normal":
        if not args.force:
            _layout_refusal(kind, detail)
            sys.exit(1)
        forced_layout = True
        print(f"WARN {kind}: --force with --reason {force_reason!r} - the "
              f"layout is recorded in WRITER_LOCK.json as forced_layout. "
              f"{detail}")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    # `getattr`: the guard tests build a Namespace by hand, so a new flag must
    # not be the reason an unwired command stops raising RuntimeError.
    discard = getattr(args, "discard_lock", False)
    status = lock_state()
    holder = status.holder
    if status.state == "error":
        # D1: an unreadable record is contention, not an empty pen. It is most
        # often the merge this file is designed to hit, and the other machine's
        # acquisition may be sitting inside the unparseable half.
        print("LOCK UNREADABLE: cannot parse the writer lock record - it is "
              "treated as HELD, not as free.")
        print(f"  detail: {status.detail}")
        print("Resolve the git conflict (or repair the JSON) and re-run. If the "
              "record is unrecoverable, --force --discard-lock --reason \"<why>\" "
              "abandons it.")
        if not (args.force and discard):
            sys.exit(1)
        print("  Discarding the unreadable record: the old bytes stay in git "
              "history, so the abandoned hold remains auditable.")
    elif status.state == "held" and holder != args.agent and not args.force:
        lock, _err = read_json_or_error(LOCK_PATH)
        print(f"LOCK CONFLICT: held by {holder} {status.detail} "
              f"(reason: {lock.get('reason', '-')})")
        print("Advisory lock: you may wait for expiry, coordinate, or re-run "
              'with --force --reason "<why>" - that takes the pen over and '
              "records the takeover (and the reason) in the lock itself.")
        sys.exit(1)
    acquired = now_dt()
    expires = acquired.timestamp() + args.ttl
    # Takeover must be auditable AFTER it is pushed: this file is tracked, so
    # whatever is copied out of the displaced record here is what the next
    # machine reads. Read it once, here, whatever the branches above did.
    # The compare-and-write of B6/8, applied to the other reader (finding C1-3):
    # what lands below is validated against the bytes this command actually read,
    # so a merge that arrives mid-command aborts the acquisition instead of being
    # destroyed by it. Bounded and advisory - an ABORT is a re-run, not a server.
    prev, prev_err, prev_raw = read_json_for_update(LOCK_PATH)
    epoch, epoch_err = _next_epoch(prev, prev_err)
    record = {
        "agent": args.agent,
        # C1-6: one read of the reason, through the guarded form above, so a
        # hand-built Namespace without the flag cannot crash this command.
        "reason": force_reason,
        "acquired_at": acquired.isoformat(timespec="seconds"),
        "expires_at": datetime.fromtimestamp(expires, acquired.tzinfo)
                             .isoformat(timespec="seconds"),
        "released_at": None,
    }
    if epoch_err:
        print(f"WARN: the epoch is not recorded - {epoch_err}; restarting the "
              "count at 1 would claim a history this command cannot see.")
        if not prev_err:
            record["epoch_unreadable"] = repr(prev.get("epoch", 0))
    else:
        record["epoch"] = epoch
    # C1-4: the record is built from scratch, so a takeover used to be visible
    # only until the NEXT acquisition rewrote the file, and only if a commit
    # landed in between - which nothing here checks. Two takeovers in one
    # uncommitted session left one record. The chain is additive and travels
    # forward whichever kind of acquisition writes it.
    chain = [e for e in (prev.get("prior_forced") or []) if isinstance(e, dict)]
    displaced_before = prev.get("forced_over")
    if isinstance(displaced_before, dict):
        chain.append(displaced_before)
    if chain:
        record["prior_forced"] = chain
    if args.force:
        displaced = prev.get("agent")
        if prev_err:
            record["forced_over_unreadable"] = prev_err
        elif displaced and displaced != args.agent:
            record["forced_over"] = {
                "agent": displaced,
                "epoch": prev.get("epoch"),
                "acquired_at": prev.get("acquired_at"),
            }
        if forced_layout:
            record["forced_layout"] = kind
            record["forced_layout_detail"] = detail
    elif (status.state == "expired" and prev.get("agent")
            and prev.get("agent") != args.agent):
        # C1-5: the split nobody audited. A TTL ran out mid-task, no --force was
        # involved, and the single writer simply changed - so the displaced name
        # is recorded on the same terms as a forced takeover.
        record["over_expired_hold"] = {
            "agent": prev.get("agent"),
            "acquired_at": prev.get("acquired_at"),
        }
    if not _write_json_if_unchanged(LOCK_PATH, record, prev_raw, "LOCK"):
        sys.exit(2)
    print(f"Writer lock acquired by {args.agent} until {record['expires_at']} "
          f"(TTL {args.ttl}s, advisory)")
    if holder == args.agent:
        print("(renewed an existing lock you already held)")


def cmd_unlock(args):
    _require_paths()
    # Lane Z finding 2 (HIGH): this was the one lock-touching command with no
    # D15 gate. In a linked worktree `--lock` refused at rc 1 while
    # `--unlock --agent <name>` exited 0 and wrote `released_at` into THAT
    # worktree's tracked WRITER_LOCK.json, leaving the main checkout's hold
    # intact -- so machine B pulled "released", started writing, and the writer
    # on machine A never stopped. R1's single-writer rule, broken with the
    # protocol's blessing, and `SKILL.md`'s rc-1 row for "refused checkout
    # layout" was false for this command.
    #
    # The gate is the same classifier, the same rc 1, and the same `--force`
    # override as `_refuse_unliveable_layout()`; that helper is not reused
    # verbatim because its closing sentence ("this command writes no lock
    # record") is the opposite of what a release does.
    kind, detail = install_layout()
    if kind != "normal":
        if getattr(args, "force", False):
            print(f"WARN unlock: this checkout is {kind} ({detail}) and "
                  "--force was given, so the release is written here anyway. "
                  "It lands in this worktree\'s tracked WRITER_LOCK.json; the "
                  "checkout that took the pen keeps reading its own "
                  "released_at: null, so say in the handoff that the release "
                  "was made from a linked worktree.")
        else:
            _layout_refusal(kind, detail, "unlock")
            print("  unlock: the release would be written into THIS worktree\'s "
                  "copy of the tracked lock record while the checkout holding "
                  "the pen keeps reading its own -- the next machine would pull "
                  "\"released\" and start writing beside a live writer. "
                  "--force is the override here too, and it says so in the "
                  "record you commit.")
            sys.exit(1)
    status = lock_state()
    if status.state == "error":
        print(f"Lock record is unreadable ({status.detail}); refusing to release "
              "it blind. Resolve the git conflict, then --unlock --agent <name>.")
        sys.exit(2)
    if status.state == "free":
        # Nothing to release: no record, or one already released — the record is
        # the audit trail, so it is kept, never deleted.
        print("Writer lock: none" + ("" if status.detail == "no lock file"
                                     else f" - {status.detail}"))
        return
    # D2: the holder check used to run only when --agent happened to be passed,
    # which is exactly the command --prime told users to run. An expired record
    # still names whose pen it was, so it needs the name too.
    if not args.agent:
        print(f"--unlock requires --agent <name>: the lock is held by "
              f"{status.holder} ({status.detail}).")
        sys.exit(2)
    if status.holder != args.agent and not args.force:
        print(f"Lock is held by {status.holder}, not {args.agent}. "
              "Use --force to override.")
        sys.exit(1)
    # F2: the error this read used to discard is the one that decides whether a
    # write is allowed at all. The check at the top of the command is not enough
    # — a merge can land on this path mid-command — and writing the {} that a
    # failed read returns would leave a released_at-only stub whose next read
    # says "free": exactly the evidence this batch exists to keep. The record
    # written back is therefore either one that parsed or nothing at all.
    lock, err, lock_raw = read_json_for_update(LOCK_PATH)
    if err:
        print(f"UNLOCK ABORTED: the lock record could not be parsed ({err}); "
              "refusing to release a record this command cannot read. Resolve "
              "the git conflict, then --unlock --agent <name>.")
        sys.exit(2)
    lock["released_at"] = now_iso()
    lock["released_by"] = args.agent
    # B6/8: F2 closed the parse-error half of the read→write window, not the
    # window. A merge that PARSES is the harder case — nothing is wrong with the
    # bytes this command holds, they are simply no longer the bytes on disk, and
    # os.replace would destroy an uncommitted conflict. Compare and refuse.
    if not _write_json_if_unchanged(LOCK_PATH, lock, lock_raw, "UNLOCK"):
        sys.exit(2)
    print(f"Writer lock released at {now_display()}")


def _refuse_unliveable_layout(command, args):
    """V-5 (finding 2.3): the D15 layout gate for the commands that write state.

    `install_layout()` was called from `cmd_lock` and nowhere else, so on a
    linked worktree `--handoff` archived tracked files and exited 0 while
    `--lock` in the very same checkout refused it: the protocol's invariant that
    a per-worktree lock is meaningless was enforced on one of the five commands
    that can create state. One classifier, one gate, same ADVISORY shape — a
    refused layout exits 1 before a byte is written, and `--force` stays the
    documented override.

    What `--force` buys here is a WARN, not a quiet pass, and the WARN says why
    it is weaker than the lock's: a state write creates no record, so there is
    nothing to carry `forced_layout` to the next machine. The reason requirement
    stays on `--lock`, per ruling 5 — a state write takes no pen.
    """
    kind, detail = install_layout()
    if kind == "normal":
        return
    if getattr(args, "force", False):
        print(f"WARN {command}: this checkout is {kind} ({detail}) and --force "
              "was given, so state is written anyway. Nothing records the split: "
              "unlike --lock there is no WRITER_LOCK.json entry to carry "
              "forced_layout, so record it in the handoff yourself.")
        return
    _layout_refusal(kind, detail)
    print(f"  {command}: the same gate --lock applies, and this command writes "
          "no lock record; --force is the override here too.")
    sys.exit(1)


def _guard_state_writes(command, args):
    """F3: the commands that write state must consult the lock they never took.

    Before this, only --status, --prime, --lock and --unlock looked at
    lock_state(), so an agent that skipped --lock could still clobber
    runtime/STATUS.json while a conflicted — i.e. HELD — record sat in the tree,
    which is the whole D1/F1 failure one step to the left.

    The lock stays ADVISORY, deliberately: it coordinates honest agents, and the
    protocol refuses to require a server, so a record that merely names another
    holder warns BY NAME and continues. Only an unreadable record — the state
    this batch defined as HELD — blocks the write.

    B6/2: the override is now the SAME pair --lock demands. Plain --force used to
    open the wall for a state writer while cmd_lock refused it without
    --discard-lock, so an honest agent that obeyed the printed hint cleared the
    block AND left the tracked, still-conflicted WRITER_LOCK.json in the tree for
    the close-out `git add -A` to commit. --force does not resolve a conflict;
    the refusal says so, and the WARN says what the pair does and does not buy.

    V-5: the layout gate runs first, because on a refused checkout the question
    "who else is writing?" is already meaningless — a second worktree holds its
    own record, so a clean lock read here is not evidence of a single writer.
    """
    _refuse_unliveable_layout(command, args)
    status = lock_state()
    if status.state in ("free", "expired"):
        return
    force = bool(getattr(args, "force", False))
    discard = bool(getattr(args, "discard_lock", False))
    if status.state == "error":
        if force and discard:
            print(f"WARN {command}: the writer lock record is unreadable "
                  f"({status.detail}); --force --discard-lock writes state over "
                  "it anyway. That does NOT resolve the conflict: the tracked "
                  "record stays in the tree until --lock --force --discard-lock "
                  "--reason \"<why>\" or a git resolve replaces it, and the "
                  "abandoned "
                  "bytes stay in "
                  "git history, so the hold remains auditable.")
            return
        print(f"{command.upper()} REFUSED: the writer lock record is unreadable "
              f"({status.detail}), which is HELD, not free - no state file is "
              "written. Resolve the git conflict and re-run, or re-run with "
              "--force --discard-lock to write anyway; --force alone does not "
              "resolve the conflict, so it is not accepted here either.")
        sys.exit(1)
    if status.holder == getattr(args, "agent", None):
        return
    print(f"WARN {command}: the writer lock is held by {status.holder} "
          f"{status.detail}, not by "
          f"{getattr(args, 'agent', None) or 'an identified agent'}. Advisory "
          "lock, so this continues: coordinate, wait for expiry, or record the "
          "overlap in the handoff.")



def main():
    protect_stdio()
    try:
        ai_dir, _root = resolve_roots(__file__)
    except RepoError as exc:
        print(f"[FAIL] install layout: {exc}")
        return 2
    _set_paths(ai_dir)

    parser = argparse.ArgumentParser(
        description="Cross-harness continuity checkpoint tool")
    parser.add_argument("--agent", type=str, default=None,
                        help="Active agent name (e.g., claude-code, codex, kimi)")
    parser.add_argument("--task", type=str, default=None,
                        help="Current task description (updates STATUS.json)")
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS,
                        help="Lock TTL in seconds (default 4h)")
    parser.add_argument("--reason", type=str, default=None,
                        help="Task/issue ID or reason recorded on the lock; "
                             "required by every --force, and it names the D15 "
                             "layout override (linked worktree, symlinked "
                             "install, undetermined root)")
    parser.add_argument("--force", action="store_true",
                        help="Take a conflicting lock OVER (reason-required), "
                             "override a refused checkout layout (D15) and, with "
                             "--discard-lock, abandon an unparseable record. "
                             "Takes over; never resolves")
    parser.add_argument("--discard-lock", action="store_true",
                        help="With --force, abandon a lock record that cannot be "
                             "parsed; the discarded bytes stay in git history")

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Show current status")
    group.add_argument("--prime", action="store_true",
                       help="Session-start injection (override: .ai/PRIME.md)")
    group.add_argument("--handoff", action="store_true",
                       help="Archive current handoff, prepare for next agent")
    group.add_argument("--validate", action="store_true",
                       help="Validate required state files exist")
    group.add_argument("--lock", action="store_true",
                       help="Acquire the advisory writer lock")
    group.add_argument("--unlock", action="store_true",
                       help="Release the advisory writer lock "
                            "(--agent <name> is required against a live lock)")

    args = parser.parse_args()

    if args.status:
        cmd_status(args)
    elif args.prime:
        cmd_prime(args)
    elif args.validate:
        # B6/3: --validate writes nothing, and its documented rc 1 means "state
        # files missing or empty" (usage block above, SKILL.md). The F3 gate made
        # rc 1 ALSO mean "the lock was unreadable and nothing was checked", which
        # overloads the code and reports a verdict the command never reached. It
        # is ungated; its own reads are error-aware instead (rc 2 = no verdict).
        cmd_validate(args)
    elif args.handoff or not (args.lock or args.unlock):
        # F3: the two commands that change the tree are --handoff and the
        # bare-checkpoint default, and neither had ever looked at the lock, so
        # skipping --lock was enough to clobber state beside a conflicted (i.e.
        # HELD) record. One gate, at the one place in the CLI where the command
        # being run is known, so THROUGH THE CLI a writer cannot be reached
        # without the lock having been consulted. An in-process cmd_* call after
        # a hand-wired _set_paths() skips it — _require_paths() plus
        # tests/test_ai_common.py is what keeps that route a test and not a
        # workflow.
        command = "handoff" if args.handoff else "checkpoint"
        _guard_state_writes(command, args)
        if args.handoff:
            cmd_handoff(args)
        else:
            cmd_checkpoint(args)
    elif args.lock:
        cmd_lock(args)
    elif args.unlock:
        cmd_unlock(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
