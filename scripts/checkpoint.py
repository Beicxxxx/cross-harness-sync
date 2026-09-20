#!/usr/bin/env python3
"""
Cross-harness continuity checkpoint tool (cross-harness-sync skill).

Usage:
    python .ai/scripts/checkpoint.py                    # Update runtime status
    python .ai/scripts/checkpoint.py --status           # Show current status
    python .ai/scripts/checkpoint.py --prime            # Session-start injection
    python .ai/scripts/checkpoint.py --handoff          # Archive handoff, mark handed-off
    python .ai/scripts/checkpoint.py --validate         # Required files exist & non-empty
    python .ai/scripts/checkpoint.py --lock --agent X   # Acquire advisory writer lock
    python .ai/scripts/checkpoint.py --unlock --agent X # Release the writer lock
    python .ai/scripts/checkpoint.py --lock --agent X --force --discard-lock
                                        # abandon an UNREADABLE lock record: the
                                        # only override for a merged/corrupt one

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
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# Shared primitives, installed next to this file by init_sync.py. There is
# deliberately no inline fallback: a second copy of that plumbing would be a
# second copy of the wrong-root path this removes (see scripts/ai_common.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from ai_common import RepoError, protect_stdio, resolve_roots
except ImportError:
    print("[FAIL] install layout: ai_common.py is missing from .ai/scripts/ — "
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
    local = now_dt()
    offset = local.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    zone = local.tzname() or "local time"
    return f"{local:%Y-%m-%d %H:%M:%S} ({zone}, UTC{offset})"


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
    """
    try:
        raw = _retry_sharing(path.read_bytes)
    except FileNotFoundError:
        return {}, None
    except OSError as exc:
        return {}, f"cannot read: {exc}"
    if b"<<<<<<<" in raw or b">>>>>>>" in raw:
        return {}, "merge conflict markers"
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {}, f"cannot parse: {exc}"
    if not isinstance(data, dict):
        return {}, "cannot parse: expected a JSON object"
    return data, None


def read_json(path):
    """Best-effort read for the untracked runtime files: {} means "no data".

    Lock consumers must NOT use this — they need the error, which is the whole
    of D1. See read_json_or_error.
    """
    data, _err = read_json_or_error(path)
    return data


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
    version_file = PROTOCOL_DIR / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "unknown"


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
                          "no expiry (malformed or absent expires_at) — do not "
                          "rely on the TTL; release with --unlock --force")
    if now_dt() > expires:
        return LockStatus("expired", holder, f"expired {lock['expires_at']}")
    return LockStatus("held", holder, f"until {lock['expires_at']}")


def cmd_status(args):
    _require_paths()
    status = read_json(RUNTIME_DIR / "STATUS.json")
    if not status:
        print("No active session found (runtime/STATUS.json missing or empty)")
    else:
        print(f"Protocol Version : {status.get('protocol_version') or get_protocol_version()}")
        print(f"Active Agent     : {status.get('active_agent', '?')}")
        print(f"Last Checkpoint  : {status.get('last_checkpoint', '?')}")
        print(f"Status           : {status.get('status', '?')}")
        print(f"Current Task     : {status.get('current_task', '?')}")
        print(f"Checkpoints      : {status.get('checkpoint_count', 0)}")

    lock_status = lock_state()
    if lock_status.state == "error":
        print(f"Writer Lock      : CONFLICT/ERROR ({lock_status.detail})"
              " — do NOT write state files; resolve the conflict first")
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
        path = STATE_DIR / name
        mark = "OK " if path.exists() else "MISS"
        size = f"({path.stat().st_size} bytes)" if path.exists() else "(missing)"
        print(f"  [{mark}] {name} {size}")

    print("\nHandoff files:")
    for name in ["LATEST.md", "NEXT_PROMPT.md"]:
        path = HANDOFF_DIR / name
        mark = "OK " if path.exists() else "MISS"
        size = f"({path.stat().st_size} bytes)" if path.exists() else "(missing)"
        print(f"  [{mark}] {name} {size}")

    if ARCHIVE_DIR.exists():
        print(f"\n  Archived handoffs: {len(list(ARCHIVE_DIR.glob('*.md')))}")


def cmd_checkpoint(args):
    _require_paths()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    status = read_json(RUNTIME_DIR / "STATUS.json")
    status["last_checkpoint"] = now_iso()
    status["checkpoint_count"] = status.get("checkpoint_count", 0) + 1
    status["status"] = "active"
    if args.agent:
        status["active_agent"] = args.agent
        write_text_atomic(RUNTIME_DIR / "ACTIVE_AGENT", args.agent + "\n")
    if args.task:
        status["current_task"] = args.task
    status["protocol_version"] = get_protocol_version()
    write_json(RUNTIME_DIR / "STATUS.json", status)
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
        lock_line = (f"CONFLICT/ERROR — {lock_status.detail} — do NOT write state "
                     "files; resolve the conflict first.")
    elif lock_status.state == "held":
        # `HELD by <h> {detail}` with no separator: with detail "until <ts>" this
        # reproduces the pre-fix line byte for byte, so anything reading --prime
        # output keeps matching. The no-expiry detail reads awkwardly there — it
        # is a warning line, not prose.
        lock_line = (f"HELD by {lock_status.holder} {lock_status.detail} — "
                     "if that is not you, do NOT write state files.")
    elif lock_status.state == "expired":
        lock_line = f"expired (was {lock_status.holder}) — free to acquire."
    else:
        lock_line = "none — free to acquire."

    status = read_json(RUNTIME_DIR / "STATUS.json")
    last = status.get("last_checkpoint", "never")
    agent = status.get("active_agent", "?")

    print(f"== SESSION PRIME (cross-harness-sync v{get_protocol_version()}) ==")
    print(f"Writer lock: {lock_line}")
    print(f"Last checkpoint: {last} by {agent}")
    print()
    print("READ NOW (L0, in order, nothing else at startup):")
    print("  1. .ai/state/CURRENT.md")
    print("  2. .ai/state/TASK.md")
    print("  3. .ai/state/BLOCKERS.md")
    print("If continuing prior work, also read: .ai/handoff/LATEST.md")
    print()
    print("Do NOT read in full: DECISIONS.md, MILESTONES.md, handoff/archive/.")
    print("Retrieve single entries via .ai/state/DECISIONS_INDEX.md or grep.")
    print()
    print("Before writing any state file:")
    print("  python .ai/scripts/checkpoint.py --lock --agent <your-harness-name>")
    print("At close-out: python .ai/scripts/sync_verify.py must be all green,")
    print("then --unlock --agent <your-name>, commit, and push.")


def cmd_handoff(args):
    _require_paths()
    latest = HANDOFF_DIR / "LATEST.md"
    if latest.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        agent = args.agent or "unknown"
        archive_name = f"{timestamp}-{agent}-HANDOFF.md"
        shutil.copy2(str(latest), str(ARCHIVE_DIR / archive_name))
        print(f"Archived previous handoff -> {archive_name}")

    status = read_json(RUNTIME_DIR / "STATUS.json")
    status["status"] = "handed-off"
    status["last_checkpoint"] = now_iso()
    if args.agent:
        status["active_agent"] = args.agent
    write_json(RUNTIME_DIR / "STATUS.json", status)

    print(f"Handoff prepared at {now_display()}")
    print()
    print("The coding agent must still update these files manually:")
    print(f"  1. {STATE_DIR / 'CURRENT.md'} — final state snapshot (<= budget lines)")
    print(f"  2. {HANDOFF_DIR / 'LATEST.md'} — 6 sections: Done / Not done /")
    print("     Evidence pointers / Warnings / Next step / Must-read list")
    print(f"  3. {HANDOFF_DIR / 'NEXT_PROMPT.md'} — next agent's starting prompt")
    print()
    print("Then run sync_verify.py, release the lock "
          "(--unlock --agent <name>), commit, and push.")


def cmd_validate(args):
    _require_paths()
    required_files = [
        STATE_DIR / "CURRENT.md",
        STATE_DIR / "TASK.md",
        STATE_DIR / "DECISIONS.md",
        STATE_DIR / "DECISIONS_INDEX.md",
        STATE_DIR / "BLOCKERS.md",
        HANDOFF_DIR / "LATEST.md",
        PROTOCOL_DIR / "VERSION",
    ]
    all_ok = True
    for path in required_files:
        rel = path.relative_to(AI_DIR)
        if not path.exists():
            print(f"  MISSING: {rel}")
            all_ok = False
        elif path.stat().st_size == 0:
            print(f"  EMPTY:   {rel}")
            all_ok = False
        else:
            print(f"  OK:      {rel} ({path.stat().st_size} bytes)")
    print("\nAll state files present and non-empty." if all_ok
          else "\nSome files are missing or empty.")
    sys.exit(0 if all_ok else 1)


def cmd_lock(args):
    _require_paths()
    if not args.agent:
        print("--lock requires --agent <harness-name>")
        sys.exit(2)
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
        print("LOCK UNREADABLE: cannot parse the writer lock record — it is "
              "treated as HELD, not as free.")
        print(f"  detail: {status.detail}")
        print("Resolve the git conflict (or repair the JSON) and re-run. If the "
              "record is unrecoverable, --force --discard-lock abandons it.")
        if not (args.force and discard):
            sys.exit(1)
        print("  Discarding the unreadable record: the old bytes stay in git "
              "history, so the abandoned hold remains auditable.")
    elif status.state == "held" and holder != args.agent and not args.force:
        lock, _err = read_json_or_error(LOCK_PATH)
        print(f"LOCK CONFLICT: held by {holder} {status.detail} "
              f"(reason: {lock.get('reason', '-')})")
        print("Advisory lock: you may wait for expiry, coordinate, or re-run "
              "with --force (record why in the handoff).")
        sys.exit(1)
    acquired = now_dt()
    expires = acquired.timestamp() + args.ttl
    record = {
        "agent": args.agent,
        "reason": args.reason or "",
        "acquired_at": acquired.isoformat(timespec="seconds"),
        "expires_at": datetime.fromtimestamp(expires, acquired.tzinfo)
                             .isoformat(timespec="seconds"),
        "released_at": None,
    }
    write_json(LOCK_PATH, record)
    print(f"Writer lock acquired by {args.agent} until {record['expires_at']} "
          f"(TTL {args.ttl}s, advisory)")
    if holder == args.agent:
        print("(renewed an existing lock you already held)")


def cmd_unlock(args):
    _require_paths()
    status = lock_state()
    if status.state == "error":
        print(f"Lock record is unreadable ({status.detail}); refusing to release "
              "it blind. Resolve the git conflict, then --unlock --agent <name>.")
        sys.exit(2)
    if status.state == "free":
        # Nothing to release: no record, or one already released — the record is
        # the audit trail, so it is kept, never deleted.
        print("Writer lock: none" + ("" if status.detail == "no lock file"
                                     else f" — {status.detail}"))
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
    lock, err = read_json_or_error(LOCK_PATH)
    if err:
        print(f"UNLOCK ABORTED: the lock record could not be parsed ({err}); "
              "refusing to release a record this command cannot read. Resolve "
              "the git conflict, then --unlock --agent <name>.")
        sys.exit(2)
    lock["released_at"] = now_iso()
    lock["released_by"] = args.agent
    write_json(LOCK_PATH, lock)   # never deleted: the record is the audit trail
    print(f"Writer lock released at {now_display()}")


def _guard_state_writes(command, args):
    """F3: the commands that write state must consult the lock they never took.

    Before this, only --status, --prime, --lock and --unlock looked at
    lock_state(), so an agent that skipped --lock could still clobber
    runtime/STATUS.json while a conflicted — i.e. HELD — record sat in the tree,
    which is the whole D1/F1 failure one step to the left.

    The lock stays ADVISORY, deliberately: it coordinates honest agents, and the
    protocol refuses to require a server, so a record that merely names another
    holder warns BY NAME and continues. Only an unreadable record — the state
    this batch defined as HELD — blocks the write, and --force remains the local
    override for it. No enforcement that needs a server, and no wall that
    --force cannot open.
    """
    status = lock_state()
    if status.state in ("free", "expired"):
        return
    force = bool(getattr(args, "force", False))
    if status.state == "error":
        if force:
            print(f"WARN {command}: the writer lock record is unreadable "
                  f"({status.detail}); --force writes state over it anyway.")
            return
        print(f"{command.upper()} REFUSED: the writer lock record is unreadable "
              f"({status.detail}), which is HELD, not free — no state file is "
              "written. Resolve the conflict, or re-run with --force to write "
              "anyway.")
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
                        help="Task/issue ID or reason recorded on the lock")
    parser.add_argument("--force", action="store_true",
                        help="Override a conflicting lock")
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
    elif args.handoff or args.validate or not (args.lock or args.unlock):
        # F3: the three commands that change the tree are --handoff, --validate
        # and the bare-checkpoint default, and none of them had ever looked at
        # the lock, so skipping --lock was enough to clobber state beside a
        # conflicted (i.e. HELD) record. One gate, at the one place where the
        # command being run is known, so a writer cannot be reached without the
        # lock having been consulted.
        command = ("handoff" if args.handoff else
                   "validate" if args.validate else "checkpoint")
        _guard_state_writes(command, args)
        if args.handoff:
            cmd_handoff(args)
        elif args.validate:
            cmd_validate(args)
        else:
            cmd_checkpoint(args)
    elif args.lock:
        cmd_lock(args)
    elif args.unlock:
        cmd_unlock(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
