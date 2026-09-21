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
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
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
PROTOCOL_VERSION = "2.1.0"

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
    is what keeps init's `should be all green` line from being a lie.
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
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory")
        return 2

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
            for line in raise_agents_budget_for_block(root):
                print(line)
                if line.startswith("ERROR"):
                    rc = 1
            for line in warn_agents_over_budget(root):
                print(line)
            print(write_claude_pointer(root))

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
    print("  1. Fill in every <placeholder> in AGENTS.md, .ai/SYNC_PROMPT.md,")
    print("     and the .ai/state/*.md files.")
    print("  2. Declare project-specific checks in .ai/sync_config.json")
    print("     (extra_checks, secret_mirrors).")
    print("  3. python .ai/scripts/sync_verify.py  -> no FAILED line; a named")
    print("     [SKIP] is EXPECTED on a default install, because it registers no")
    print("     project checks. Silence is not the same as clean.")
    print("  4. Commit and push. Never commit secrets, never force-push.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
