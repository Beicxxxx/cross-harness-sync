#!/usr/bin/env python3
"""Scaffold the cross-harness-sync system into a target repository.

Usage:
    python init_sync.py [REPO_ROOT] [--force] [--no-agents-block]

Creates (never overwrites unless --force):
    .ai/state/{CURRENT,TASK,BLOCKERS,ROLE_POLICY,DECISIONS,DECISIONS_INDEX}.md
    .ai/handoff/{LATEST,NEXT_PROMPT}.md + archive/
    .ai/protocol/VERSION
    .ai/scripts/{checkpoint.py,sync_verify.py}
    .ai/sync_config.json
    .ai/SYNC_PROMPT.md            (onboarding prompt for newly joined agents)
    .ai/templates/AUTHORIZATION.md (per-stage authorization template)
    .gitignore entries for runtime/secrets
    CLAUDE.md pointer (only if no CLAUDE.md exists)
    Managed block inside an existing AGENTS.md (idempotent, marker-delimited);
    if no AGENTS.md exists, the full template is copied instead.

After running, fill in every <placeholder> in AGENTS.md / SYNC_PROMPT.md and
the state files, then commit and push.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_DIR / "templates"

PROTOCOL_VERSION = "2.0.0"

MANAGED_BEGIN = "<!-- BEGIN CROSS-HARNESS-SYNC v:1 -->"
MANAGED_END = "<!-- END CROSS-HARNESS-SYNC -->"
MANAGED_BLOCK = f"""{MANAGED_BEGIN}
## Cross-Harness Continuity (managed block — cross-harness-sync skill)

0. Session start: `git pull --ff-only`, then read ONLY `.ai/state/CURRENT.md`,
   `TASK.md`, `BLOCKERS.md` (L0). Shortcut: `python .ai/scripts/checkpoint.py --prime`.
- L2 archives (DECISIONS/MILESTONES/handoff archive) are retrieval-only via
  `.ai/state/DECISIONS_INDEX.md` or grep — never read in full.
- One active writer: `python .ai/scripts/checkpoint.py --lock --agent <name>`
  before writing state files; review tiers in `.ai/state/ROLE_POLICY.md`.
- New decision = one line in `DECISIONS_INDEX.md` + ≤ 15 lines in `DECISIONS.md`.
- Handoff: `.ai/handoff/LATEST.md`, 6 sections, ≤ 80 lines.
- Close out: `python .ai/scripts/sync_verify.py` all green → `--unlock` →
  commit + push. Never force-push, never commit secrets.
{MANAGED_END}"""

# (source under templates/, destination under repo root)
FILE_MAP = [
    ("CURRENT.md", ".ai/state/CURRENT.md"),
    ("TASK.md", ".ai/state/TASK.md"),
    ("BLOCKERS.md", ".ai/state/BLOCKERS.md"),
    ("ROLE_POLICY.md", ".ai/state/ROLE_POLICY.md"),
    ("DECISIONS.md", ".ai/state/DECISIONS.md"),
    ("DECISIONS_INDEX.md", ".ai/state/DECISIONS_INDEX.md"),
    ("handoff/LATEST.md", ".ai/handoff/LATEST.md"),
    ("handoff/NEXT_PROMPT.md", ".ai/handoff/NEXT_PROMPT.md"),
    ("SYNC_PROMPT.md", ".ai/SYNC_PROMPT.md"),
    ("AUTHORIZATION.md", ".ai/templates/AUTHORIZATION.md"),
    ("sync_config.json", ".ai/sync_config.json"),
]

SCRIPT_MAP = [
    ("checkpoint.py", ".ai/scripts/checkpoint.py"),
    ("sync_verify.py", ".ai/scripts/sync_verify.py"),
]

GITIGNORE_LINES = [
    "",
    "# cross-harness-sync",
    ".ai/runtime/*",
    "!.ai/runtime/WRITER_LOCK.json",
    ".env",
]


def copy_file(src: Path, dst: Path, force: bool) -> str:
    if dst.exists() and not force:
        return f"SKIP (exists): {dst}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    return f"wrote: {dst}"


def update_gitignore(root: Path) -> str:
    gi = root / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    missing = [ln for ln in GITIGNORE_LINES
               if ln and ln not in existing.splitlines()]
    if not missing:
        return ".gitignore: already up to date"
    with open(gi, "a", encoding="utf-8") as f:
        f.write("\n".join(GITIGNORE_LINES) + "\n")
    return f".gitignore: appended {len(missing)} entries"


def update_agents_md(root: Path, force: bool) -> str:
    agents = root / "AGENTS.md"
    if not agents.exists():
        return copy_file(TEMPLATES / "AGENTS.md", agents, force)
    text = agents.read_text(encoding="utf-8")
    if "Canonical instructions for ALL harnesses" in text:
        # Already the full template — the whole protocol is inline, no block needed
        return "AGENTS.md: already the full template, no managed block added"
    if MANAGED_BEGIN in text and MANAGED_END in text:
        pre = text.split(MANAGED_BEGIN)[0]
        post = text.split(MANAGED_END, 1)[1]
        agents.write_text(pre + MANAGED_BLOCK + post, encoding="utf-8")
        return "AGENTS.md: replaced managed block in place"
    with open(agents, "a", encoding="utf-8") as f:
        f.write("\n\n" + MANAGED_BLOCK + "\n")
    return "AGENTS.md: appended managed block"


def write_claude_pointer(root: Path) -> str:
    claude = root / "CLAUDE.md"
    if claude.exists():
        return "CLAUDE.md: exists, untouched (add a pointer to AGENTS.md yourself)"
    claude.write_text(
        "# Claude Code\n\nRead `AGENTS.md` at the project root — it is the "
        "canonical instruction file for ALL harnesses. This file is only a "
        "pointer so Claude Code auto-loads it.\n",
        encoding="utf-8")
    return "CLAUDE.md: wrote pointer to AGENTS.md"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold cross-harness-sync into a repository")
    parser.add_argument("repo_root", nargs="?", default=".",
                        help="Target repository root (default: cwd)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files")
    parser.add_argument("--no-agents-block", action="store_true",
                        help="Do not touch AGENTS.md")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory")
        return 2

    print(f"Scaffolding cross-harness-sync v{PROTOCOL_VERSION} into {root}\n")

    for rel_src, rel_dst in FILE_MAP:
        print(copy_file(TEMPLATES / rel_src, root / rel_dst, args.force))
    for rel_src, rel_dst in SCRIPT_MAP:
        print(copy_file(SKILL_DIR / "scripts" / rel_src, root / rel_dst, args.force))

    version = root / ".ai/protocol/VERSION"
    if args.force or not version.exists():
        version.parent.mkdir(parents=True, exist_ok=True)
        version.write_text(PROTOCOL_VERSION + "\n", encoding="utf-8")
        print(f"wrote: {version}")
    (root / ".ai/handoff/archive").mkdir(parents=True, exist_ok=True)
    (root / ".ai/state/archive").mkdir(parents=True, exist_ok=True)
    (root / ".ai/runtime").mkdir(parents=True, exist_ok=True)

    print(update_gitignore(root))
    if not args.no_agents_block:
        print(update_agents_md(root, args.force))
    print(write_claude_pointer(root))

    print("\nNext steps:")
    print("  1. Fill in every <placeholder> in AGENTS.md, .ai/SYNC_PROMPT.md,")
    print("     and the .ai/state/*.md files.")
    print("  2. Declare project-specific checks in .ai/sync_config.json")
    print("     (extra_checks, secret_mirrors).")
    print("  3. python .ai/scripts/sync_verify.py  → should be all green.")
    print("  4. Commit and push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
