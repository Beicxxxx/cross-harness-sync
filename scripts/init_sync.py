#!/usr/bin/env python3
"""Scaffold the cross-harness-sync system into a target repository.

Usage:
    python init_sync.py [REPO_ROOT] [--force] [--clobber] [--scripts-only]
                        [--no-agents-block]
    python init_sync.py [REPO_ROOT] --migrate [--authorizations-dir DIR]

Creates (never overwrites unless --force, and --force never overwrites state
the caller has edited unless --clobber):
    .ai/state/{CURRENT,TASK,BLOCKERS,ROLE_POLICY,DECISIONS,DECISIONS_INDEX}.md
    .ai/state/authorizations/INDEX.md  (the record index wave 1b requires)
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

After running, fill in the <placeholders> that describe this project's work: the
state skeletons in `.ai/state/*.md` and `.ai/SYNC_PROMPT.md`, then commit and
push. The installer's own slots are resolved by the run itself (wave 1c C1/C3) -
AGENTS.md's project name, remote and commit identity, and ROLE_POLICY.md's Adopted
line - because a rule document whose authorship still reads `<who>` is not waiting
on the user, and nothing else can complete it.

Before anything is written, an existing install's `.ai/protocol/VERSION` is
compared with this script's own PROTOCOL_VERSION (D22). A stamp newer than these
scripts, or one that does not parse, stops the run with `VERSION MISMATCH:
<detail>` and exit 1 — `--force` and `--clobber` included, since a downgrade
would overwrite the only record of the higher number. An older stamp is reported
as the upgrade path and the install proceeds.

Flags:
    --force          refresh every file that is still an untouched copy of its
                     template (scripts, protocol files and unedited state).
                     Edited state/config prints KEEP (edited) and survives: in
                     this tool `.ai/state` IS the work state (D7).
    --clobber        overwrite edited state too (implies --force). Prints a
                     warning telling you to commit first, because this is the
                     one path that can destroy work.
    --scripts-only   the upgrade path. It refreshes `.ai/scripts/*.py` and
                     `.ai/protocol/VERSION`, creates the tracked `.gitkeep`
                     placeholders for the empty protocol directories, and
                     appends the `.gitignore` exception that makes the runtime
                     placeholder addable (D16's fix has to reach this flag or it
                     only ever works on a fresh install). What it never touches
                     is anything the user wrote: no state file, no
                     `sync_config.json`, no template, no AGENTS.md, no CLAUDE.md
                     is read or created. Each script whose bytes differ from the
                     shipped copy is named with a `NOTE replaced:` line, which
                     also says whether it looks like a local edit.
    --no-agents-block  do not touch AGENTS.md — and, because that file then
                     does not exist, write no CLAUDE.md pointer to it and drop
                     its line budget from sync_config.json, so
                     `sync_verify.py` stays green instead of failing forever
                     (D18). A repo that already has AGENTS.md keeps the budget.
    --migrate        the governance upgrade (spec §8). Records what v2.0 never
                     recorded on an EXISTING install: creates
                     `.ai/state/authorizations/` and its `INDEX.md`, pins
                     `role_policy_sha256`, deep-adds the config's governance
                     namespaces as TEXT, anchors `governance.window_start_commit`
                     on a real 40-hex HEAD (or the `NO_HISTORY` sentinel where
                     there is no repository to anchor on, which the verifier
                     reads as a named skip and never a pass), writes
                     `.ai/protocol/MIGRATION.json` plus a journal naming what a
                     revert cannot undo, and commits `.ai/**` only — never the
                     writer-lock record, which it acquires first and releases by
                     hand afterwards. Refuses (exit 2, nothing written) on an
                     unborn or detached HEAD, a newer or unparseable stamp, an
                     unparseable config, an unstaged edit under `.ai/scripts/`,
                     a staged change outside `.ai/`, a held lock, or a git that
                     cannot be asked at all (no `git` on PATH, a refused probe
                     such as dubious ownership, `index.lock` contention) — the
                     last is its own halt, never the no-repository bucket; a
                     diverged script gets a `.new` sidecar instead of a clobber,
                     recorded in the migration record's `warnings`/`degraded`; a
                     re-run verifies instead of migrating again.
    --authorizations-dir  where the stage records live. Never guessed: the flag
                     wins, then the config's `authorizations_dir`, then
                     `.ai/state/authorizations`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from ai_common import compare_version, protect_stdio
except ImportError:  # imported by path (a test, or a caller off PATH)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ai_common import compare_version, protect_stdio

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL_DIR / "templates"

# The PROTOCOL version, not the skill's marketing version: it is what
# `.ai/protocol/VERSION` gets stamped with, and what `check_version_match`
# compares an existing install against. It read "2.0.0" on a v2.1 tree for the
# whole of wave 1a because nothing compared it with anything (D22) — a constant
# nobody reads is a constant that drifts, which is why the comparison below is
# the fix and this number is only its subject.
# Lane Z finding 7: this used to be the only copy of the number, in the one
# script that is NOT installed -- which is why an installed tree could not
# cross-check its own `protocol/VERSION`. The constant moved to
# `ai_common.py`, which ships with the scripts, and both this installer and the
# verifier read it from there, so a stamp and the code it describes cannot be
# edited apart. Imported by path because `init_sync.py` runs from the skill
# checkout, where `scripts/` is its own directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_common import PROTOCOL_VERSION  # noqa: E402

# spec §8's migration reads the repository through the SAME three-valued probes
# the verifier uses — one definition of "what does git say about HEAD", not a
# second one that can disagree with it on the machine that asks.
from ai_common import (INSTALLER_SLOTS, NO_HISTORY, SHA_HEX_LEN, git_available,  # noqa: E402
                       is_git_repo, run_argv, run_git, window_is_valid)

# `check_version_match`'s fourth answer, as a constant so `main()` can tell
# "nothing to compare yet" from a verdict without re-reading the sentence.
NO_INSTALLED_VERSION = "no existing install"


def check_version_match(root: Path) -> tuple[bool, str]:
    """`(ok, detail)` for installing THESE scripts over what is already there.

    D22's whole point: the two numbers existed and never met. Four answers —
    no install, a comparable older install (the upgrade path every v2.0 install
    needs, including the one `--scripts-only` exists to serve), an identical
    stamp, and a refusal — so a skew is recorded by the tool that could notice
    it instead of being smoothed over by it.

    The refusal is real in both directions of "newer than these scripts", and
    `--force` does not buy it: an override that ignores a protocol it cannot
    read would rewrite `VERSION` to a lower number and take the evidence of the
    skew with it. The remedy is therefore named as the checkout, never as a
    flag.
    """
    path = root / ".ai" / "protocol" / "VERSION"
    if not path.exists():
        return True, NO_INSTALLED_VERSION
    try:
        installed = path.read_text(encoding="utf-8-sig").strip()
        delta = compare_version(installed, PROTOCOL_VERSION)
    except ValueError as exc:
        return False, f"unparseable: {exc}"
    except OSError as exc:
        return False, (f"{path} cannot be read ({type(exc).__name__}: {exc}); "
                       "refusing to install over a protocol this tool cannot see")
    if delta > 0:
        return False, (f"{installed} is NEWER than these scripts "
                       f"({PROTOCOL_VERSION}); refusing to downgrade the "
                       "install. Update the cross-harness-sync checkout "
                       "(`git pull` in the skill repo, then re-run this "
                       "installer). Nothing was written.")
    if delta < 0:
        return True, (f"{installed} -> {PROTOCOL_VERSION} (upgrade: these "
                      "scripts are newer than the installed protocol; "
                      "--scripts-only or --force refreshes it)")
    return True, f"{installed} (unchanged)"

MANAGED_BEGIN = "<!-- BEGIN CROSS-HARNESS-SYNC v:1 -->"
MANAGED_END = "<!-- END CROSS-HARNESS-SYNC -->"
MANAGED_BLOCK = f"""{MANAGED_BEGIN}
## Cross-Harness Continuity (managed block — cross-harness-sync skill)

0. Session start: `git pull --ff-only`, then read ONLY `.ai/state/CURRENT.md`,
   `TASK.md`, `BLOCKERS.md` (L0). Shortcut: `python .ai/scripts/checkpoint.py --prime`.
- L2 archives (DECISIONS/handoff archive) are retrieval-only via
  `.ai/state/DECISIONS_INDEX.md` or grep — never read in full.
- One active writer: `python .ai/scripts/checkpoint.py --lock --agent <name>`
  before writing state files; review tiers in `.ai/state/ROLE_POLICY.md`.
- New decision = one line in `DECISIONS_INDEX.md` + ≤ 15 lines in `DECISIONS.md`.
- Handoff: `.ai/handoff/LATEST.md`, 6 sections, ≤ 80 lines.
- Close out: `sync_verify.py` → no `FAILED:` line; a named `[SKIP]` is expected,
  silence is not → `--unlock --agent <name>` → commit + push, never force-push.
{MANAGED_END}"""

# N2: the markers are recognised as a FAMILY, not as the two literals above.
# Matching `MANAGED_BEGIN in text` meant that retyping one character of the HTML
# comment — a `v:1` -> `v:2` upgrade, a formatter, one side of a merge conflict —
# sent the next install down the append branch, duplicating the whole protocol
# block at +16 lines per run with no bound, in the file every harness auto-loads.
MANAGED_BEGIN_RE = re.compile(
    r"^\s*<!--\s*BEGIN CROSS-HARNESS-SYNC\b.*?-->\s*$", re.I)
MANAGED_END_RE = re.compile(r"^\s*<!--\s*END CROSS-HARNESS-SYNC\s*-->\s*$", re.I)

# N1/D27: the block is not free. As the append branch writes it it contributes
# its own lines plus two blank separators, and `sync_verify.py` counts the whole
# file against `.ai/sync_config.json`'s `"AGENTS.md"` cap. A constant cap that
# installing this tool is guaranteed to violate is a broken cap, so the budget is
# raised at install time by exactly this number.
MANAGED_BLOCK_LINES = len(MANAGED_BLOCK.splitlines())
BLOCK_APPEND_SPAN = MANAGED_BLOCK_LINES + 2  # "\n\n" + block + "\n"

# Mirrors `"AGENTS.md": 65` in templates/sync_config.json (and the built-in
# default in scripts/sync_verify.py): the cap on the caller's OWN instructions,
# which the raise below deliberately does not touch.
AGENTS_BUDGET_KEY = "AGENTS.md"
AGENTS_OWN_BUDGET = 65

# (source under templates/, destination under repo root)
#
# `authorizations/INDEX.md` is here because wave 1b makes it a REQUIRED file at
# the same moment it becomes something the installer writes: a required file
# nothing creates reddens every fresh install, and the two halves of that
# sentence have to land in one commit.
AUTHORIZATIONS_INDEX_SRC = "authorizations/INDEX.md"
AUTHORIZATIONS_INDEX_REL = ".ai/state/authorizations/INDEX.md"

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
    # wave 1b: the authorization records get a canonical home AND an index, in
    # the same commit that makes that index a required file. Required-but-unwritten
    # is the failure mode `ai_common.DEFAULT_REQUIRED_FILES` documents.
    (AUTHORIZATIONS_INDEX_SRC, AUTHORIZATIONS_INDEX_REL),
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
    # D16: `.ai/runtime/` is the one protocol directory that is empty on install
    # day, and git does not track empty directories, so it never reached a clone.
    # The placeholder that fixes that lives INSIDE the ignore glob above, so it
    # needs its own exception or `git add -A` silently skips it and the second
    # machine is back to a missing directory.
    "!.ai/runtime/.gitkeep",
    ".env",
    # N5: the protocol's own scripts generate bytecode inside the target, and
    # the installed instructions tell every agent to `git add -A && git commit
    # && git push` at each close-out — so an unignored __pycache__ is committed
    # AND delivered to the other machine. This repo had to add the same two
    # entries during Task 0; the shipped install list never learned.
    "__pycache__/",
    "*.pyc",
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


_INSTALLER_SLOT_LINES: tuple[re.Pattern, ...] | None = None


def installer_slot_lines() -> tuple[re.Pattern, ...]:
    """Each template line holding an installer-owned slot, as a matcher for its fills.

    `fill_installer_slots()` rewrites such a line with a date, a name or a URL
    that appears in no shipped template, so `is_template_shaped()` would call the
    file hand-edited from the moment it is created: `--force` would then refresh
    nothing, which is the dead end this predicate exists to avoid. Both ends of
    the line stay anchored and only the filled span is free, so prose a user wrote
    after the slot still fails the test.
    """
    global _INSTALLER_SLOT_LINES
    if _INSTALLER_SLOT_LINES is None:
        slots = [slot for group in INSTALLER_SLOTS.values() for slot in group]
        out = []
        for blob in _installed_template_texts():
            for line in blob.split("\n"):
                if not any(slot in line for slot in slots):
                    continue
                parts = re.split(r"<[^<>]*>", line)
                out.append(re.compile("^" + ".*?".join(map(re.escape, parts)) + "$"))
        _INSTALLER_SLOT_LINES = tuple(out)
    return _INSTALLER_SLOT_LINES


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
    slot_lines = installer_slot_lines()
    for line in (ln for ln in norm.split("\n") if ln.strip()):
        if line in anchors or PLACEHOLDER_RE.search(line) or "<!--" in line:
            continue
        if any(match.match(line) for match in slot_lines):
            continue
        return False
    return True


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _read_raw_text(path: Path) -> tuple[str | None, str | None]:
    """`(text, why-not)` for a file that belongs to the caller.

    N3: the text keeps the file's OWN line terminators. `read_text` folds CRLF to
    LF and the matching `write_text` then emits `os.linesep`, so an install run
    on Windows reformatted the caller's whole file while it was only asked to add
    a block to it.

    N4: a file that cannot be decoded is reported as a name instead of raising
    out of `main()`, so the caller can leave it exactly as it found it —
    `UnicodeDecodeError` here used to abort the install after `.gitignore` had
    been appended, wrote no `CLAUDE.md`, and named nothing.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"cannot be read ({exc.__class__.__name__})"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, f"is not UTF-8 text ({exc})"


def _dominant_newline(text: str) -> str:
    """The terminator this text mostly uses; LF when it has none or ties."""
    crlf = text.count("\r\n")
    return "\r\n" if crlf > text.count("\n") - crlf else "\n"


def _write_bytes_text(path: Path, body: str) -> None:
    """Write exact bytes — no newline translation anywhere (N3)."""
    path.write_bytes(body.encode("utf-8"))


def _write_text(path: Path, text: str, term: str = "\n") -> None:
    """Write LF-separated `text` with `term`, never with the platform default.

    Every write in this module used to go through `write_text` or an append-mode
    handle with no `newline=`, i.e. "translate \\n to os.linesep": `CLAUDE.md`,
    `.ai/protocol/VERSION` and the pruned config came out CRLF on Windows while
    every template copied with `copy2` is LF.
    """
    _write_bytes_text(path, text if term == "\n" else text.replace("\n", term))


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
                return (f"KEEP (unreadable): {dst} - not text we can compare; "
                        "pass --clobber to overwrite")
            if not is_template_shaped(existing):
                return f"KEEP (edited): {dst} - pass --clobber to overwrite"
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
    body = ""
    if gi.exists():
        text, _ = _read_raw_text(gi)
        if text is None:
            return (f"WARNING: {gi} is not readable UTF-8 text; nothing was "
                    "appended, declare the entries yourself")
        body = text
    term = _dominant_newline(body)
    # A BOM is content to preserve, not part of the first pattern; utf-8-sig
    # used to hide it here while the append left it on disk.
    have = set(body.lstrip("\ufeff").splitlines())
    missing = [ln for ln in lines if ln not in have]
    if not missing:
        return ".gitignore: already up to date"
    if body and not body.endswith("\n"):
        body += term
    _write_bytes_text(gi, body + term.join(missing) + term)
    return f".gitignore: appended {len(missing)} entries"


def _splice_out_budget_line(text: str) -> str | None:
    """D18: drop the `"AGENTS.md"` budget line, keeping the file's byte shape."""
    return _splice_budget_line(text, AGENTS_BUDGET_KEY, None)


# ---- the text-level JSON editor `--migrate` edits the config with ------------
# Every constant here is derived from the file's OWN line terminator, because
# N3's defect was a text edit that rewrote the caller's whole file while it was
# only asked to add a line to it.

def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _json_string_end(text: str, i: int) -> tuple:
    """`(index past the closing quote, the decoded string)`; `(-1, "")` if the
    literal is unterminated. The scanner needs both: the end to keep walking
    with, the value to compare against a key name."""
    j = i + 1
    while j < len(text):
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == '"':
            return j + 1, text[i + 1:j]
        j += 1
    return -1, ""


def _json_value_end(text: str, i: int) -> int:
    """Index just past the JSON value starting at `text[i]`; -1 if malformed.

    Balanced-brace walking with string awareness, because `"{}"` inside a string
    is the one thing a `text.index("}")` gets wrong - and getting it wrong here
    means writing a config that no longer parses.
    """
    if i < 0 or i >= len(text):
        return -1
    ch = text[i]
    if ch == '"':
        end, _ = _json_string_end(text, i)
        return end
    if ch in "{[":
        close = "}" if ch == "{" else "]"
        j = i + 1
        while True:
            j = _skip_ws(text, j)
            if j >= len(text):
                return -1
            if text[j] == close:
                return j + 1
            if text[j] == ",":
                # The separator between two members: consume it and look again.
                j += 1
                continue
            if ch == "{":
                # an object's element is a `"key": value` member, so the key,
                # the colon and the value all have to be where they belong.
                if text[j] != '"':
                    return -1
                k, _ = _json_string_end(text, j)
                if k < 0:
                    return -1
                k = _skip_ws(text, k)
                if k >= len(text) or text[k] != ":":
                    return -1
                j = _skip_ws(text, k + 1)
            end = _json_value_end(text, j)
            if end < 0:
                return -1
            j = end
    j = i
    while j < len(text) and text[j] not in ",}] \t\r\n":
        j += 1
    return j if j > i else -1


def _find_member(text: str, obj_start: int, key: str) -> int:
    """Index of the opening quote of `"key"` in the object at `obj_start`, or -1."""
    pos = obj_start + 1
    while True:
        pos = _skip_ws(text, pos)
        if pos < 0 or pos >= len(text):
            return -1
        ch = text[pos]
        if ch == "}":
            return -1
        if ch == ",":
            pos += 1
            continue
        if ch != '"':
            return -1
        k, _name = _json_string_end(text, pos)
        if k < 0:
            return -1
        try:
            decoded = json.loads(text[pos:k])
        except ValueError:
            return -1
        after = _skip_ws(text, k)
        if after < 0 or after >= len(text) or text[after] != ":":
            return -1
        v_start = _skip_ws(text, after + 1)
        v_end = _json_value_end(text, v_start)
        if v_end < 0:
            return -1
        if decoded == key:
            return pos
        pos = v_end


def _member_value(text: str, quote: int) -> tuple:
    """`(value_start, value_end)` for the member whose key quote is at `quote`."""
    k, _name = _json_string_end(text, quote)
    after = _skip_ws(text, k)
    v_start = _skip_ws(text, after + 1)
    return v_start, _json_value_end(text, v_start)


def _object_start(text: str, obj_start: int, key: str) -> int:
    """The `{` of the sub-object stored at `key` inside `obj_start`, or -1."""
    quote = _find_member(text, obj_start, key)
    if quote < 0:
        return -1
    v_start, v_end = _member_value(text, quote)
    if v_start < 0 or v_end < 0 or text[v_start:v_start + 1] != "{":
        return -1
    return v_start


def _leading_len(text: str, line_start: int) -> int:
    i = line_start
    while i < len(text) and text[i] in " \t":
        i += 1
    return i


def _insert_member(text: str, obj_start: int, member: str) -> str:
    """Add `member` (a `"key": value` string) as the last member of the object."""
    end = _json_value_end(text, obj_start)
    if end < 0:
        return text
    nl = _dominant_newline(text)
    close = end - 1
    line_start = text.rfind("\n", 0, obj_start) + 1
    outer_indent = text[line_start:_leading_len(text, line_start)]
    first = _skip_ws(text, obj_start + 1)
    if first < 0 or first > close:
        return text
    if text[first] == "}":
        # An empty object: open it up around the one member it now has.
        return (text[:obj_start + 1] + nl + outer_indent + "  " + member
                + nl + outer_indent + text[close:])
    line_start = text.rfind("\n", 0, first) + 1
    inner_indent = text[line_start:_leading_len(text, line_start)]
    p = close - 1
    while p > obj_start and text[p] in " \t\r\n":
        p -= 1
    return (text[:p + 1] + "," + nl + inner_indent + member
            + text[p + 1:])


def _replace_member_value(text: str, quote: int, value_json: str) -> str:
    v_start, v_end = _member_value(text, quote)
    if v_start < 0 or v_end < 0:
        return text
    return text[:v_start] + value_json + text[v_end:]


def _apply_edits(data, edits: list):
    """`data` with the same edits applied in memory - the comparison target."""
    out = json.loads(json.dumps(data))
    for path, value_json in edits:
        try:
            value = json.loads(value_json)
        except ValueError:
            return None
        node = out
        for key in path[:-1]:
            if not isinstance(node, dict):
                return out
            nxt = node.get(key)
            if not isinstance(nxt, dict):
                return out
            node = nxt
        if not isinstance(node, dict):
            return out
        node[path[-1]] = value
    return out


def _splice_json(text: str, edits: list) -> str:
    """Apply `[(path, value_json)]` as TEXT; the ORIGINAL text whenever the
    result would not parse back to exactly the same document.

    `_splice_budget_line()`'s discipline, generalised (that is what the
    byte-shape rule is for - a `json.dumps` round trip reflows every array and
    rewrites every key the owner added, which turns "one line touched" into a
    diff nobody reads). So: splice, then re-parse and compare against the same
    edits applied in memory, and refuse the whole edit set on any mismatch.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, dict):
        return text
    out = text
    for path, value_json in edits:
        obj = out.index("{")
        for key in path[:-1]:
            obj = _object_start(out, obj, key)
            if obj < 0:
                # A parent segment is absent or is not an object: adding the
                # whole parent is the caller's decision, not a guess made here.
                return text
        quote = _find_member(out, obj, path[-1])
        member = json.dumps(path[-1], ensure_ascii=False) + ": " + value_json
        if quote < 0:
            new = _insert_member(out, obj, member)
        else:
            new = _replace_member_value(out, quote, value_json)
        if new == out:
            return text
        out = new
    expected = _apply_edits(data, edits)
    try:
        got = json.loads(out)
    except ValueError:
        return text
    return out if got == expected else text


def _splice_budget_line(text: str, key: str, value: int | None) -> str | None:
    """Return `text` with `"key": <n>` set to `value`, or deleted when `value` is
    None; None if that cannot be done safely.

    The point is the byte shape: a JSON round-trip reflows every array in the
    file, which turns a config nobody touched into text no template contains,
    and `--force` then reports it KEEP (edited) and never restores what this
    function pruned or raised. Splicing the one line leaves the rest of the file
    as the template shipped it, and the result is re-parsed before it is trusted.
    """
    pattern = re.compile(r'^\s*"' + re.escape(key) + r'"\s*:\s*\d+\s*,?\s*$')
    lines = text.split("\n")
    idx = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
    if idx is None:
        return None
    had_comma = lines[idx].rstrip().endswith(",")
    if value is None:
        del lines[idx]
        if not had_comma:
            for j in range(idx - 1, -1, -1):
                if not lines[j].strip():
                    continue
                if lines[j].rstrip().endswith(","):
                    lines[j] = lines[j].rstrip()[:-1]
                break
    else:
        indent = lines[idx][:len(lines[idx]) - len(lines[idx].lstrip())]
        lines[idx] = f'{indent}"{key}": {value}' + ("," if had_comma else "")
    spliced = "\n".join(lines)
    try:
        parsed = json.loads(spliced)
    except json.JSONDecodeError:
        return None
    budgets = parsed.get("budgets")
    budgets = budgets if isinstance(budgets, dict) else {}
    if value is None:
        return None if key in budgets else spliced
    return spliced if budgets.get(key) == value else None


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
    _write_text(cfg_path, spliced)
    return (f"sync_config.json: dropped AGENTS.md budget (was {removed}) because "
            "--no-agents-block did not create the file")


def _own_agents_budget() -> int:
    """The cap the SHIPPED config sets for the caller's own AGENTS.md text.

    Read from the template rather than from the installed file, so the raise
    below is a derived number that cannot drift when this tool is run twice: the
    alternative — incrementing whatever cap is on disk — walks the budget upwards
    once per install, which is the same unbounded-growth defect N1 is about.
    """
    text = _read_text(TEMPLATES / "sync_config.json")
    if text is None:
        return AGENTS_OWN_BUDGET
    try:
        cap = json.loads(text).get("budgets", {}).get(AGENTS_BUDGET_KEY)
    except (json.JSONDecodeError, AttributeError):
        return AGENTS_OWN_BUDGET
    return cap if isinstance(cap, int) and not isinstance(cap, bool) \
        else AGENTS_OWN_BUDGET


def managed_block_present(root: Path) -> bool:
    agents = root / "AGENTS.md"
    text = _read_text(agents) if agents.is_file() else None
    return bool(text) and bool(_block_spans(text.split("\n"))[0])


def _block_spans(lines: list[str]) -> tuple[list[tuple[int, int]], int]:
    """`([ (begin, end) inclusive ], unmatched BEGIN count)` for `lines`.

    N2: spans come from the marker family, so a drifted `v:` tag, extra internal
    whitespace or trailing spaces still resolve to the same block. Each BEGIN
    takes the first unused END after it; a BEGIN with no END after it is
    unmatched and reported, because appending beside it would add a second live
    copy of the protocol text to a file that already has one.
    """
    begins = [i for i, ln in enumerate(lines) if MANAGED_BEGIN_RE.match(ln)]
    ends = [i for i, ln in enumerate(lines) if MANAGED_END_RE.match(ln)]
    spans: list[tuple[int, int]] = []
    taken: set[int] = set()
    for b in begins:
        e = next((x for x in ends if x > b and x not in taken), None)
        if e is None:
            continue
        taken.add(e)
        spans.append((b, e))
    return spans, len(begins) - len(spans)


def raise_agents_budget_for_block(root: Path) -> list[str]:
    """N1/D27: make the configured cap cover the block this install wrote.

    `sync_verify.py` counts the whole `AGENTS.md`, including the managed block
    the protocol itself appends, against `"AGENTS.md"` in `.ai/sync_config.json`.
    With a constant 65 that meant any pre-existing AGENTS.md of 50+ lines went
    permanently red *because of the install* (58 -> 74 lines), while init's own
    closing line promised green. The cap therefore becomes
    `own-budget + block span` — 81 — which keeps the caller's own 65 lines under
    exactly the same limit and charges the 16 lines to the tool that added them.

    Returns the lines to print; an `ERROR` prefix means the install could not fix
    the config and must not claim success.
    """
    if not managed_block_present(root):
        return []
    own = _own_agents_budget()
    needed = own + BLOCK_APPEND_SPAN
    cfg_path = root / ".ai" / "sync_config.json"
    if not cfg_path.is_file():
        return [f"ERROR (cannot account for the managed block): "
                f".ai/sync_config.json is not installed, so the verifier keeps "
                f"the {own}-line AGENTS.md cap this {BLOCK_APPEND_SPAN}-line "
                "block overruns"]
    text = _read_text(cfg_path)
    if text is None:
        return [f"ERROR (unreadable config, cannot raise the budget): {cfg_path}"]
    try:
        cfg = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"ERROR (unparseable config, cannot raise the budget): "
                f"{cfg_path}: {exc}"]
    budgets = cfg.get("budgets")
    if not isinstance(budgets, dict) or AGENTS_BUDGET_KEY not in budgets:
        return [f'ERROR (no AGENTS.md budget in .ai/sync_config.json): add '
                f'"{AGENTS_BUDGET_KEY}": {needed} so the managed block fits']
    current = budgets[AGENTS_BUDGET_KEY]
    if isinstance(current, int) and current >= needed:
        return [f"sync_config.json: AGENTS.md budget {current} already covers the "
                f"{BLOCK_APPEND_SPAN}-line managed block ({own}-line cap on your "
                "own content)"]
    spliced = _splice_budget_line(text, AGENTS_BUDGET_KEY, needed)
    if spliced is None:
        if not is_template_shaped(text):
            return [f'ERROR (cannot raise the AGENTS.md budget): '
                    f'.ai/sync_config.json has no line-shaped "{AGENTS_BUDGET_KEY}" '
                    f"entry to edit and is not an untouched template; set it to "
                    f"{needed} yourself"]
        cfg["budgets"][AGENTS_BUDGET_KEY] = needed
        spliced = json.dumps(cfg, indent=2) + "\n"
    _write_text(cfg_path, spliced)
    return [f"sync_config.json: AGENTS.md budget {current} -> {needed} lines "
            f"(+{BLOCK_APPEND_SPAN}: the managed block this install added, so your "
            f"own content keeps the {own}-line cap)"]


def warn_agents_over_budget(root: Path) -> list[str]:
    """Name an overrun the raise cannot fix, instead of promising green.

    The budget raise pays for the block, not for the caller's text: an
    `AGENTS.md` already past its own cap still has to verify red. Saying so here
    is what keeps init's step-3 line ("sync_verify.py -> no FAILED line; a named
    [SKIP] is EXPECTED") from being a promise this run cannot meet.
    """
    agents = root / "AGENTS.md"
    cfg_path = root / ".ai" / "sync_config.json"
    if not agents.is_file() or not cfg_path.is_file():
        return []
    text = _read_text(agents)
    cfg_text = _read_text(cfg_path)
    if text is None or cfg_text is None:
        return []
    try:
        cap = json.loads(cfg_text).get("budgets", {}).get(AGENTS_BUDGET_KEY)
    except json.JSONDecodeError:
        return []
    if not isinstance(cap, int):
        return []
    n = len(text.splitlines())
    if n <= cap:
        return []
    return [f"WARNING: AGENTS.md is over budget: {n} lines vs cap {cap}. "
            f"sync_verify.py reports [FAIL] budget AGENTS.md until the file is "
            f"{cap} lines or fewer - trim {n - cap} line(s) of your own rules "
            f"(the managed block accounts for {BLOCK_APPEND_SPAN} of them) or "
            f"raise the cap in .ai/sync_config.json"]


def update_agents_md(root: Path, force: bool) -> str:
    agents = root / "AGENTS.md"
    if not agents.exists():
        return copy_file(TEMPLATES / "AGENTS.md", agents, force)
    # N3: read and write the file's OWN bytes. `read_text` folds every
    # terminator to LF and `write_text` then emits os.linesep, so an installer
    # run on Windows re-emitted the caller's whole file as CRLF (measured: an
    # 8-line LF file came back with 24 CRLF terminators) while every template
    # this tool copies is LF.
    #
    # N4: the decode is guarded. This read used to raise straight out of main(),
    # so a GBK/ANSI AGENTS.md — routine on a cp936 host — aborted the install
    # with a traceback *after* .gitignore had been appended, wrote no CLAUDE.md,
    # and named nothing.
    text, why_not = _read_raw_text(agents)
    if text is None:
        return (f"AGENTS.md: ERROR ({why_not}) - left untouched and the managed "
                "block was not added; everything else in this run stands, so "
                "save the file as UTF-8 and re-run")
    if "Canonical instructions for ALL harnesses" in text:
        # Already the full template — the whole protocol is inline, no block needed
        return "AGENTS.md: already the full template, no managed block added"
    term = _dominant_newline(text)
    lines = text.splitlines(keepends=True)
    spans, orphans = _block_spans(lines)
    if orphans:
        return (f"AGENTS.md: ERROR ({orphans} BEGIN marker with no END marker) - "
                "left the file untouched; repair the marker and re-run. Appending "
                "here would put a second managed block in the same file.")
    block = [ln + term for ln in MANAGED_BLOCK.split("\n")]
    if spans:
        rebuilt = lines[:spans[0][0]] + block
        cursor = spans[0][1] + 1
        for begin, end in spans[1:]:
            rebuilt.extend(lines[cursor:begin])
            cursor = end + 1
        rebuilt.extend(lines[cursor:])
        _write_bytes_text(agents, "".join(rebuilt))
        message = "AGENTS.md: replaced managed block in place"
        if lines[spans[0][0]:spans[0][1] + 1] != block:
            message += (" - drifted markers and any text inside them were "
                        "normalised to the shipped block")
        extra = len(spans) - 1
        if extra:
            message += f" ({extra} duplicate block(s) collapsed)"
        return message
    tail = "" if not text or text.endswith(("\n", "\r\n")) else term
    _write_bytes_text(agents,
                      text + tail + term + term + "".join(block))
    return "AGENTS.md: appended managed block"


def write_claude_pointer(root: Path) -> str:
    claude = root / "CLAUDE.md"
    if claude.exists():
        return "CLAUDE.md: exists, untouched (add a pointer to AGENTS.md yourself)"
    claude_text = ("# Claude Code\n\nRead `AGENTS.md` at the project root — it is "
                   "the canonical instruction file for ALL harnesses. This file is "
                   "only a pointer so Claude Code auto-loads it.\n")
    _write_text(claude, claude_text)
    return "CLAUDE.md: wrote pointer to AGENTS.md"


# ---------------------------------------------------------------------------
# spec §8: `--migrate` - records what v2.0 never recorded
# ---------------------------------------------------------------------------
#
# An existing v2.0 install cannot run ANY of the 1a/1b scripts until it is
# migrated, because it has no `ai_common.py` to import; and the governance layer
# has nothing to read until the authorization records have a home on disk. This
# is the one command that closes the wave boundary, so the rules are strict
# about the direction of failure: refuse BEFORE writing, never guess, never
# clobber something a hand wrote, and name what a `git revert` cannot undo.

MIGRATION_REL = ".ai/protocol/MIGRATION.json"
MIGRATION_JOURNAL_REL = ".ai/protocol/MIGRATION.md"
CONFIG_REL = ".ai/sync_config.json"
ROLE_POLICY_REL = ".ai/state/ROLE_POLICY.md"
WRITER_LOCK_REL = ".ai/runtime/WRITER_LOCK.json"
MIGRATION_AGENT = "init-sync-migrate"
MIGRATION_COMMIT_TAG = "cross-harness-sync-migrate"

# The sentinel `sync_verify.py` reads as `SKIP(no-window: NO_HISTORY)`, never as
# a pass: `"NO_HISTORY"` is a claim that the window has no anchor, so it must not
# be confused with `""` (nobody has migrated this tree) or with a real commit.
# It is `ai_common.NO_HISTORY`, imported above, because the predicate that accepts
# it — `ai_common.window_is_valid` — is now shared with the reader (final review
# I-1) and a locally re-bound copy is how a shared constant stops being shared.

# SHA-256 of every script the released v2.0.0 installed, taken from the git blob
# at `e692e73` ("Initial release: cross-harness-sync v2.0.0") - i.e. the bytes a
# real v2.0 install has in HEAD, not the working-tree copy a `core.autocrlf` or a
# `.gitattributes` rule may have rewritten. `ai_common.py` has no entry because
# v2.0 never shipped one: its absence is an ADD, not a divergence.
#
# The table is deliberately tiny and closed: it answers one question - "is the
# committed copy exactly what we released?" - and where it cannot answer,
# `--migrate` writes a `.new` sidecar instead of clobbering. `tests/test_migrate.py`
# re-derives these digests from the commit itself, so a wrong entry goes red.
V20_SCRIPT_SHA256 = {
    ".ai/scripts/checkpoint.py":
        "5b73b8a4fde6de315906632ce652e6987713ee2457b650ff691835f64afa4aa3",
    ".ai/scripts/sync_verify.py":
        "1c7beedf4d8127e4fd5a9d5827d855d885b31c9779cf8b2de76498245058b757",
}

# The commit refuses-and-writes-nothing cases all exit this way, so a script
# around `--migrate` can tell "refused" (2) from "half-migrated, look" (1).
MIGRATE_REFUSED = 2
MIGRATE_INCOMPLETE = 1


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _refuse(why: str, extra: list | None = None) -> int:
    """One refusal shape: say why, say nothing was written, exit 2."""
    print(f"MIGRATE REFUSED: {why}")
    for line in extra or []:
        print(f"  {line}")
    print("Nothing was written: this run made no change to the install, the "
          "index, the config, or the history.")
    return MIGRATE_REFUSED


def _one_line(text: str, limit: int = 240) -> str:
    """A subprocess's multi-line complaint as one readable line."""
    return " | ".join(ln.strip() for ln in text.splitlines() if ln.strip())[:limit]


def _not_a_repository_said(res) -> bool:
    """True ONLY for git's own "outside any repository" answer.

    The distinction is the whole point: every other non-zero exit is git
    refusing to answer (dubious ownership, an `index.lock` left by a crashed
    process, an unreadable object store, a timeout), and a question the
    migration could not ask has no clean answer. Lumping the two together let a
    repository with a transient lock be stamped `NO_HISTORY` — a value that then
    travels to every other machine in `sync_config.json`.
    """
    if res.timed_out or res.rc == 0:
        return False
    err = res.err().lower()
    return ("not a git repository" in err
            or "repository not found" in err
            or "cannot find repository" in err)


def _no_commits_said(res) -> bool:
    """True only for git's own "HEAD names no commit" answer (rc 1, a revision
    problem). A repository-level fatal is rc 128 and belongs to the guard above.
    """
    if res.timed_out or res.rc != 1:
        return False
    err = res.err().lower()
    return ("needed a single revision" in err
            or "unknown revision" in err
            or "does not have any commits" in err
            or "ambiguous argument 'head'" in err)


def git_head_state(root: Path) -> tuple:
    """`('head', sha40)` / `('no-repo', detail)` / `('unborn', detail)` /
    `('detached', sha40)` / `('bogus', detail)` / `('probe-refused', detail)`.

    The states are separate because spec §8 sends them different ways: unborn
    and detached REFUSE (a migration commit would land on no branch at all, or
    on a detached one), while a tree git positively confirms is outside any
    repository still gets its records - with `NO_HISTORY` as the window anchor,
    which is a named skip rather than a claim. `bogus` is the fail-open guard: a
    HEAD that does not resolve to exactly 40 lowercase hex is not a commit id,
    and storing whatever came back would make `git log <window>..HEAD` a coin
    flip.

    `probe-refused` is fix round 1's split, and it is deliberately NOT in the
    no-repository bucket: git not being on PATH, a refused probe (dubious
    ownership), a lock contention or a timeout all mean "this tree's history is
    unknown". Reading that as "no repository" skipped the writer lock and
    permanently stamped `NO_HISTORY` into a repo that has history, which §6
    already refuses to do for dubious ownership ("its own actionable error").
    Here it is a named halt of its own.
    """
    if not git_available():
        return "probe-refused", ("`git` is not on PATH, so this tree's history "
                                 "cannot be read at all (install git, or run "
                                 "this from a shell that has it on PATH)")
    probe = run_git(root, ["rev-parse", "--is-inside-work-tree"], timeout=15)
    answer = probe.out().strip().lower()
    if probe.ok and answer == "true":
        pass                                   # a work tree: ask about HEAD
    elif probe.ok and answer == "false":
        return "probe-refused", ("`git rev-parse --is-inside-work-tree` answered "
                                 "false: this is a git directory, not a working "
                                 "tree, so nothing here can be committed from")
    elif _not_a_repository_said(probe):
        return "no-repo", ("git reports no repository around this directory "
                           "(confirmed, not assumed)")
    else:
        return "probe-refused", (
            f"`git rev-parse --is-inside-work-tree` exited {probe.rc} instead of "
            f"answering: {_one_line(probe.err() or probe.out())}")
    head = run_git(root, ["rev-parse", "--verify", "HEAD"], timeout=15)
    if not head.ok:
        if _no_commits_said(head):
            return "unborn", "`git rev-parse --verify HEAD` found no commit"
        return "probe-refused", (
            f"`git rev-parse --verify HEAD` exited {head.rc} instead of "
            f"answering: {_one_line(head.err() or head.out())}")
    sha = head.out().strip()
    if not re.fullmatch(r"[0-9a-f]{%d}" % SHA_HEX_LEN, sha):
        return "bogus", f"HEAD resolved to {sha!r}, not a {SHA_HEX_LEN}-hex id"
    branch = run_git(root, ["symbolic-ref", "--quiet", "HEAD"], timeout=15)
    if branch.ok:
        return "head", sha
    if branch.timed_out or branch.rc != 1:
        # rc 1 is "HEAD is not a symbolic ref" — the detached answer. Anything
        # else (rc 128, a failed launch) is git declining to say.
        return "probe-refused", (
            f"`git symbolic-ref --quiet HEAD` exited {branch.rc} instead of "
            f"answering: {_one_line(branch.err() or branch.out())}")
    return "detached", sha


def _nul_lines(res) -> list:
    """A `-z` git listing as paths: split on NUL, never `splitlines()` (§6)."""
    return [part.decode("utf-8", "surrogateescape")
            for part in res.stdout.split(b"\0") if part]


def _in_a_work_tree(root: Path) -> tuple:
    """`(yes, '')` / `(no, '')` / `(unknown, why)` for "is anything tracked here".

    Shared by the two guards below so they cannot disagree about which question
    they are answering.
    """
    probe = run_git(root, ["rev-parse", "--is-inside-work-tree"], timeout=15)
    if probe.ok and probe.out().strip().lower() == "true":
        return True, ""
    if _not_a_repository_said(probe):
        return False, ""
    return None, (f"`git rev-parse --is-inside-work-tree` exited {probe.rc}: "
                  f"{_one_line(probe.err() or probe.out())}")


def dirty_tracked_scripts(root: Path) -> tuple:
    """`(paths, why_unknown)` for tracked files under `.ai/scripts/` that are
    edited or deleted in the worktree; `paths is None` means git could not answer.

    `git ls-files -m/-d` is asked, not `git status`: the question is exactly
    "tracked and modified", and an untracked install (everything `??`) must not
    read as a dirty one - that would refuse every tree that has not committed
    yet, which is the common case for a first `--migrate`.

    Fix round 1: a FAILED probe no longer returns `[]`. `[]` means "checked, and
    nothing is dirty"; a refused `ls-files` (an `index.lock` contention, a
    dubious-ownership halt, a timeout) is not evidence of anything, and the
    files it was asking about are exactly the ones this migration rewrites.
    """
    inside, why = _in_a_work_tree(root)
    if inside is None:
        return None, why
    if not inside:
        return [], ""                      # confirmed: nothing here is tracked
    out = []
    for flag in ("-m", "-d"):
        res = run_git(root, ["ls-files", flag, "-z", "--", ".ai/scripts"],
                      timeout=15)
        if not res.ok:
            return None, (f"`git ls-files {flag} -- .ai/scripts` exited "
                          f"{res.rc}: {_one_line(res.err() or res.out())}")
        out.extend(_nul_lines(res))
    return sorted(set(out)), ""


def staged_outside_ai(root: Path) -> tuple:
    """`(paths, why_unknown)` for index entries outside `.ai/` - the commit
    could not stay scoped with them. `paths is None` means git could not answer.

    Fix round 1: same split as `dirty_tracked_scripts()` — and this one is read
    AGAIN immediately before `git commit`, because the check that mattered was
    running after it: a bad index reaching history at rc 0 cannot be undone by
    noticing afterwards.
    """
    inside, why = _in_a_work_tree(root)
    if inside is None:
        return None, why
    if not inside:
        return [], ""
    res = run_git(root, ["diff", "--cached", "--name-only", "-z"], timeout=15)
    if not res.ok:
        return None, (f"`git diff --cached --name-only` exited {res.rc}: "
                      f"{_one_line(res.err() or res.out())}")
    return [p for p in _nul_lines(res) if not p.startswith(".ai/")], ""


def head_blob(root: Path, rel: str):
    """The committed bytes at HEAD, or None when HEAD has no such path."""
    res = run_git(root, ["show", f"HEAD:{rel}"], timeout=15)
    return res.stdout if res.ok else None


def script_plan(root: Path) -> list:
    """`[(rel, action, detail)]` for every script, decided BEFORE anything writes.

    action is `add` (absent), `current` (bytes already match what we ship),
    `refresh` (HEAD holds the released v2.0 blob: overwriting is the upgrade),
    `sidecar` (diverged or untracked: hand-edited and an unknown version cannot
    be told apart, so the new bytes go to `<name>.new`), or `unknown-history`
    (a git query that could not be answered - treated as `sidecar`, because the
    fail-open direction here is the one that can destroy work).
    """
    plan = []
    for name, rel in SCRIPT_MAP:
        dst = root / rel
        try:
            shipped = (SKILL_DIR / "scripts" / name).read_bytes()
        except OSError:
            plan.append((rel, "missing-source", f"scripts/{name} is unreadable"))
            continue
        shipped_digest = hashlib.sha256(shipped).hexdigest()
        if not dst.exists():
            plan.append((rel, "add", ""))
            continue
        try:
            work = dst.read_bytes()
        except OSError as exc:
            plan.append((rel, "unreadable", f"cannot read ({exc.__class__.__name__})"))
            continue
        if hashlib.sha256(work).hexdigest() == shipped_digest:
            plan.append((rel, "current", ""))
            continue
        if not is_git_repo(root):
            # Spec §8: an untracked file counts as MODIFIED, because byte
            # comparison against a released version is not evidence here.
            plan.append((rel, "sidecar",
                         "no repository to read HEAD from, so an in-place "
                         "customisation cannot be ruled out"))
            continue
        blob = head_blob(root, rel)
        if blob is None:
            plan.append((rel, "sidecar",
                         "not in HEAD, so a hand edit and an older shipped "
                         "version cannot be told apart"))
            continue
        head_digest = hashlib.sha256(blob).hexdigest()
        if head_digest == shipped_digest:
            # Identical in HEAD and in the worktree apart from what this run is
            # about to write: `dirty_tracked_scripts()` already refused the
            # worktree-modified case, so this is a stale check. Keep it honest.
            plan.append((rel, "sidecar",
                         "HEAD matches the shipped copy but the worktree does "
                         "not: an unstaged edit git cannot recover"))
            continue
        if V20_SCRIPT_SHA256.get(rel) == head_digest:
            plan.append((rel, "refresh", "HEAD is the released v2.0.0 blob"))
            continue
        plan.append((rel, "sidecar",
                     "HEAD's blob is neither the released v2.0.0 copy nor the "
                     "shipped one: a hand edit and an unknown version cannot be "
                     "told apart"))
    return plan


def effective_authorizations_dir(cfg: dict, requested: str | None) -> str:
    """CLI flag > config > canonical default - never a guess at a location.

    Spec §8: a wrong guess fabricates an authoritative record source, so the
    precedence is fixed and every level of it is named in the printout.
    """
    if requested:
        return requested.rstrip("/\\")
    declared = str(cfg.get("authorizations_dir", "") or "").strip()
    if declared:
        return declared.rstrip("/\\")
    return AUTHORIZATIONS_INDEX_REL.rsplit("/", 1)[0]


def config_edits(cfg: dict, adir_rel: str, window: str, role_sha: str,
                 dir_explicit: bool = False) -> list:
    """The `[(path, value_json)]` edits this migration owes the config.

    Only what is ABSENT or deliberately empty is written: a `window_start_commit`
    that already names a commit is not moved (that would rewind or forge the
    coverage window), and a `role_policy_sha256` someone set to a value that
    disagrees with the file is left for a human to reconcile.
    """
    edits = []
    if "protected_paths" not in cfg:
        edits.append((("protected_paths",), "[]"))
    if "protected_paths_case" not in cfg:
        edits.append((("protected_paths_case",), '"case-sensitive"'))
    declared = str(cfg.get("authorizations_dir", "") or "").strip()
    if not declared:
        edits.append((("authorizations_dir",),
                      json.dumps(adir_rel, ensure_ascii=False)))
    elif dir_explicit and declared != adir_rel:
        # An explicit `--authorizations-dir` is the user RETARGETING the record
        # source, and the verifier reads that key - writing the index somewhere
        # the config does not name would put the records out of sight.
        edits.append((("authorizations_dir",),
                      json.dumps(adir_rel, ensure_ascii=False)))
    pinned = cfg.get("role_policy_sha256")
    if "role_policy_sha256" not in cfg:
        edits.append((("role_policy_sha256",),
                      json.dumps(role_sha, ensure_ascii=False)))
    elif pinned == "" and role_sha:
        edits.append((("role_policy_sha256",),
                      json.dumps(role_sha, ensure_ascii=False)))
    gov = cfg.get("governance")
    if not isinstance(gov, dict):
        edits.append((("governance",), json.dumps({"window_start_commit":
                                                   window})))
    elif not str(gov.get("window_start_commit", "") or "").strip():
        edits.append((("governance", "window_start_commit"),
                      json.dumps(window, ensure_ascii=False)))
    return edits


def _acquire_writer_lock(root: Path) -> tuple:
    """Take the pen THROUGH the installed `checkpoint.py`, not by copying its
    record format: D23's disease was three scripts each writing the same file.

    Returns `(ok, detail)`. A refusal here writes nothing at all, which is the
    point - `--migrate` mutates tracked state, so it is exactly the command the
    advisory lock exists for.
    """
    cp = root / ".ai/scripts/checkpoint.py"
    if not cp.is_file():
        return False, (".ai/scripts/checkpoint.py is missing, so the writer-lock "
                       "contract cannot be invoked. Run plain `init_sync.py` "
                       "first (a fresh install), not --migrate.")
    res = run_argv(root, [sys.executable, str(cp), "--lock",
                          "--agent", MIGRATION_AGENT, "--reason",
                          f"cross-harness-sync --migrate to {PROTOCOL_VERSION}"],
                   timeout=120)
    if res.timed_out:
        return False, "`checkpoint.py --lock` timed out; no lock was taken"
    detail = (res.out() + res.err()).strip().replace("\n", " | ")
    if res.rc != 0:
        return False, f"`checkpoint.py --lock` exited {res.rc}: {detail}"
    return True, detail


def _migration_commit(root: Path, installed: str) -> tuple:
    """Commit `.ai/**` and nothing else. `(ok, detail)`; a failed commit is a
    NAMED outcome, never an absent one.

    Two things make "and nothing else" true rather than hoped for:

    1. the staged set is verified BEFORE the commit. The old order ran `git
       show --name-only` afterwards and reported a bad commit having already
       created it - a fact with an rc of 0 and a history entry behind it.
    2. the commit is PATH-SCOPED (`git commit ... -- .ai`), so git cannot fold an
       index entry from outside `.ai/` into it even if a guard failed to see it.
       The scope excludes the lock record by pathspec, because a path-scoped
       commit takes the WORKING-TREE content of the named paths and
       `.gitignore` deliberately un-ignores `WRITER_LOCK.json` - `git reset`
       alone would not have kept it out.
    """
    add = run_git(root, ["add", "-A", "--", ".ai"], timeout=120)
    if not add.ok:
        return False, (f"`git add -- .ai` exited {add.rc}: "
                       f"{_one_line(add.err() or add.out())}")
    run_git(root, ["reset", "-q", "--", WRITER_LOCK_REL], timeout=60)
    outside, why_unknown = staged_outside_ai(root)
    if outside is None:
        return False, (f"the staged set could not be verified before committing "
                       f"({why_unknown}). A guard that could not run is not a "
                       "clean index, and this commit cannot be un-made.")
    if outside:
        return False, (f"the index holds {len(outside)} change(s) outside .ai/ "
                       f"before the commit: {_one_line(', '.join(outside))}. "
                       "No commit was created.")
    message = (f"chore({MIGRATION_COMMIT_TAG}): v{installed} -> "
               f"v{PROTOCOL_VERSION} governance records\n\n"
               f"Written by `init_sync.py --migrate`: the authorization index, "
               f"the config's governance namespaces, and "
               f"{MIGRATION_JOURNAL_REL}.\n"
               f"Revert this commit to undo the .ai/ part; "
               f"{MIGRATION_JOURNAL_REL} names what a revert cannot undo.")
    commit = run_git(root, ["commit", "-q", "-m", message, "--", ".ai",
                            ":(exclude)" + WRITER_LOCK_REL], timeout=120)
    if commit.ok:
        listing = run_git(root, ["show", "--name-only", "--format="],
                          timeout=60)
        if not listing.ok:
            # Final review M-2: this ignored `listing.ok`, so a git error here
            # yielded an empty file list, printed `0 path(s) committed`, and —
            # because the containment recheck below is driven by that same list —
            # silently skipped the recheck. A commit DID land (the staged set was
            # verified before it, and the commit is path-scoped to `.ai/`), so
            # reporting failure would be its own lie; what must not happen is
            # reporting an unqualified success with the recheck unseen.
            return True, (f"committed; post-commit listing unavailable (rc "
                          f"{listing.rc}), so the containment recheck did not "
                          f"run: {_one_line(listing.err() or listing.out())}")
        files = [ln.strip() for ln in listing.out().splitlines() if ln.strip()]
        outside = [f for f in files
                   if not f.startswith(".ai/") or f == WRITER_LOCK_REL]
        if outside:
            return False, (f"the commit was created but it reaches outside "
                           f".ai/: {', '.join(outside)}")
        return True, f"{len(files)} path(s) committed"
    out = (commit.out() + commit.err()).strip().replace("\n", " | ")
    if "nothing to commit" in out:
        return True, "nothing to commit (this run wrote no tracked change)"
    return False, f"`git commit` exited {commit.rc}: {out[:200]}"


def _journal(started: str, completed: str, installed: str, window: str,
             window_how: str, adir_rel: str, touched: list,
             not_reversible: list) -> str:
    lines = [
        f"# Migration journal - cross-harness-sync v{installed} -> "
        f"v{PROTOCOL_VERSION}",
        "",
        f"- started: {started}",
        f"- completed: {completed}",
        f"- window anchor (`governance.window_start_commit`): `{window}` - "
        f"{window_how}",
        f"- authorization records: `{adir_rel}`",
        "- record: `.ai/protocol/MIGRATION.json`",
        "",
        "## Files this run wrote",
        "",
    ]
    lines += [f"- `{rel}`" for rel in touched] or ["- (none)"]
    lines += ["", "## NOT reversible by reverting the migration commit", ""]
    lines += (not_reversible or ["- (nothing this run: every change it made is "
                                 "inside the commit, so a revert undoes all of "
                                 "it)"])
    lines += ["", "## Known unsolvable, documented rather than worked around",
              "",
              "- Customization detection needs history: an untracked "
              "`.ai/scripts/`, or a shallow clone whose HEAD blob is not the "
              "released copy, can only be reported as 'cannot tell', and the "
              "answer taken is the fail-safe one (a `.new` sidecar).",
              "- Two machines migrating the same install conflict in "
              "`.gitignore`, `AGENTS.md`, `VERSION` and `sync_config.json`. "
              "The lock that would serialise them is itself a tracked file, so "
              "it cannot arbitrate across machines; `--ff-only` and no "
              "force-push mean the loser rebases by hand, and re-running "
              "`--migrate` there verifies instead of re-migrating.",
              "- Hook command strings in `.claude/settings.json` live outside "
              "`.ai/` and are invisible to this migration.",
              "- `AGENTS.md` is NOT refreshed by `--migrate` (it is outside "
              "`.ai/`, so the commit could not stay scoped to `.ai/**`). Run "
              "plain `init_sync.py --force` for the managed block.",
              ""]
    return "\n".join(lines)


def verify_migration(root: Path) -> list:
    """The idempotency check: what `--migrate` promised, re-measured on disk.

    A re-run that only reads `MIGRATION.json` would report success over a tree
    that has since LOST the index - the same `rc == 0`-is-not-evidence class
    this wave exists to end - so every item is read from the file it names.
    """
    out = []
    text, why = _read_raw_text(root / MIGRATION_REL)
    if text is None:
        return [("FAIL", MIGRATION_REL, why or "unreadable")]
    try:
        record = json.loads(text)
    except ValueError as exc:
        return [("FAIL", MIGRATION_REL, f"does not parse: {exc}")]
    ok_to = record.get("to") == PROTOCOL_VERSION
    out.append(("PASS" if ok_to else "FAIL", "migration record `to`",
                f"{record.get('to')!r} vs {PROTOCOL_VERSION!r}"))
    stamp = (_read_text(root / ".ai/protocol/VERSION") or "").strip()
    out.append(("PASS" if stamp == PROTOCOL_VERSION else "FAIL", "protocol stamp",
                f"{stamp or 'missing'!r}"))
    cfg_text, cfg_why = _read_raw_text(root / CONFIG_REL)
    if cfg_text is None:
        out.append(("FAIL", CONFIG_REL, cfg_why or "unreadable"))
        return out
    try:
        cfg = json.loads(cfg_text)
    except ValueError as exc:
        out.append(("FAIL", CONFIG_REL, f"does not parse: {exc}"))
        return out
    gov = cfg.get("governance") if isinstance(cfg.get("governance"), dict) else {}
    window = str(gov.get("window_start_commit", "") or "")
    out.append((("PASS" if window_is_valid(window) else "FAIL"),
                "window anchor",
                window if window_is_valid(window) else
                f"{window or 'unset'!r} is neither a {SHA_HEX_LEN}-lowercase-hex "
                f"commit id nor the exact {NO_HISTORY} sentinel, so it cannot be "
                "a completed migration's anchor"))
    rec_warns = record.get("warnings")
    if isinstance(rec_warns, list) and rec_warns:
        out.append(("WARN", "migration warnings",
                    f"{len(rec_warns)} recorded in {MIGRATION_REL}: "
                    + " ; ".join(str(w) for w in rec_warns)[:300]))
    adir = effective_authorizations_dir(cfg, None)
    index = root / Path(adir) / "INDEX.md"
    out.append((("PASS" if index.is_file() and index.stat().st_size else "FAIL"),
                "authorization index", index.relative_to(root).as_posix()))
    pinned = str(cfg.get("role_policy_sha256", "") or "")
    policy = root / ROLE_POLICY_REL
    if not pinned:
        out.append(("WARN", "role policy pin",
                    "config pins no digest (the migration writes one; an empty "
                    "value here means it was unpinned since)"))
    elif policy.is_file():
        got = hashlib.sha256(policy.read_bytes()).hexdigest()
        out.append((("PASS" if got == pinned else "FAIL"), "role policy pin",
                    f"digests to {got}" if got == pinned
                    else f"digests to {got}, config pins {pinned}"))
    else:
        out.append(("FAIL", "role policy pin", f"{ROLE_POLICY_REL} is missing"))
    for name, rel in SCRIPT_MAP:
        dst = root / rel
        if not dst.is_file():
            out.append(("FAIL", rel, "missing"))
            continue
        try:
            same = dst.read_bytes() == (SKILL_DIR / "scripts" / name).read_bytes()
        except OSError:
            same = False
        if same:
            continue
        side = dst.parent / (dst.name + ".new")
        if side.is_file():
            out.append(("WARN", rel,
                        "kept as installed, shipped copy at "
                        f"{side.relative_to(root).as_posix()}"))
        else:
            out.append(("FAIL", rel,
                        "neither the shipped copy nor a preserved `.new` "
                        "sidecar"))
    return out


def run_migration(root: Path, args) -> int:
    """`--migrate`: preflight everything that can refuse, THEN write, THEN commit."""
    print(f"Migrating cross-harness-sync in {root} (protocol "
          f"{PROTOCOL_VERSION})\n")

    # --- preflight: nothing below writes a single byte ------------------------
    stamp_path = root / ".ai/protocol/VERSION"
    if not root.joinpath(".ai").is_dir() or not stamp_path.is_file():
        return _refuse("there is no install here to migrate "
                       "(`.ai/protocol/VERSION` is absent). For a new "
                       "repository run `init_sync.py` without --migrate.")
    version_ok, version_detail = check_version_match(root)
    if not version_ok:
        return _refuse(f"the installed protocol refuses this upgrade: "
                       f"{version_detail}")
    installed = (_read_text(stamp_path) or "").strip()

    state, value = git_head_state(root)
    if state == "probe-refused":
        # Its own halt, named: not the no-repository bucket. Stamping the
        # sentinel here would (a) skip the writer lock over a tree that DOES
        # have tracked state and (b) write a permanent "no history" claim into
        # the config every other machine pulls.
        return _refuse("git could not be asked what this tree's HEAD is, so "
                       "this run cannot tell a repository from a plain "
                       "directory - and the two answers send the migration in "
                       "opposite directions (one needs a commit and a writer "
                       "lock, the other is the only case that records a "
                       "history-free window)", [value])
    if state == "unborn":
        return _refuse("this repository has no commits (unborn HEAD), so a "
                       "migration commit has nowhere to land and the coverage "
                       f"window has no anchor. Commit the install first. "
                       f"({value})")
    if state == "detached":
        return _refuse(f"HEAD is detached (at {value[:8]}): the commit would "
                       "belong to no branch and the next machine could not "
                       "receive it. Check out a branch first.")
    if state == "bogus":
        return _refuse(f"HEAD is not a usable commit id: {value}")
    # Only the two states above survive: `head` (a real 40-hex anchor) and
    # `no-repo` (git positively confirming there is no repository), and only the
    # latter may carry the sentinel.
    window = value if state == "head" else NO_HISTORY
    window_how = ("taken from `git rev-parse --verify HEAD` at migration time"
                  if state == "head" else
                  "SKIP(no-history): git confirmed there is no repository here "
                  "to anchor a window on, so the coverage walk reports a named "
                  "skip rather than a pass")

    dirty, dirty_unknown = dirty_tracked_scripts(root)
    if dirty is None:
        return _refuse("git could not answer whether .ai/scripts/ is dirty, and "
                       "that guard is the one standing between this run and "
                       "overwriting an unrecoverable unstaged edit",
                       [dirty_unknown,
                        "A guard that could not run is never 'clean': fix "
                        "whatever made git refuse (dubious ownership, "
                        "`index.lock`, PATH) and re-run."])
    if dirty:
        return _refuse(".ai/scripts/ has edits that are not even staged, and "
                       "migration rewrites those exact files",
                       [f"{rel} (unstaged edit or deletion)" for rel in dirty]
                       + ["Commit or discard them first: this is the one state "
                          "where a migration could destroy work git cannot "
                          "restore."])
    outside, outside_unknown = staged_outside_ai(root)
    if outside is None:
        return _refuse("git could not answer what the index holds, so this run "
                       "cannot promise its commit stays inside .ai/",
                       [outside_unknown,
                        "Nothing was staged or committed: the index is read "
                        "AGAIN immediately before `git commit` for exactly this "
                        "reason."])
    if outside:
        return _refuse("the index already holds changes outside .ai/, and this "
                       "run's commit is scoped to .ai/** only",
                       [f"{rel} (staged)" for rel in outside]
                       + ["Commit or unstage them first - `--migrate` will not "
                          "fold someone else's staged work into a protocol "
                          "migration."])

    cfg_text, cfg_why = _read_raw_text(root / CONFIG_REL)
    if cfg_text is None:
        return _refuse(f"{CONFIG_REL} {cfg_why or 'cannot be read'}")
    try:
        cfg = json.loads(cfg_text)
    except ValueError as exc:
        return _refuse(f"{CONFIG_REL} is not valid JSON, and rewriting it "
                       f"silently would drop the owner's keys: {exc}")
    if not isinstance(cfg, dict):
        return _refuse(f"{CONFIG_REL} is not a JSON object")

    adir_rel = effective_authorizations_dir(cfg, args.authorizations_dir)
    if args.authorizations_dir:
        norm = args.authorizations_dir.replace("\\", "/").strip("/")
        if (not norm or norm.startswith("/") or ":" in norm
                or ".." in Path(norm).parts):
            return _refuse(f"--authorizations-dir must be a repo-relative path "
                           f"inside the checkout, got "
                           f"{args.authorizations_dir!r}")
        adir_rel = norm
    # Degradations collected here are PRINTED and, when this run writes the
    # record, RECORDED in it: `--migrate` exits 0 on a preserved customised
    # script, so an rc-only caller (a hook, a wrapper) has only the file.
    warns: list = []
    if not adir_rel.startswith(".ai/") and args.authorizations_dir:
        print(f"[WARN] {adir_rel} is outside .ai/, so the index this run "
              "creates is NOT in the migration commit (which is scoped to "
              ".ai/**). Commit it yourself.")
        warns.append(f"authorization records: {adir_rel} is outside .ai/, so "
                     "its INDEX.md is not in the migration commit")

    policy_path = root / ROLE_POLICY_REL
    role_sha = ""
    if policy_path.is_file():
        try:
            role_sha = hashlib.sha256(policy_path.read_bytes()).hexdigest()
        except OSError as exc:
            return _refuse(f"{ROLE_POLICY_REL} cannot be read to pin its "
                           f"digest ({exc.__class__.__name__})")
    pinned = str(cfg.get("role_policy_sha256", "") or "")
    if pinned and role_sha and pinned != role_sha:
        print(f"[WARN] role policy pin: {CONFIG_REL} says {pinned}, "
              f"{ROLE_POLICY_REL} digests to {role_sha}. Left as it is - an "
              "intentional edit of the governance document is reconciled by a "
              "human, not overwritten by a migrator.")
        warns.append(f"role policy pin: {CONFIG_REL} still says {pinned} while "
                     f"{ROLE_POLICY_REL} digests to {role_sha}")

    planned = config_edits(cfg, adir_rel, window, role_sha,
                           bool(args.authorizations_dir))
    new_cfg_text = _splice_json(cfg_text, planned) if planned else cfg_text
    if planned and new_cfg_text == cfg_text:
        return _refuse(f"{CONFIG_REL} could not be edited as text without "
                       "reflowing or losing a key")
    plan = script_plan(root)

    # --- idempotency: a re-run VERIFIES and writes nothing -------------------
    if (root / MIGRATION_REL).is_file():
        try:
            prior = json.loads(_read_text(root / MIGRATION_REL) or "")
        except ValueError:
            prior = None
        # What makes a migration "already done" is the pair this run WRITES: the
        # record's `to` and the config's window anchor. It is deliberately NOT
        # `prior["from"] == installed` — after a real 2.0.0 -> 2.1.0 upgrade the
        # stamp is 2.1.0 while the record says `from: 2.0.0`, so that predicate
        # re-migrated on every later run: a rewritten MIGRATION.json, an
        # overwritten journal, and a second `cross-harness-sync-migrate` commit.
        claims_done = (isinstance(prior, dict)
                       and prior.get("to") == PROTOCOL_VERSION)
        prior_gov = cfg.get("governance")
        prior_window = str((prior_gov or {}).get("window_start_commit", "")
                           or "") if isinstance(prior_gov, dict) else ""
        if claims_done and prior_window and not window_is_valid(prior_window):
            return _refuse(
                f"{MIGRATION_REL} records a completed migration to "
                f"{PROTOCOL_VERSION}, but "
                f"{CONFIG_REL}'s governance.window_start_commit is "
                f"{prior_window!r} - not a {SHA_HEX_LEN}-lowercase-hex commit id "
                f"and not the exact {NO_HISTORY} sentinel. A half-written or "
                "edited anchor is not re-migrated over in silence: repair the "
                "config or delete the record deliberately.")
        already = claims_done and window_is_valid(prior_window)
        if already:
            print(f"already migrated "
                  f"({prior.get('from')} -> {PROTOCOL_VERSION}); verifying the "
                  "recorded state and writing nothing.")
            fails = 0
            for kind, name, detail in verify_migration(root):
                print(f"[{kind}] migrate verify {name}: {detail}")
                fails += kind == "FAIL"
            if fails:
                print(f"\nMIGRATE INCOMPLETE: {fails} verification(s) failed "
                      f"after a recorded migration. This run changed nothing; "
                      f"delete {MIGRATION_REL} only if you want to re-run the "
                      "migration from scratch, or restore the named file from "
                      "git.")
                return MIGRATE_INCOMPLETE
            return 0

    # --- the writer lock, taken before the first mutation --------------------
    # Spec §8's reason for the lock is that migration MUTATES TRACKED STATE. A
    # tree git CONFIRMS has no repository has no tracked state and no second
    # machine to contend with - and `checkpoint.py --lock` refuses a
    # non-repository layout by design - so the lock is skipped BY NAME here
    # rather than pretending to be held. A probe that REFUSED is not in this
    # branch: it halted above, under its own name.
    if state == "no-repo":
        print("[SKIP(no-repository)] writer lock: nothing in this install is "
              "tracked, so there is no shared state to acquire a pen over.")
    else:
        ok, lock_detail = _acquire_writer_lock(root)
        if not ok:
            return _refuse("the writer lock could not be acquired, and --migrate "
                           "mutates tracked state", [lock_detail])
        print(f"lock: {lock_detail or 'acquired'}")

    started = _now()
    touched: list = []

    # 1. the config, edited as text.
    if planned:
        _write_bytes_text(root / CONFIG_REL, new_cfg_text)
        touched.append(CONFIG_REL)
        for path, _value in planned:
            print(f"config: {'.'.join(path)} set")
    else:
        print(f"config: {CONFIG_REL} already carries every governance key")

    # 2. the scripts: refresh what is provably ours, sidecar what is not.
    for rel, action, detail in plan:
        name = Path(rel).name
        src = SKILL_DIR / "scripts" / name
        if action == "current":
            print(f"unchanged: {rel} (already the shipped copy)")
            continue
        if action == "add":
            line = copy_file(src, root / rel, True)
            print(line)
            if line.startswith("wrote"):
                touched.append(rel)
            continue
        if action == "refresh":
            line = copy_file(src, root / rel, True)
            print(line)
            if line.startswith("wrote"):
                touched.append(rel)
            print(f"NOTE replaced: {rel} ({detail}, so no hand edit is in the "
                  "line being overwritten) - `git diff HEAD^ " + rel + "` "
                  "names what went")
            continue
        if action in ("sidecar", "unknown-history", "missing-source",
                      "unreadable"):
            if action == "missing-source":
                warns.append(f"{rel}: {detail}")
                print(f"[WARN] {rel}: {detail}")
                continue
            side = (root / rel).parent / (name + ".new")
            try:
                side.write_bytes(src.read_bytes())
            except OSError as exc:
                warns.append(f"{rel}: the shipped copy could not be written "
                             f"even as a sidecar ({exc.__class__.__name__})")
                continue
            touched.append(side.relative_to(root).as_posix())
            side_rel = side.relative_to(root).as_posix()
            warns.append(f"preserved customised script: {rel} was NOT "
                         f"overwritten ({detail}); the shipped copy is at "
                         f"{side_rel} and this install still runs the OLD "
                         "script")
            print(f"[WARN] preserved customised script: {rel} is left exactly "
                  f"as it was ({detail}); the shipped copy is at "
                  f"{side_rel}. This install still "
                  "runs the OLD script - review the sidecar, then replace it "
                  "by hand and re-run `--migrate`.")

    # 3. the protocol stamp, the missing state files, the placeholders.
    _write_text(stamp_path, PROTOCOL_VERSION + "\n")
    touched.append(".ai/protocol/VERSION")
    for rel_src, rel_dst in FILE_MAP:
        if rel_dst == AUTHORIZATIONS_INDEX_REL and adir_rel != \
                AUTHORIZATIONS_INDEX_REL.rsplit("/", 1)[0]:
            continue
        dst = root / rel_dst
        if dst.exists():
            continue
        line = copy_file(TEMPLATES / rel_src, dst, True)
        print(line)
        if line.startswith("wrote"):
            touched.append(rel_dst)

    # 4. the authorization records: the directory, its index, and the template
    #    that now carries a `## Governance` block.
    index_dst = root / Path(adir_rel) / "INDEX.md"
    line = copy_file(TEMPLATES / AUTHORIZATIONS_INDEX_SRC, index_dst, True,
                     protected=True)
    print(line)
    if line.startswith("wrote"):
        touched.append(index_dst.relative_to(root).as_posix())
    elif line.startswith("SKIP") or line.startswith("KEEP"):
        print("index: kept the record index already on disk "
              f"({line.split(':')[0].strip()})")
    auth_dst = root / ".ai/templates/AUTHORIZATION.md"
    line = copy_file(TEMPLATES / "AUTHORIZATION.md", auth_dst, True,
                     protected=True)
    print(line)
    if line.startswith("wrote"):
        touched.append(".ai/templates/AUTHORIZATION.md")

    # 5. the tracked placeholders and the append-only `.gitignore` (D16/D17).
    not_reversible: list = []
    for keep in (".ai/handoff/archive/.gitkeep", ".ai/state/archive/.gitkeep",
                 f"{adir_rel}/.gitkeep", ".ai/runtime/.gitkeep"):
        path = root / Path(keep)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            _write_text(path, "")
            touched.append(path.relative_to(root).as_posix())
            print(f"wrote: {path.relative_to(root).as_posix()}")
    line = update_gitignore(root)
    print(line)
    if "appended" in line:
        not_reversible.append("- `.gitignore` was APPENDED to, and it lives "
                              "outside `.ai/`: a revert of the migration "
                              "commit does not take those lines back. `git diff "
                              ".gitignore` names them.")

    # 6. the journal, then the record that points at it.
    completed = _now()
    for rel, action, detail in plan:
        if action in ("sidecar", "unknown-history"):
            not_reversible.append(
                f"- `{rel}` was NOT overwritten: it is still the customised "
                f"copy ({detail}). Nothing here needs reverting, and nothing "
                "here tells you the customisation still works under the new "
                "protocol.")
    journal = _journal(started, completed, installed, window, window_how,
                       adir_rel, sorted(set(touched)), not_reversible)
    _write_text(root / MIGRATION_JOURNAL_REL, journal)
    touched.append(MIGRATION_JOURNAL_REL)
    record = {"from": installed, "to": PROTOCOL_VERSION, "started": started,
              "completed": completed, "files_touched": sorted(set(touched)),
              "warnings": list(warns), "degraded": bool(warns)}

    def _write_record() -> None:
        """The record, as it stands right now. Re-called after a failed commit:
        `warnings` is the field an rc-only caller reads, and the commit is the
        one degradation that can only be learned by attempting it."""
        record["warnings"] = list(warns)
        record["degraded"] = bool(warns)
        _write_text(root / MIGRATION_REL,
                    json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    _write_record()
    print(f"wrote: {MIGRATION_REL}")
    print(f"wrote: {MIGRATION_JOURNAL_REL}")

    # 7. the commit - `.ai/**` only, never the lock record, and the staged set
    #    re-verified inside `_migration_commit()` BEFORE it runs.
    if state == "no-repo":
        print(f"[SKIP(no-repository)] commit: there is no repository to commit "
              f"{MIGRATION_REL} into; the files are on disk, nothing is in "
              "history.")
    else:
        ok, detail = _migration_commit(root, installed)
        if ok:
            print(f"commit: {MIGRATION_COMMIT_TAG} v{installed} -> "
                  f"v{PROTOCOL_VERSION} ({detail}); "
                  f"{WRITER_LOCK_REL} was deliberately left out")
        else:
            warns.append(f"the migration commit: {detail}")
            print(f"[WARN] commit failed: {detail}")
            # The record and the journal already went to disk and were already
            # staged; they now say what actually happened instead of implying a
            # commit that does not exist. Nothing here is in history, which is
            # itself the named degradation.
            _write_text(root / MIGRATION_JOURNAL_REL, journal + (
                "\n## NAMED FAILURE: this run's commit did not land\n\n"
                f"- {detail}\n"
                "- Everything this migration wrote is on disk and NOT in "
                "history, so no other machine has it and `git revert` has "
                "nothing to undo. Fix whatever git refused (dubious ownership, "
                "`index.lock`, a staged change outside `.ai/`) and re-run "
                "`--migrate`.\n"))
            _write_record()
            print(f"rewrote: {MIGRATION_REL} and {MIGRATION_JOURNAL_REL} to "
                  "record the failed commit (they are not in history either)")

    print(f"\nwindow_start_commit: {window} - {window_how}")
    for line in warns:
        print(f"[WARN] {line}")
    print("\nNext steps:")
    print(f"  1. Read {MIGRATION_JOURNAL_REL} - it names what a revert cannot "
          "undo.")
    print("  2. Fill the index rows and write one .md per stage into "
          f"{adir_rel}/ from .ai/templates/AUTHORIZATION.md.")
    print("  3. python .ai/scripts/sync_verify.py -> a named [SKIP] is "
          "expected; silence is not.")
    print(f"  4. Release the pen when you are done: python "
          f".ai/scripts/checkpoint.py --unlock --agent {MIGRATION_AGENT}")
    return 0


def fill_installer_slots(root: Path) -> list[str]:
    """Resolve the slots `ai_common.INSTALLER_SLOTS` names; report what cannot be.

    Wave 1c C1 and C3: the installer copied `Adopted: <YYYY-MM-DD ...> by <who>`
    and `<NAME> <<EMAIL>>` verbatim, and `required`/`budget` both passed on the
    result — so every install shipped the rule document with its own authorship
    left blank and an instruction file naming no identity. Each value here is
    something git or the clock already knows. Where it does not, the text says so
    and the line is printed, because a blank slot reads as work somebody finished.

    Returns the notes worth showing the operator; a silent install is the bug.
    """
    notes: list[str] = []

    def slot_text(path: Path):
        """`(text, why_not)` — a GBK AGENTS.md is not hypothetical.

        An editor on a cp936 console writes one, and
        `test_a_gbk_agents_md_does_not_crash_the_install` exists because the
        installer once died decoding it. Leaving such a file exactly as found and
        naming it beats both the crash and a silent rewrite that would re-encode
        the whole document. `exists()` is not consulted: it answers False for a
        file this host merely denies, which would read as absent.
        """
        try:
            return path.read_text("utf-8"), ""
        except FileNotFoundError:
            return None, "absent"
        except (OSError, UnicodeDecodeError) as exc:
            return None, type(exc).__name__

    def git_text(*args: str) -> str:
        res = run_git(root, list(args), timeout=15)
        return res.out().strip() if res.ok else ""

    name, email = git_text("config", "user.name"), git_text("config", "user.email")
    if name and email:
        identity = f"{name} <{email}>"
    else:
        identity = "(not detected - set user.name and user.email in this repository)"
        notes.append("commit identity: none is set for this repository, so AGENTS.md "
                     "says so rather than guessing one from the machine or the harness")

    agents = root / "AGENTS.md"
    text, why = slot_text(agents)
    if text is None and why != "absent":
        notes.append(f"AGENTS.md: unreadable ({why}), so its slots stay as found - "
                     "set the commit identity line by hand")
    elif text is not None:
        filled = (text.replace("<PROJECT NAME>", root.name)
                      .replace("<NAME> <<EMAIL>>", identity)
                      .replace("<REMOTE URL>",
                               git_text("remote", "get-url", "origin")
                               or "no remote configured")
                      .replace("<private/public>", "visibility not checked"))
        if filled != text:
            _write_text(agents, filled)

    policy = root / ".ai" / "state" / "ROLE_POLICY.md"
    text, why = slot_text(policy)
    if text is None and why != "absent":
        notes.append(f"ROLE_POLICY.md: unreadable ({why}), so its Adopted line "
                     "stays as found")
    elif text is not None:
        now = datetime.now().astimezone()
        offset = now.strftime("%z")                       # +1000
        filled = (text.replace("<YYYY-MM-DD HH:MM:SS>", now.strftime("%Y-%m-%d %H:%M:%S"))
                      .replace("(<timezone>)", f"({offset[:3]}:{offset[3:]})")
                      .replace("by <who>",
                               f"by `init_sync.py` (cross-harness-sync {PROTOCOL_VERSION})"))
        # The template's own instruction is to delete section 7 when the project
        # has no standing boundaries; the installer cannot invent them, so it
        # does exactly that and says so rather than shipping the instruction as
        # if it were the answer.
        start = filled.find("\n## 7. ")
        if start != -1 and "<List standing " in filled[start:]:
            end = filled.find("\n## ", start + 1)
            filled = filled[:start] + (filled[end:] if end != -1 else "")
            notes.append("role policy section 7 (project boundaries): dropped as "
                         "template text - add it back if this project has standing "
                         "prohibitions only the user can lift")
        if filled != text:
            _write_text(policy, filled)

    for rel, slots in INSTALLER_SLOTS.items():
        body, _ = slot_text(root / rel)
        if body is None:
            continue  # already named above, or never installed at all
        left = [slot for slot in slots if slot in body]
        if left:
            notes.append(f"{rel}: still holds {', '.join(left)} - fill it or the "
                        "`unfilled template slots` check will report it red")
    return notes


def main() -> int:
    # First, before anything is printed: a cp936 console turns the UTF-8 bytes

    # of any non-ASCII text left in them into mojibake, and the install output
    # is the first thing a new user reads (checkpoint.py and sync_verify.py
    # have always done this; init_sync.py was the one entry script that did not).
    protect_stdio()
    parser = argparse.ArgumentParser(
        description="Scaffold cross-harness-sync into a repository")
    parser.add_argument("repo_root", nargs="?", default=".",
                        help="Target repository root (default: cwd)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files that are still "
                             "untouched templates; edited state and config are "
                             "kept (see --clobber). Implied by --scripts-only.")
    parser.add_argument("--clobber", action="store_true",
                        help="Overwrite edited state files too (implies "
                             "--force); commit first, this is the one path "
                             "that can destroy work")
    parser.add_argument("--scripts-only", action="store_true",
                        help="The upgrade path: refresh .ai/scripts/ and "
                             ".ai/protocol/VERSION, create the tracked .gitkeep "
                             "placeholders for the empty protocol directories, "
                             "and append the .gitignore exception that makes "
                             "them addable. Writes no state file, no "
                             "sync_config.json, no template, no AGENTS.md and "
                             "no CLAUDE.md; each script it replaces is named "
                             "with a NOTE replaced: line.")
    parser.add_argument("--no-agents-block", action="store_true",
                        help="Do not touch AGENTS.md")
    parser.add_argument("--migrate", action="store_true",
                        help="The wave-1b upgrade path for an EXISTING install: "
                             "record what v2.0 never recorded (the "
                             "authorization index, the config's governance "
                             "namespaces, the coverage window anchor, the "
                             "role-policy digest) and commit it under .ai/**. "
                             "Refuses and writes nothing on an unborn or "
                             "detached HEAD, an unusable protocol stamp, an "
                             "unparseable config, an unstaged edit under "
                             ".ai/scripts/, an index holding changes outside "
                             ".ai/, a git that cannot be asked (no git on "
                             "PATH, a refused probe, index.lock contention), "
                             "or a held writer lock; a re-run is "
                             "a verifying no-op. Implies neither --force nor "
                             "--clobber, and refuses --clobber.")
    parser.add_argument("--authorizations-dir", default=None, metavar="DIR",
                        help="Where the stage authorization records live "
                             "(repo-relative, inside the checkout). Never "
                             "guessed: with no flag --migrate uses the config's "
                             "authorizations_dir, falling back to "
                             ".ai/state/authorizations.")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory")
        return 2

    if args.migrate:
        if args.clobber:
            print("ERROR: --migrate never overwrites edited state, so it cannot "
                  "be combined with --clobber. Use plain `init_sync.py "
                  "--clobber` for that.")
            return 2
        if args.scripts_only:
            print("ERROR: --migrate and --scripts-only are different upgrade "
                  "paths; --migrate refreshes the scripts itself (and writes "
                  ".new sidecars rather than clobbering a customised one).")
            return 2
        return run_migration(root, args)

    # D22: the version comparison runs BEFORE the banner and before a single
    # write, because the damage a downgrade does is exactly the overwrite this
    # function is being asked to authorise. `--force` and `--clobber` do not
    # reach it: neither means "I want a lower protocol version than the tree I
    # am installing into", and the file they would rewrite is the only record
    # that the higher number was ever there.
    version_ok, version_detail = check_version_match(root)
    if not version_ok:
        print(f"VERSION MISMATCH: {version_detail}")
        return 1

    # --clobber is strictly stronger than --force, so it implies it rather than
    # silently doing nothing when it is the only one passed.
    #
    # V-3: --scripts-only implies it too. Its docstring and its --help both
    # promise "refresh .ai/scripts/ and .ai/protocol/VERSION", and until now the
    # flag needed a SECOND, undocumented flag to do any of that: on an installed
    # repo it printed `SKIP (exists)` three times, wrote no VERSION, and exited 0
    # having changed nothing — the upgrade path wave 1a depends on was a no-op
    # wearing a success code, the same interface/silence class as the "all green"
    # promise. Refreshing is safe as this flag's DEFAULT because what it can
    # reach is the installer's own output: no state file, `sync_config.json`,
    # template, AGENTS.md or CLAUDE.md is opened by it, and the two paths it
    # does write (`.gitignore` and the `.gitkeep` placeholders) only ever gain
    # lines. Note that `.gitignore` IS on that list: an earlier draft of this
    # text claimed the flag created nothing, which stopped being true the moment
    # D16's fix had to reach the upgrade path too.
    force = args.force or args.clobber or args.scripts_only
    # With --clobber nothing is protected; copy_file keeps its original meaning
    # of "overwrite this destination".
    protect = not args.clobber
    rc = 0

    print(f"Scaffolding cross-harness-sync v{PROTOCOL_VERSION} into {root}\n")
    if version_detail != NO_INSTALLED_VERSION:
        # The comparison ran and its answer is this line; `no existing install`
        # stays silent, because the `wrote: .../VERSION` line below says it.
        print(f"VERSION: {version_detail}")
    if args.clobber:
        print("WARNING: --clobber overwrites edited .ai state and config. Commit "
              "the work first (`git add -A && git commit`) so this stays "
              "recoverable.")

    if args.scripts_only:
        print("scripts-only: state files, handoff, sync_config.json and "
              ".ai/templates/ are left exactly as they are. This run refreshes "
              ".ai/scripts/ and .ai/protocol/VERSION, creates the tracked "
              "placeholders for the empty protocol directories, and appends the "
              ".gitignore exception those placeholders need - no file the user "
              "wrote is read, replaced or created.")
    else:
        for rel_src, rel_dst in FILE_MAP:
            line = copy_file(TEMPLATES / rel_src, root / rel_dst, force,
                             protected=protect and rel_dst in PROTECTED_DESTS)
            print(line)
            if line.startswith("ERROR"):
                rc = 1

    # D22/this lane: the stamp as it stands BEFORE anything is written is the
    # second witness for the replacement notice below. Two files can differ from
    # the shipped copy for two reasons -- the install is older, or somebody
    # edited it -- and the only thing here that records which version last wrote
    # these bytes is VERSION itself.
    version = root / ".ai/protocol/VERSION"
    prior_stamp = (_read_text(version) or "").strip()
    for rel_src, rel_dst in SCRIPT_MAP:
        src = SKILL_DIR / "scripts" / rel_src
        dst = root / rel_dst
        try:
            before = dst.read_bytes() if dst.exists() else None
        except OSError:
            before = None
        line = copy_file(src, dst, force)
        print(line)
        if line.startswith("ERROR"):
            rc = 1
            continue
        # Adjudication 4 (finding 5): the behaviour is right -- replacing the
        # installer's own scripts is the only way this flag's promise can be
        # true, and it stays one command, no `--force` needed. The silence was
        # not: a fail-closed tool must not swap bytes it did not author without
        # naming it, and must not call an older version a local edit either.
        if before is not None and before != src.read_bytes():
            if prior_stamp == PROTOCOL_VERSION:
                why = (f"this install's stamp already reads {PROTOCOL_VERSION}, "
                       "so the copy being replaced looks locally modified "
                       "(hand-edited, not an older version)")
            else:
                why = (f"this install's stamp reads {prior_stamp or 'nothing'}, "
                       "not "
                       f"{PROTOCOL_VERSION}, so an older shipped version and a "
                       "local edit cannot be told apart here")
            print(f"NOTE replaced: {rel_dst} (its bytes differed from the "
                  f"shipped copy - {why}) - overwritten; `git diff` after this "
                  "run names every line that went")

    if force or not version.exists():
        version.parent.mkdir(parents=True, exist_ok=True)
        _write_text(version, PROTOCOL_VERSION + "\n")
        print(f"wrote: {version}")
    (root / ".ai/handoff/archive").mkdir(parents=True, exist_ok=True)
    (root / ".ai/state/archive").mkdir(parents=True, exist_ok=True)
    (root / ".ai/runtime").mkdir(parents=True, exist_ok=True)

    # D16: an empty directory is invisible to git, so a fresh clone on a second
    # machine arrives WITHOUT the directories the installer just made — and the
    # first `--handoff` there writes into `.ai/runtime/`, which was never cloned.
    # A zero-byte tracked placeholder per protocol directory is the fix that
    # survives the clone; `git ls-files` is what proves it, not `Path.exists()`,
    # because the question is what the OTHER machine receives. Idempotent by the
    # same `if not exists()` rule the VERSION write above uses: a second scaffold
    # says nothing rather than reporting a file it did not write.
    for keep in (".ai/handoff/archive/.gitkeep", ".ai/state/archive/.gitkeep",
                 ".ai/state/authorizations/.gitkeep", ".ai/runtime/.gitkeep"):
        path = root / keep
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            _write_text(path, "")
            print(f"wrote: {path}")

    # Item 1: this loop ran on EVERY path, `--scripts-only` included, while the
    # `.gitignore` exception that lets `.ai/runtime/.gitkeep` be added at all sat
    # behind `if not args.scripts_only:`. On any tree scaffolded before that
    # exception existed, the upgrade flag therefore wrote a placeholder `git add
    # -A` silently dropped -- D16 surviving on the very path existing users are
    # told to run. The two now share a branch: whatever the placeholder loop
    # creates, `update_gitignore()` has already made addable. It is append-only
    # per D17, and an up-to-date tree just prints `already up to date`.
    line = update_gitignore(root)
    print(line)
    if line.startswith("ERROR"):
        rc = 1

    if not args.scripts_only:
        if args.no_agents_block:
            line = drop_agents_md_budget(root)
            print(line)
            if line.startswith("ERROR"):
                rc = 1
            print("CLAUDE.md: not written (--no-agents-block)")
        else:
            line = update_agents_md(root, force)
            print(line)
            if line.startswith("AGENTS.md: ERROR"):
                rc = 1
            print(write_claude_pointer(root))
        # Lane Z finding 3 (MEDIUM): these two lived inside the `else`, so
        # `--no-agents-block` skipped the cap arithmetic while leaving the
        # managed block in the file. With `--clobber` the config also came back
        # from the template at 65, under a 66-line AGENTS.md: the run exited 0
        # printing the "no FAILED line" promise and verification was red
        # forever at rc 1. The cap has to follow what this run actually left in
        # AGENTS.md, not which flags were set -- and both calls are already
        # no-ops when no managed block is present (`managed_block_present()`
        # for the raise, a missing file/cap for the warning), so running them
        # on the `--no-agents-block` path costs a repo without a block nothing.
        for line in raise_agents_budget_for_block(root):
            print(line)
            if line.startswith("ERROR"):
                rc = 1
        for line in warn_agents_over_budget(root):
            print(line)
        # Wave 1c C1/C3, and deliberately HERE rather than with the state files:
        # AGENTS.md is not written until this block runs, so a fill that wanted
        # its project name, remote and commit identity had nothing to edit yet.
        # The step-1 note at the `if rc:` gate below is what this replaces.
        for note in fill_installer_slots(root):
            print(f"[WARN] {note}")

    # V-4: this block is a promise about what happens NEXT, and it used to print
    # whatever the run had actually achieved — i.e. "should be all green" after
    # an `ERROR (missing source template)` and an exit 1. `rc` is the outcome the
    # run already reported (the same accumulation whose rationale
    # `warn_agents_over_budget()` records at :522), so the gate is that value and
    # not a second bookkeeping mechanism. A failed install names its failure
    # instead of being told to expect green.
    if rc:
        print("\nInstall incomplete: a step above reported ERROR, so this run "
              f"exits {rc} and the Next-steps list is deliberately withheld - "
              "sync_verify.py would be looking at a half-built install.")
        return rc

    print("\nNext steps:")
    print("  1. Fill in the <placeholders> in .ai/SYNC_PROMPT.md and the")
    print("     .ai/state/*.md skeletons - the ones that describe this project's")
    print("     work. The installer's own slots (AGENTS.md's project name, remote")
    print("     and commit identity; ROLE_POLICY.md's Adopted line and its")
    print("     project-boundaries section) are resolved in the run above, and")
    print("     `unfilled template slots` reports any that could not be.")
    print("  2. Declare project-specific checks in .ai/sync_config.json")
    print("     (extra_checks, secret_mirrors).")
    print("  3. python .ai/scripts/sync_verify.py  -> no FAILED line; a named")
    print("     [SKIP] is EXPECTED on a default install, because it registers no")
    print("     project checks. Silence is not the same as clean.")
    print("  4. Commit and push. Never commit secrets, never force-push.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
