#!/usr/bin/env python3
"""Scaffold the cross-harness-sync system into a target repository.

Usage:
    python init_sync.py [REPO_ROOT] [--force] [--clobber] [--scripts-only]
                        [--no-agents-block]

Creates (never overwrites unless --force, and --force never overwrites state
the caller has edited unless --clobber):
    .ai/state/{CURRENT,TASK,BLOCKERS,ROLE_POLICY,DECISIONS,DECISIONS_INDEX}.md
    .ai/handoff/{LATEST,NEXT_PROMPT}.md + archive/
    .ai/protocol/VERSION
    .ai/scripts/{ai_common.py,checkpoint.py,sync_verify.py}
    .ai/sync_config.json
    .ai/SYNC_PROMPT.md            (onboarding prompt for newly joined agents)
    .ai/templates/AUTHORIZATION.md (per-stage authorization template)
    .gitignore entries for runtime/secrets
    CLAUDE.md pointer (only if no CLAUDE.md exists)
    Managed block inside an existing AGENTS.md (idempotent, marker-delimited);
    if no AGENTS.md exists, the full template is copied instead.

After running, fill in every <placeholder> in AGENTS.md / SYNC_PROMPT.md and
the state files, then commit and push.

Flags:
    --force          refresh every file that is still an untouched copy of its
                     template (scripts, protocol files and unedited state).
                     Edited state/config prints KEEP (edited) and survives: in
                     this tool `.ai/state` IS the work state (D7).
    --clobber        overwrite edited state too (implies --force). Prints a
                     warning telling you to commit first, because this is the
                     one path that can destroy work.
    --scripts-only   refresh `.ai/scripts/` and `.ai/protocol/VERSION` and
                     nothing else: no state, config, template, AGENTS.md,
                     CLAUDE.md or .gitignore is read, written or created.
    --no-agents-block  do not touch AGENTS.md — and, because that file then
                     does not exist, write no CLAUDE.md pointer to it and drop
                     its line budget from sync_config.json, so
                     `sync_verify.py` stays green instead of failing forever
                     (D18). A repo that already has AGENTS.md keeps the budget.
"""
from __future__ import annotations

import argparse
import json
import re
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
    ("ai_common.py", ".ai/scripts/ai_common.py"),
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

# Destinations that hold the caller's work rather than the skill's own files:
# everything init installs except `.ai/templates/`, which is protocol text the
# skill re-ships on every upgrade. `--force` refreshes the scripts and these
# only while they are still untouched templates (D7).
PROTECTED_DESTS = frozenset(dst for _, dst in FILE_MAP
                            if not dst.startswith(".ai/templates/"))

PLACEHOLDER_RE = re.compile(r"<[^<>]*>")
_TEMPLATE_INDEX: tuple[frozenset[str], frozenset[str]] | None = None


def _normalised(text: str) -> str:
    """Fold newline style, drop a BOM and trailing whitespace, drop leading and
    trailing blank lines. Content in the middle is left exactly as it is."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _installed_template_texts() -> list[str]:
    paths = [TEMPLATES / rel for rel, _ in FILE_MAP]
    paths.append(TEMPLATES / "AGENTS.md")
    out = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            out.append(_normalised(path.read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeDecodeError):
            continue
    return out


def _template_index() -> tuple[frozenset[str], frozenset[str]]:
    """`(whole templates, every line any template contains)`, built once."""
    global _TEMPLATE_INDEX
    if _TEMPLATE_INDEX is None:
        blobs = frozenset(_installed_template_texts())
        lines = {ln for blob in blobs for ln in blob.split("\n") if ln.strip()}
        _TEMPLATE_INDEX = (blobs, frozenset(lines))
    return _TEMPLATE_INDEX


def is_template_shaped(text: str) -> bool:
    """True only for a copy of one of OUR templates that nobody wrote in.

    Both signals are measured against the shipped templates instead of against a
    guess about what prose looks like:

      * the text is one whole installed template, unchanged apart from newline /
        BOM / trailing-whitespace noise, or
      * every non-blank line is either a line that already appears in a shipped
        template or a line still carrying an unfilled `<placeholder>`. The
        second signal is what survives a protocol upgrade, where the file on
        disk is the previous version's untouched template.

    The line-by-line version of this rule, as written in the wave 1a plan,
    cannot work: our
    own templates hold static prose paragraphs ("Archived:
    `.ai/state/archive/STAGE_MAP.md` ...") that no placeholder marks, so a rule
    that demands a placeholder on every content line calls an untouched
    CURRENT.md edited (and --force then refreshes nothing), while a rule that
    skips `|`- and `-`-prefixed lines calls a filled-in state table untouched —
    destroying exactly the file D7 is about.

    Known limit: a caller who only DELETED lines from a template still reads as
    untouched, and refreshing it puts those lines back. No text of theirs is
    lost, which is the asymmetry this guard optimises for; `--clobber` stays the
    only path that overwrites anything recognised as edited.
    """
    norm = _normalised(text)
    if not norm:
        return False
    blobs, anchors = _template_index()
    if norm in blobs:
        return True
    for line in (ln for ln in norm.split("\n") if ln.strip()):
        if line in anchors or PLACEHOLDER_RE.search(line) or "<!--" in line:
            continue
        return False
    return True


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def copy_file(src: Path, dst: Path, force: bool,
              protected: bool = False) -> str:
    """Install one file. The return value is a printed line, never an exception.

    D24: the source is checked before anything is written. `shutil.copy2` on a
    missing template raised straight out of the install loop, so one deleted
    template left a half-built `.ai/` tree and a traceback instead of a name.
    """
    if not src.is_file():
        return f"ERROR (missing source template): {src}"
    if dst.exists():
        if not force:
            return f"SKIP (exists): {dst}"
        if protected:
            existing = _read_text(dst)
            if existing is None:
                return (f"KEEP (unreadable): {dst} — not text we can compare; "
                        "pass --clobber to overwrite")
            if not is_template_shaped(existing):
                return f"KEEP (edited): {dst} — pass --clobber to overwrite"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    return f"wrote: {dst}"


def update_gitignore(root: Path, wanted: list[str] | None = None) -> str:
    """Append only the lines that are genuinely absent, and say how many.

    D17: the old version decided *whether* to write by looking for one missing
    line and then appended the whole block, so a repo that already listed
    `.env` got a second `.env` and a second marker — while being told
    `appended 4 entries` about five lines it had just written.
    """
    lines = GITIGNORE_LINES if wanted is None else list(wanted)
    gi = root / ".gitignore"
    existing = _read_text(gi) if gi.exists() else ""
    if existing is None:
        return (f"WARNING: {gi} is not readable UTF-8 text; nothing was "
                "appended, declare the entries yourself")
    have = set(existing.splitlines())
    missing = [ln for ln in lines if ln not in have]
    if not missing:
        return ".gitignore: already up to date"
    with open(gi, "a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write("\n".join(missing) + "\n")
    return f".gitignore: appended {len(missing)} entries"


def _splice_out_budget_line(text: str) -> str | None:
    """Return `text` with the `"AGENTS.md": <n>,` budget line deleted, or None.

    The point is the byte shape: a JSON round-trip reflows every array in the
    file, which turns a config nobody touched into text no template contains,
    and `--force` then reports it KEEP (edited) and never restores the budget it
    pruned here. Splicing the one line leaves the rest of the file as the
    template shipped it, and the result is re-parsed before it is trusted.
    """
    lines = text.split("\n")
    idx = None
    for i, line in enumerate(lines):
        if re.match(r'^\s*"AGENTS\.md"\s*:\s*\d+\s*,?\s*$', line):
            idx = i
            break
    if idx is None:
        return None
    had_comma = lines[idx].rstrip().endswith(",")
    del lines[idx]
    if not had_comma:
        for j in range(idx - 1, -1, -1):
            if not lines[j].strip():
                continue
            if lines[j].rstrip().endswith(","):
                lines[j] = lines[j].rstrip()[:-1]
            break
    spliced = "\n".join(lines)
    try:
        parsed = json.loads(spliced)
    except json.JSONDecodeError:
        return None
    if "AGENTS.md" in parsed.get("budgets", {}):
        return None
    return spliced


def drop_agents_md_budget(root: Path) -> str:
    """D18: do not leave a budget for a file `--no-agents-block` never created.

    `AGENTS.md` is in no required-file list, so its line budget is the only
    thing that watches it; turning "missing budget file" into a WARN instead of
    pruning here would leave the file monitored by nothing. A repo that already
    has its own AGENTS.md keeps the budget — the flag means "do not touch
    AGENTS.md", not "stop checking it".
    """
    cfg_path = root / ".ai" / "sync_config.json"
    if not cfg_path.is_file():
        return "sync_config.json: not installed, nothing to prune"
    if (root / "AGENTS.md").exists():
        return ("sync_config.json: kept AGENTS.md budget (the repo already has "
                "AGENTS.md, so the budget still applies)")
    text = _read_text(cfg_path)
    if text is None:
        return f"ERROR (unreadable config, cannot prune): {cfg_path}"
    try:
        cfg = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"ERROR (unparseable config, cannot prune): {cfg_path}: {exc}"
    budgets = cfg.get("budgets")
    if not isinstance(budgets, dict) or "AGENTS.md" not in budgets:
        return "sync_config.json: no AGENTS.md budget to drop"
    removed = budgets.get("AGENTS.md")
    spliced = _splice_out_budget_line(text)
    if spliced is None:
        budgets.pop("AGENTS.md")
        spliced = json.dumps(cfg, indent=2) + "\n"
    cfg_path.write_text(spliced, encoding="utf-8")
    return (f"sync_config.json: dropped AGENTS.md budget (was {removed}) because "
            "--no-agents-block did not create the file")


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
                        help="Overwrite existing files that are still "
                             "untouched templates; edited state and config are "
                             "kept (see --clobber)")
    parser.add_argument("--clobber", action="store_true",
                        help="Overwrite edited state files too (implies "
                             "--force); commit first, this is the one path "
                             "that can destroy work")
    parser.add_argument("--scripts-only", action="store_true",
                        help="Refresh .ai/scripts/ and protocol/VERSION only; "
                             "leave state, config, AGENTS.md, CLAUDE.md and "
                             ".gitignore alone")
    parser.add_argument("--no-agents-block", action="store_true",
                        help="Do not touch AGENTS.md")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory")
        return 2

    # --clobber is strictly stronger than --force, so it implies it rather than
    # silently doing nothing when it is the only one passed.
    force = args.force or args.clobber
    # With --clobber nothing is protected; copy_file keeps its original meaning
    # of "overwrite this destination".
    protect = not args.clobber
    rc = 0

    print(f"Scaffolding cross-harness-sync v{PROTOCOL_VERSION} into {root}\n")
    if args.clobber:
        print("WARNING: --clobber overwrites edited .ai state and config. Commit "
              "the work first (`git add -A && git commit`) so this stays "
              "recoverable.")

    if args.scripts_only:
        print("scripts-only: state files, handoff, sync_config.json, "
              ".ai/templates/, AGENTS.md, CLAUDE.md and .gitignore are left "
              "exactly as they are")
    else:
        for rel_src, rel_dst in FILE_MAP:
            line = copy_file(TEMPLATES / rel_src, root / rel_dst, force,
                             protected=protect and rel_dst in PROTECTED_DESTS)
            print(line)
            if line.startswith("ERROR"):
                rc = 1

    for rel_src, rel_dst in SCRIPT_MAP:
        line = copy_file(SKILL_DIR / "scripts" / rel_src, root / rel_dst, force)
        print(line)
        if line.startswith("ERROR"):
            rc = 1

    version = root / ".ai/protocol/VERSION"
    if force or not version.exists():
        version.parent.mkdir(parents=True, exist_ok=True)
        version.write_text(PROTOCOL_VERSION + "\n", encoding="utf-8")
        print(f"wrote: {version}")
    (root / ".ai/handoff/archive").mkdir(parents=True, exist_ok=True)
    (root / ".ai/state/archive").mkdir(parents=True, exist_ok=True)
    (root / ".ai/runtime").mkdir(parents=True, exist_ok=True)

    if not args.scripts_only:
        line = update_gitignore(root)
        print(line)
        if line.startswith("ERROR"):
            rc = 1
        if args.no_agents_block:
            line = drop_agents_md_budget(root)
            print(line)
            if line.startswith("ERROR"):
                rc = 1
            print("CLAUDE.md: not written (--no-agents-block)")
        else:
            print(update_agents_md(root, force))
            print(write_claude_pointer(root))

    print("\nNext steps:")
    print("  1. Fill in every <placeholder> in AGENTS.md, .ai/SYNC_PROMPT.md,")
    print("     and the .ai/state/*.md files.")
    print("  2. Declare project-specific checks in .ai/sync_config.json")
    print("     (extra_checks, secret_mirrors).")
    print("  3. python .ai/scripts/sync_verify.py  → should be all green.")
    print("  4. Commit and push.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
