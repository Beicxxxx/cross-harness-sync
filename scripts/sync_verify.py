#!/usr/bin/env python3
"""One-command sync-system health check (cross-harness-sync skill).

Config-driven; project-specific checks are declared in `.ai/sync_config.json`,
not hardcoded here. Checks, in order:

  0. The install layout is one git can describe (linked worktrees and symlinked
     payloads leave a `WRITER_LOCK.json` the other writer never sees, so every
     check below would be about the wrong tree). `ai_common.checkout_layout`.
  1. The config itself is readable, parses, and holds a JSON object. Reading it
     is the precondition of every other line, so failing here stops the run
     instead of falling back to defaults (D4).
  2. Required state files exist and are non-empty (config "required_files",
     default `ai_common.DEFAULT_REQUIRED_FILES`, with `REQUIRED_FILE_FLOOR`
     unioned back in after the merge).
  3. Token budgets (per-file line caps from config "budgets", with
     `BUDGET_FLOOR` naming the files that must carry a cap when present)
  4. Decision log cap (config "decisions_max_active_entries")
  5. Secret files are git-ignored (config "secret_files")
  6. Secret mirror key sets match (config "secret_mirrors": pairs of files
     whose KEY NAMES must be identical, e.g. [".env", ".claude/.env"])
  7. Extra project checks (config "extra_checks": [{"name", "cmd"}];
     PASS iff the command exits 0 — e.g. a freeze verifier)

Exit 0 = every check that ran passed, 1 = at least one FAIL. Every check prints
PASS/FAIL/SKIP plus its evidence line, and the summary prints the passed count,
the total and the skip count on ONE line: a check that could not run is named
and kept out of the passed fraction, never folded into it (spec 4). Add new
checks to the config, not to chat memory.

Usage:  python .ai/scripts/sync_verify.py
"""
from __future__ import annotations

import copy
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
    from ai_common import (DEFAULT_REQUIRED_FILES, RepoError, checkout_layout,
                           decode, protect_stdio, resolve_roots, run_argv,
                           run_git)
except ImportError:
    print("[FAIL] install layout: ai_common.py is missing from .ai/scripts/ -- "
          "re-run init_sync.py so the shared primitives are copied in")
    sys.exit(2)

# Assigned by main() from resolve_roots(), never by arithmetic on __file__: D19
# was this pair of paths silently pointing one level too high.
AI_DIR: Path | None = None
ROOT: Path | None = None
CONFIG_PATH: Path | None = None

# `ok` is TRI-STATE: True passed, False failed, None skipped. The third value
# exists because spec 4 allows a degradation to be named as a WARN or a SKIP
# and never as a PASS, and a SKIP squeezed into a two-valued `record()` becomes
# either a false red (a legal install held at FAIL, which is what lane S1
# documented twice) or a false green (a skip pushed through with `ok=True`,
# landing in the passed numerator). `_summarise()` keeps None out of that
# fraction; see `record()`.
RESULTS: list[tuple[str, "bool | None", str]] = []

DEFAULT_CONFIG = {
    # The one required-file list, imported rather than restated (D23). The
    # shipped template carries the same entries; `test_required_files.py` fails
    # if the two ever disagree.
    "required_files": list(DEFAULT_REQUIRED_FILES),
    # The four protocol files every install creates. `AGENTS.md` is deliberately
    # NOT here even though `templates/sync_config.json` sets it: its cap is
    # installer-owned (D18 prunes the entry when `--no-agents-block` created no
    # file, D27 raises it by the managed block's line count when it did), so a
    # hardcoded default here would resurrect a budget for a file this install
    # says it does not have — which is D18 again, wearing D3's fix. The
    # installer-owned exception is `BUDGET_FLOOR` below, which asks only that a
    # PRESENT AGENTS.md carry a cap or an explicit null.
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

# No `REQUIRED_FILES` here: D23 was this constant disagreeing with two private
# copies in checkpoint.py, so the list lives in config with
# `ai_common.DEFAULT_REQUIRED_FILES` as its single default.

# The governance floor under the required-file list. `required_files` merges by
# REPLACE, which is what lets a repo with no decision log say so — and a replace
# is also one key away from dropping the files nothing else checks. Spec 4 lets a
# check be skipped only after proving necessity elsewhere, and at this HEAD
# nothing else covers these five: `checkpoint.py --validate` omits
# `ROLE_POLICY.md`, and `protocol/VERSION` is in no other list at all. So the
# floor is unioned back in after the merge, and unlike the rest of the key it is
# NOT configurable: config may add requirements and may drop the optional tail
# (DECISIONS, DECISIONS_INDEX, LATEST), nothing more.
REQUIRED_FILE_FLOOR = (
    ".ai/state/CURRENT.md",
    ".ai/state/TASK.md",
    ".ai/state/BLOCKERS.md",
    ".ai/state/ROLE_POLICY.md",
    ".ai/protocol/VERSION",
)

# The name the installer owns (D18 prunes it, D27 raises it), so it can never be
# a code DEFAULT budget — but when the file is PRESENT it must carry a cap or an
# explicit null, which is what `BUDGET_FLOOR` below enforces.
AGENTS_MD_BUDGET_NAME = "AGENTS.md"

# Files whose line cap the protocol always wants enforced while the file is
# there. Derived from the one built-in budget table plus the installer-owned
# name, so a template line deleted by accident (`sync_config.json` is copied,
# not generated) or an upgrade that `--force`-skipped the config cannot leave the
# most-loaded auto-loaded instruction file uncapped and silent.
BUDGET_FLOOR = tuple(DEFAULT_CONFIG["budgets"]) + (AGENTS_MD_BUDGET_NAME,)

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
    "decisions_file": str,
    "decisions_max_active_entries": int,
}

# Keys whose list entries are repo-relative paths.
PATH_LIST_KEYS = ("secret_files", "required_files")


class ConfigError(Exception):
    """The config was missing, unreadable, unparseable, or shaped wrong.

    `str(e)` starts with `unreadable:`, `malformed:` or `not-object:` so a
    caller can tell the reasons apart without re-reading the file.
    """


def record(name: str, ok, evidence: str) -> None:
    """Append and print one verdict: PASS, FAIL, or SKIP.

    `ok` must be True / False / None. Anything else (an int a caller forgot to
    compare, a future `res.ok` wearing a new type) is recorded as FAIL rather
    than trusted: the old `{'PASS' if ok else 'FAIL'}` printed
    `[PASS] … : …` for `ok=1`, which is the fail-open spec 4 exists to end, and
    a bare dict lookup on the value would have raised KeyError out of the
    reporting path itself.
    """
    verdict = ok if ok is None or isinstance(ok, bool) else False
    RESULTS.append((name, verdict, evidence))
    tag = {True: "PASS", False: "FAIL", None: "SKIP"}[verdict]
    print(f"[{tag}] {name}: {evidence}")


def _is_path_str(val) -> bool:
    return isinstance(val, str) and val.strip() != ""


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
    if key == "decisions_max_active_entries" and (
            isinstance(val, bool) or not isinstance(val, int) or val <= 0):
        # `true` is an int in Python and `n <= True` passes at 1 entry, so the
        # JSON boolean has to be named here rather than trusted to `int`.
        raise ConfigError(f"malformed: config key {key!r} must hold a positive "
                          f"integer entry cap, got {val!r}")
    if key == "secret_mirrors":
        for idx, pair in enumerate(val):
            if (not isinstance(pair, list) or len(pair) != 2
                    or not all(_is_path_str(p) for p in pair)):
                raise ConfigError(
                    f"malformed: config key {key!r} entries must be 2-item "
                    f"lists of repo-relative path strings, got {pair!r} at "
                    f"index {idx}")
    if key == "extra_checks":
        for idx, chk in enumerate(val):
            if not isinstance(chk, dict):
                raise ConfigError(
                    f"malformed: config key {key!r} entries must be "
                    f"{{name, cmd}} objects, got {type(chk).__name__} at "
                    f"index {idx}")
            missing = [k for k in ("name", "cmd") if k not in chk]
            if missing:
                raise ConfigError(f"malformed: config key {key!r} entry "
                                  f"{idx} is missing {missing}")
            if not _is_path_str(chk["name"]):
                raise ConfigError(f"malformed: config key {key!r} entry {idx} "
                                  f"'name' must be a non-empty string, got "
                                  f"{chk['name']!r}")
            if (not isinstance(chk["cmd"], list)
                    or not chk["cmd"]
                    or not all(isinstance(p, str) for p in chk["cmd"])):
                raise ConfigError(f"malformed: config key {key!r} entry {idx} "
                                  f"'cmd' must be a non-empty list of strings, "
                                  f"got {chk['cmd']!r}")


def merge_config(defaults: dict, user: dict) -> tuple[dict, set]:
    """Merge a user config over the defaults, one key at a time.

    Policy comes from `MERGE_POLICY`; anything unlisted replaces, which is the
    behaviour a project needs for its own install shape.

    Returns `(merged, nulled)`. `nulled` is the set of budget names the user
    dropped with an explicit JSON `null` — the record of a considered act. It
    has to travel out of the merge because the merged dict cannot tell "no cap"
    from "cap declined" once the key is gone, and every check downstream reads
    only the merged dict (finding: the AGENTS.md opt-out left no trace).

    `defaults` is DEEP-copied, not shallow-copied: an unnamed key used to hand
    back `DEFAULT_CONFIG`'s own containers, so one in-process `.pop()` poisoned
    the module default for every later `load_config()` in the same interpreter.
    """
    merged = copy.deepcopy(defaults)
    nulled: set = set()
    for key, val in user.items():
        _check_shape(key, val)
        policy = MERGE_POLICY.get(key, MERGE_REPLACE)
        if policy == MERGE_DEEP and isinstance(val, dict):
            inner = copy.deepcopy(defaults.get(key, {}))
            for sub_key, sub_val in val.items():
                if sub_val is None:
                    inner.pop(sub_key, None)
                    nulled.add(str(sub_key))
                else:
                    inner[sub_key] = sub_val
            merged[key] = inner
        elif policy == MERGE_UNION and isinstance(val, list):
            base = copy.deepcopy(defaults.get(key, []))
            merged[key] = base + [item for item in val if item not in base]
        else:
            merged[key] = val
    return merged, nulled


def load_config(path: Path | None = None) -> tuple[dict, set]:
    """Read `.ai/sync_config.json`, or raise — defaults are never a fallback.

    Falling back to the built-in config while still exiting 0 is how the
    checker certified a repository it had stopped reading (D4).

    `path` defaults to the module's `CONFIG_PATH` (set by `main()`); callers
    that already know which file they mean pass it, so a test no longer has to
    monkey-assign a global and a stale `None` cannot escape as AttributeError.
    """
    cfg_path = Path(path) if path is not None else CONFIG_PATH
    if cfg_path is None:
        raise ConfigError("unreadable: no config path given and CONFIG_PATH is "
                          "unset (call main() or pass the path)")
    try:
        raw = cfg_path.read_bytes()
    except FileNotFoundError:
        raise ConfigError(f"unreadable: {cfg_path} is missing")
    except OSError as exc:
        raise ConfigError(f"unreadable: {cfg_path}: {exc}")
    try:
        cfg = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"malformed: {cfg_path}: {exc}")
    if not isinstance(cfg, dict):
        raise ConfigError(f"not-object: {cfg_path} must hold a JSON object")
    return merge_config(DEFAULT_CONFIG, cfg)


def check_required_files(required_files: list) -> None:
    # Ruling (lane B3a, on lane S1's finding 1): this one STAYS a FAIL now that
    # `record()` can skip. A config declaring zero required files has removed a
    # check, which is not the same thing as a machine not having a file — the
    # tri-state channel is for the second case. The floor below still runs, so
    # the line is the name of the act, not the only evidence of it.
    declared = list(required_files)
    floor_only = [rel for rel in REQUIRED_FILE_FLOOR if rel not in declared]
    if not declared:
        record("required-file list", False,
               "config declares zero required_files; refusing to certify an "
               "unchecked install (the floor entries were checked anyway)")
    if floor_only:
        record("required-file floor", True,
               f"config listed {len(declared)} entries; floor restored "
               f"{floor_only} — these have no necessity check elsewhere, so "
               f"the key's replace policy does not reach them")
    for rel in declared + floor_only:
        p = ROOT / rel
        if not p.exists():
            record(f"required {rel}", False, "missing")
        elif p.stat().st_size == 0:
            record(f"required {rel}", False, "empty")
        else:
            record(f"required {rel}", True, f"{p.stat().st_size} bytes")


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def check_token_budgets(cfg: dict, nulled: set | None = None) -> None:
    nulled = nulled or set()
    budgets = cfg["budgets"]
    for rel, cap in budgets.items():
        p = ROOT / rel
        if not p.exists():
            record(f"budget {rel}", False, f"missing (cap {cap})")
            continue
        n = line_count(p)
        record(f"budget {rel}", n <= cap, f"{n} lines (cap {cap})")
    # The floor half: a present file with no cap and no explicit null is a
    # silently unchecked file, and `absent so unchecked` is not a shape spec 4
    # allows. An explicit null IS allowed, and gets its own line so the opt-out
    # leaves a trace instead of vanishing from the evidence.
    for rel in BUDGET_FLOOR:
        if rel in budgets:
            continue
        if not (ROOT / rel).exists():
            continue
        if rel in nulled:
            record(f"cap opt-out {rel}", True,
                   f"{rel} is present and its cap was dropped by an explicit "
                   f"null in config (considered act, not D3's accident)")
        else:
            record(f"budget {rel}", False,
                   "file present, no cap in config and no explicit null — "
                   "name the cap or decline it with null")
    dec_rel = cfg["decisions_file"]
    dec = ROOT / dec_rel
    cap = cfg["decisions_max_active_entries"]
    name = "budget DECISIONS active entries"
    # Lane S1's second `# TODO-1a/1b boundary`, now converted (B3a step 1).
    # The SKIP is allowed only because necessity is answered elsewhere for the
    # DEFAULT path: `.ai/state/DECISIONS.md` is in
    # `ai_common.DEFAULT_REQUIRED_FILES` (= `DEFAULT_CONFIG["required_files"]`)
    # and is deliberately outside `REQUIRED_FILE_FLOOR`, so either the install
    # requires it and a missing file is already a named
    # `[FAIL] required .ai/state/DECISIONS.md`, or the config dropped the entry
    # and the install has declared in the one key that owns the question that
    # it keeps no decision log. A RETARGETED path is neither of those: no
    # requirement covers it, so `if dec.exists():` with no else would let one
    # config line un-check the decision cap while every other line stayed
    # green. That shape stays a FAIL (spec 4: silence is the failure, and a
    # skip nobody had to answer for is silence with better manners).
    default_dec = DEFAULT_CONFIG["decisions_file"]
    if not dec.is_file():
        if dec_rel == default_dec:
            record(name, None, f"SKIP(this install declares no decision log at "
                               f"{dec_rel}; the cap of {cap} has nothing to "
                               f"measure, and required_files is where its "
                               f"absence would be named)")
        else:
            record(name, False, f"decisions file not present at {dec_rel} "
                                f"(cap {cap} has nothing to measure)")
        return
    try:
        text = dec.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        record(name, False, f"decisions file {dec_rel} could not be read: "
                            f"{type(exc).__name__}: {exc}")
        return
    n = len(re.findall(r"^## ", text, re.M))
    record(name, n <= cap, f"{n} entries (cap {cap})")


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

    # Every entry is a validated 2-item list of path strings by now: a flat
    # list used to make `pair[0]` index the CHARACTERS of a path and report a
    # mirror check that could PASS on nonsense (D19's class, one key over).
    for pair in cfg["secret_mirrors"]:
        a, b = ROOT / pair[0], ROOT / pair[1]
        if not (a.exists() and b.exists()):
            record(f"secret mirror {pair[0]} vs {pair[1]}", False, "one file missing")
            continue
        ka, kb = keys(a), keys(b)
        record(f"secret mirror {pair[0]} vs {pair[1]}", ka == kb,
               f"{pair[0]}-only={sorted(ka - kb)}, {pair[1]}-only={sorted(kb - ka)}")


def check_extra(cfg: dict) -> None:
    # Entries are validated objects with a string name and a list cmd, so a
    # missing `cmd` is a named `malformed:` line rather than a KeyError.
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
    """One line that says what was PASSED, out of what ran, and what skipped.

    A SKIP is in the denominator and nowhere else: `== 14/15 checks passed ==`
    may never become `== 15/15 ==` because one check could not run, so the
    passed count is `ok is True` alone and the skip count shares the line —
    a number on its own line is a number that gets scrolled past.
    """
    passed = sum(1 for _, ok, _ in RESULTS if ok is True)
    skipped = sum(1 for _, ok, _ in RESULTS if ok is None)
    failed = [n for n, ok, _ in RESULTS if ok is False]
    tail = f", {skipped} skipped" if skipped else ""
    print(f"== {passed}/{len(RESULTS)} checks passed{tail} ==")
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
    kind, layout_detail = checkout_layout(ROOT)
    if kind != "normal":
        # D15: a linked worktree keeps its own on-disk WRITER_LOCK.json and a
        # symlinked payload is not versioned in this tree, so the single-writer
        # rule this install claims may already be broken locally. "normal" is
        # only returned when git answered BOTH probes, so `outside-repo` means
        # "could not determine" — which is a FAIL, not a skip (spec 4). Not
        # `kind == "symlinked"`: the other two kinds falling through would let a
        # wrong-tree run print PASS.
        record("install layout", False,
               f"{kind}: {layout_detail} — every check below would be about a "
               f"tree that is not this checkout (coverage limit: a symlinked "
               f"`.ai` this script was invoked THROUGH is invisible here, "
               f"because resolve_roots() resolved past it)")
        return _summarise()
    try:
        cfg, nulled = load_config()
        # as_posix(): the evidence line is read by agents on the other machines
        # too, and `.ai\sync_config.json` is not the path they wrote in config.
        record("config readable", True, CONFIG_PATH.relative_to(ROOT).as_posix())
    except ConfigError as exc:
        # Every other check is driven by this file, so there is nothing to
        # report on a failure — but the summary still has to say 0/1 rather
        # than looking like a run that checked something.
        record("config readable", False, str(exc))
        return _summarise()
    check_required_files(cfg["required_files"])
    check_token_budgets(cfg, nulled)
    check_secrets_ignored(cfg)
    check_secret_mirrors(cfg)
    check_extra(cfg)
    return _summarise()


if __name__ == "__main__":
    sys.exit(main())
