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
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def parse_iso(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path, data):
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    shutil.move(str(tmp_path), str(path))


def get_protocol_version():
    version_file = PROTOCOL_DIR / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "unknown"


def lock_state():
    """Return (lock_dict, holder, expired) — holder None when no active lock."""
    lock = read_json(LOCK_PATH)
    if not lock or lock.get("released_at"):
        return lock, None, False
    expires = parse_iso(lock.get("expires_at"))
    if expires and now_dt() > expires:
        return lock, None, True
    return lock, lock.get("agent"), False


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

    lock, holder, expired = lock_state()
    if holder:
        print(f"Writer Lock      : HELD by {holder} until {lock.get('expires_at')}"
              f" (reason: {lock.get('reason', '-')})")
    elif lock and expired:
        print(f"Writer Lock      : expired (was {lock.get('agent')}, "
              f"expired {lock.get('expires_at')})")
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
        (RUNTIME_DIR / "ACTIVE_AGENT").write_text(args.agent + "\n", encoding="utf-8")
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

    lock, holder, expired = lock_state()
    if holder:
        lock_line = (f"HELD by {holder} until {lock.get('expires_at')} — "
                     f"if that is not you, do NOT write state files.")
    elif expired:
        lock_line = f"expired (was {lock.get('agent')}) — free to acquire."
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
    print("then --unlock, commit, and push.")


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
    print("Then run sync_verify.py, release the lock (--unlock), commit, and push.")


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
    lock, holder, expired = lock_state()
    if holder and holder != args.agent and not args.force:
        print(f"LOCK CONFLICT: held by {holder} until {lock.get('expires_at')} "
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
    lock, holder, expired = lock_state()
    if not lock:
        print("No lock file found — nothing to release.")
        return
    if holder and args.agent and holder != args.agent and not args.force:
        print(f"Lock is held by {holder}, not {args.agent}. Use --force to override.")
        sys.exit(1)
    lock["released_at"] = now_iso()
    write_json(LOCK_PATH, lock)  # audit artifact: mark released, never delete
    print(f"Writer lock released at {now_display()}")


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
                       help="Release the advisory writer lock")

    args = parser.parse_args()

    if args.status:
        cmd_status(args)
    elif args.prime:
        cmd_prime(args)
    elif args.handoff:
        cmd_handoff(args)
    elif args.validate:
        cmd_validate(args)
    elif args.lock:
        cmd_lock(args)
    elif args.unlock:
        cmd_unlock(args)
    else:
        cmd_checkpoint(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
