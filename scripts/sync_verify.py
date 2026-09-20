#!/usr/bin/env python3
"""One-command sync-system health check (cross-harness-sync skill).

Config-driven; project-specific checks are declared in `.ai/sync_config.json`,
not hardcoded here. Checks, in order:

  0. The config itself is readable, parses, and holds a JSON object. Reading it
     is the precondition of every other line, so failing here stops the run
     instead of falling back to defaults (D4).
  1. Required state files exist and are non-empty
  2. Token budgets (per-file line caps from config "budgets")
  3. Decision log cap (config "decisions_max_active_entries")
  4. Secret files are git-ignored (config "secret_files")
  5. Secret mirror key sets match (config "secret_mirrors": pairs of files
     whose KEY NAMES must be identical, e.g. [".env", ".claude/.env"])
  6. Extra project checks (config "extra_checks": [{"name", "cmd"}];
     PASS iff the command exits 0 — e.g. a freeze verifier)

Exit 0 = all green, 1 = at least one FAIL. Every check prints PASS/FAIL plus
its evidence line. Add new checks to the config, not to chat memory.

Usage:  python .ai/scripts/sync_verify.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# One shared copy of the subprocess / encoding / root-resolution plumbing
# (scripts/ai_common.py), installed next to this file. There is deliberately no
# inline fallback: a second copy of that logic is a second copy of the fail-open
# path it exists to remove, so a layout without it is reported and fatal.
# This message is printed BEFORE protect_stdio() can exist, because
# protect_stdio() lives in the module that is missing on exactly this path, so
# it must stay inside plain ASCII or an ASCII console dies with
# UnicodeEncodeError and rc 1 instead of the rc 2 named below.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from ai_common import RepoError, decode, protect_stdio, resolve_roots, \
        run_argv, run_git
except ImportError:
    print("[FAIL] install layout: ai_common.py is missing from .ai/scripts/ -- "
          "re-run init_sync.py so the shared primitives are copied in")
    sys.exit(2)

# Assigned by main() from resolve_roots(), never by arithmetic on __file__: D19
# was this pair of paths silently pointing one level too high.
AI_DIR: Path | None = None
ROOT: Path | None = None
CONFIG_PATH: Path | None = None

RESULTS: list[tuple[str, bool, str]] = []

DEFAULT_CONFIG = {
    # The four protocol files every install creates. `AGENTS.md` is deliberately
    # NOT here even though `templates/sync_config.json` sets it: its cap is
    # installer-owned (D18 prunes the entry when `--no-agents-block` created no
    # file, D27 raises it by the managed block's line count when it did), so a
    # hardcoded default here would resurrect a budget for a file this install
    # says it does not have — which is D18 again, wearing D3's fix.
    "budgets": {
        ".ai/state/CURRENT.md": 60,
        ".ai/handoff/LATEST.md": 80,
        ".ai/handoff/NEXT_PROMPT.md": 100,
        ".ai/state/DECISIONS_INDEX.md": 110,
    },
    "decisions_max_active_entries": 20,
    "decisions_file": ".ai/state/DECISIONS.md",
    "secret_files": [".env"],
    "secret_mirrors": [],
    "extra_checks": [],
}

REQUIRED_FILES = [
    ".ai/state/CURRENT.md",
    ".ai/state/TASK.md",
    ".ai/state/BLOCKERS.md",
    ".ai/state/DECISIONS.md",
    ".ai/state/DECISIONS_INDEX.md",
    ".ai/handoff/LATEST.md",
    ".ai/protocol/VERSION",
]

# One extra check may legitimately take minutes (a freeze verifier over a large
# tree); it may not hang forever. Task 6 makes the timeout config-driven.
EXTRA_CHECK_TIMEOUT = 600

# Every user config key is merged with the built-in defaults under exactly one
# of three policies, and which one applies is a judgement about the KEY, not
# about the file. Shallow `merged.update(cfg)` got the shape wrong in both
# directions at once (D3):
#
#   deep    — a dict of per-file settings. Keys the user did not name keep
#             their default, so one custom cap cannot un-monitor four files.
#             An entry set to JSON `null` IS honoured as a deletion: dropping
#             one default takes an explicit per-entry opt-out, which is the
#             considered act D3's accident (naming one cap, silently losing
#             four) never was.
#   union   — a governance FLOOR. The defaults are not negotiable: a project
#             can add entries but cannot un-check one with a single config edit,
#             which is precisely how `.env` stopped being a secret under D3.
#   replace — an install SHAPE. A repo that legitimately keeps no decision log
#             or no authorization records must be able to say so, and a union
#             would leave it permanently red for a reason it has already
#             answered. Replace is also the default for every unlisted key.
#
# The wave-1a brief drafted `DEEP_MERGE_KEYS = ("budgets",)` with
# replace-everywhere-else, which contradicts its own `secret_files` test; this
# table is the settled version.
MERGE_DEEP = "deep"
MERGE_UNION = "union"
MERGE_REPLACE = "replace"

MERGE_POLICY = {
    "budgets": MERGE_DEEP,
    "secret_files": MERGE_UNION,
    "required_files": MERGE_REPLACE,
}

# Derived, never re-declared, so the two spellings cannot drift apart.
DEEP_MERGE_KEYS = tuple(k for k, v in MERGE_POLICY.items() if v == MERGE_DEEP)

# A key whose value must keep a container shape for the merge to mean anything.
# `{"secret_files": ".env"}` is the interesting case: it "works" right up until
# `for target in cfg["secret_files"]` iterates the four characters of a string,
# reporting on `.`/`e`/`n`/`v` and never again on `.env`.
KEY_SHAPES = {
    "budgets": dict,
    "secret_files": list,
    "required_files": list,
    "secret_mirrors": list,
    "extra_checks": list,
}

# Keys whose list entries are repo-relative paths.
PATH_LIST_KEYS = ("secret_files", "required_files")


class ConfigError(Exception):
    """The config was missing, unreadable, unparseable, or shaped wrong.

    `str(e)` starts with `unreadable:`, `malformed:` or `not-object:` so a
    caller can tell the reasons apart without re-reading the file.
    """


def record(name: str, ok: bool, evidence: str) -> None:
    RESULTS.append((name, ok, evidence))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {evidence}")


def _check_shape(key: str, val) -> None:
    expected = KEY_SHAPES.get(key)
    if expected is not None and not isinstance(val, expected):
        raise ConfigError(f"malformed: config key {key!r} must hold a "
                          f"{expected.__name__}, got {type(val).__name__}")
    if key in PATH_LIST_KEYS:
        bad = [type(x).__name__ for x in val if not isinstance(x, str)]
        if bad:
            raise ConfigError(f"malformed: config key {key!r} must hold path "
                              f"strings, got {bad}")
    if key == "budgets":
        bad = sorted(str(k) for k, v in val.items()
                     if not (v is None or (isinstance(v, int)
                                           and not isinstance(v, bool))))
        if bad:
            raise ConfigError(f"malformed: budgets values must be line-count "
                              f"integers (or null to drop a default), not "
                              f"under {bad}")


def merge_config(defaults: dict, user: dict) -> dict:
    """Merge a user config over the defaults, one key at a time.

    Policy comes from `MERGE_POLICY`; anything unlisted replaces, which is the
    behaviour a project needs for its own install shape.
    """
    merged = dict(defaults)
    for key, val in user.items():
        _check_shape(key, val)
        policy = MERGE_POLICY.get(key, MERGE_REPLACE)
        if policy == MERGE_DEEP and isinstance(val, dict):
            inner = dict(defaults.get(key, {}))
            for sub_key, sub_val in val.items():
                if sub_val is None:
                    inner.pop(sub_key, None)
                else:
                    inner[sub_key] = sub_val
            merged[key] = inner
        elif policy == MERGE_UNION and isinstance(val, list):
            base = list(defaults.get(key, []))
            merged[key] = base + [item for item in val if item not in base]
        else:
            merged[key] = val
    return merged


def load_config() -> dict:
    """Read `.ai/sync_config.json`, or raise — defaults are never a fallback.

    Falling back to the built-in config while still exiting 0 is how the
    checker certified a repository it had stopped reading (D4).
    """
    try:
        raw = CONFIG_PATH.read_bytes()
    except FileNotFoundError:
        raise ConfigError(f"unreadable: {CONFIG_PATH} is missing")
    except OSError as exc:
        raise ConfigError(f"unreadable: {CONFIG_PATH}: {exc}")
    try:
        cfg = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"malformed: {CONFIG_PATH}: {exc}")
    if not isinstance(cfg, dict):
        raise ConfigError(f"not-object: {CONFIG_PATH} must hold a JSON object")
    return merge_config(DEFAULT_CONFIG, cfg)


def check_required_files() -> None:
    for rel in REQUIRED_FILES:
        p = ROOT / rel
        if not p.exists():
            record(f"required {rel}", False, "missing")
        elif p.stat().st_size == 0:
            record(f"required {rel}", False, "empty")
        else:
            record(f"required {rel}", True, f"{p.stat().st_size} bytes")


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def check_token_budgets(cfg: dict) -> None:
    for rel, cap in cfg["budgets"].items():
        p = ROOT / rel
        if not p.exists():
            record(f"budget {rel}", False, f"missing (cap {cap})")
            continue
        n = line_count(p)
        record(f"budget {rel}", n <= cap, f"{n} lines (cap {cap})")
    dec = ROOT / cfg["decisions_file"]
    if dec.exists():
        n = len(re.findall(r"^## ", dec.read_text(encoding="utf-8"), re.M))
        cap = cfg["decisions_max_active_entries"]
        record("budget DECISIONS active entries", n <= cap, f"{n} entries (cap {cap})")


def check_secrets_ignored(cfg: dict) -> None:
    for target in cfg["secret_files"]:
        res = run_git(ROOT, ["check-ignore", "-v", target], timeout=600)
        record(f"secret ignored: {target}", res.ok,
               decode(res.stdout).strip() or f"git check-ignore rc={res.rc}")


def check_secret_mirrors(cfg: dict) -> None:
    def keys(p: Path) -> set[str]:
        # utf-8-sig, and the BOM stripped again for lines after the first: an
        # editor that saved one side of the mirror with a byte-order mark used
        # to make its first key name disagree with itself (D20).
        return {ln.split("=", 1)[0].strip().lstrip("\ufeff")
                for ln in p.read_text(encoding="utf-8-sig").splitlines()
                if "=" in ln and not ln.lstrip().startswith("#")}

    for pair in cfg["secret_mirrors"]:
        a, b = ROOT / pair[0], ROOT / pair[1]
        if not (a.exists() and b.exists()):
            record(f"secret mirror {pair[0]} vs {pair[1]}", False, "one file missing")
            continue
        ka, kb = keys(a), keys(b)
        record(f"secret mirror {pair[0]} vs {pair[1]}", ka == kb,
               f"{pair[0]}-only={sorted(ka - kb)}, {pair[1]}-only={sorted(kb - ka)}")


def check_extra(cfg: dict) -> None:
    for chk in cfg["extra_checks"]:
        name, cmd = chk["name"], chk["cmd"]
        res = run_argv(ROOT, cmd, timeout=EXTRA_CHECK_TIMEOUT)
        label = " ".join(str(part) for part in cmd)
        tail = (decode(res.stdout) + decode(res.stderr)).strip().splitlines()
        evidence = tail[-1][:160] if tail else "(no output)"
        # A run we could not finish is never a PASS, and naming only `rc=-1`
        # threw the two facts the operator needs away: WHICH command, and
        # whether it timed out or never started. Both degradations below print
        # FAIL, so a hung or unlaunchable check cannot read as green.
        if res.timed_out:
            record(name, False, f"cmd `{label}` TIMEOUT after "
                                f"{EXTRA_CHECK_TIMEOUT}s; {evidence}")
        elif res.rc == -1:
            record(name, False, f"cmd `{label}` could not run: {evidence}")
        else:
            record(name, res.ok, f"cmd `{label}` rc={res.rc}; {evidence}")


def _summarise() -> int:
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed ==")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


def main() -> int:
    global AI_DIR, ROOT, CONFIG_PATH
    protect_stdio()
    try:
        AI_DIR, ROOT = resolve_roots(__file__)
        CONFIG_PATH = AI_DIR / "sync_config.json"
    except RepoError as exc:
        print(f"[FAIL] install layout: {exc}")
        return 2
    print(f"== sync_verify: project root {ROOT} ==")
    try:
        cfg = load_config()
        # as_posix(): the evidence line is read by agents on the other machines
        # too, and `.ai\sync_config.json` is not the path they wrote in config.
        record("config readable", True, CONFIG_PATH.relative_to(ROOT).as_posix())
    except ConfigError as exc:
        # Every other check is driven by this file, so there is nothing to
        # report on a failure — but the summary still has to say 0/1 rather
        # than looking like a run that checked something.
        record("config readable", False, str(exc))
        return _summarise()
    check_required_files()
    check_token_budgets(cfg)
    check_secrets_ignored(cfg)
    check_secret_mirrors(cfg)
    check_extra(cfg)
    return _summarise()


if __name__ == "__main__":
    sys.exit(main())
