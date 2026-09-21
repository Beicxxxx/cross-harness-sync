#!/usr/bin/env python3
"""One-command sync-system health check (cross-harness-sync skill).

Config-driven; project-specific checks are declared in `.ai/sync_config.json`,
not hardcoded here. Checks, in order:

  0. The install layout is one git can describe (linked worktrees and symlinked
     payloads leave a `WRITER_LOCK.json` the other writer never sees, so every
     check below would be about the wrong tree). `ai_common.invocation_layout`,
     which asks the unresolved invocation path FIRST and the checkout second —
     the same witness `checkpoint.py --lock` asks, so one entry point is not
     verified and the other blind (finding B7a-6).
  1. The config itself is readable, parses, and holds a JSON object. Reading it
     is the precondition of every other line, so failing here stops the run
     instead of falling back to defaults (D4).
  2. What the config REGISTERS for the project's own checks — one always-
     recorded line counting `extra_checks` and `secret_mirrors`, so emptying
     either (or deleting the key) is a named SKIP rather than silence.
  3. Required state files exist and are non-empty (config "required_files",
     default `ai_common.DEFAULT_REQUIRED_FILES`, with `REQUIRED_FILE_FLOOR`
     unioned back in after the merge — one list, shared with `checkpoint.py
     --validate` through `ai_common.with_required_file_floor`, so a project
     override cannot make the two commands disagree).
  4. The installed protocol stamp parses (`protocol version readable`): a
     required file holding `nightly` is non-empty and still not a version (D22).
  5. Line budgets (per-file LINE caps from config "budgets", with `BUDGET_FLOOR`
     naming the files that must carry a cap when present). The unit is lines —
     `line_count()` counts `splitlines()` — and D26 is the claim, not the check:
     a line is a weak proxy for tokens in CJK state files, which this protocol
     permits.
  6. Decision log cap (config "decisions_max_active_entries")
  7. Secret files are git-ignored (config "secret_files")
  8. Secret mirror key sets match (config "secret_mirrors": pairs of files
     whose KEY NAMES must be identical, e.g. [".env", ".claude/.env"])
  9. Extra project checks (config "extra_checks": [{"name", "cmd"}]; PASS iff
     the command exits 0 AND wrote something — an exit 0 that produced zero
     bytes on both streams is a SKIP, never a pass; e.g. a freeze verifier)

Exit 0 = every check that ran passed, 1 = at least one FAIL. Every check prints
PASS/FAIL/SKIP plus its evidence line, and the summary prints the passed count,
the total and the skip count on ONE line: a check that could not run is named
and kept out of the passed fraction, never folded into it (spec 4). A run whose
records are ALL skips exits 1 — `returncode == 0` is never sufficient, and an
empty `failed` list is not the same fact as "something was verified". Add new
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
    from ai_common import (DEFAULT_REQUIRED_FILES, REQUIRED_FILE_FLOOR,
                           RepoError, decode, git_available,
                           invocation_layout, is_git_repo, parse_version,
                           protect_stdio, resolve_roots, run_argv, run_git,
                           with_required_file_floor)
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
    # Wall-clock seconds one CHILD gets before it is NAMED as failed (D11).
    # Before Task 6 the value lived only in hardcoded call sites, so an operator
    # with a governance script that never returns had one answer: kill the
    # verifier and lose every other line it would have printed. Lane S2 finding 7
    # then split the single knob, because one number was serving two workloads
    # that have nothing in common: `check_timeout` covers `extra_checks` (user-
    # registered scientific verifiers, legitimately minutes) and
    # `git_check_timeout` covers `git check-ignore` (milliseconds, where a 600 s
    # allowance is a hang nobody meant to buy). `EXTRA_CHECK_TIMEOUT` is gone
    # with it: a module constant kept alive only so in-process callers could
    # skip the config is a second source of truth (D23's class), and the drift
    # pin that compared the two had locked the single-knob design in. Both keys
    # merge by REPLACE, which is right for a number — and a string here would
    # silently buy 600 s, so both are shape-checked like the rest of the scalars
    # (A.1).
    "check_timeout": 600,
    "git_check_timeout": 15,
}

# No `REQUIRED_FILES` here: D23 was this constant disagreeing with two private
# copies in checkpoint.py, so the list lives in config with
# `ai_common.DEFAULT_REQUIRED_FILES` as its one default.
#
# `REQUIRED_FILE_FLOOR` (imported above, not restated) is the governance floor
# under that replace-merged key, and `ai_common.with_required_file_floor()` is
# the one function that unions them. It lives there so `checkpoint.py --validate`
# walks the SAME list from the SAME config key: with only the constant shared, a
# project override still made the verifier and `--validate` disagree, which is
# lane V's residual and the same defect class as D23.
#
# WHY the floor is not configurable (finding 3; this replaces an older
# justification that lane V's own commit falsified -- it claimed nothing else
# covered `ROLE_POLICY.md` and `protocol/VERSION`, and `--validate` now walks
# both, which is exactly why they no longer need that argument). The surviving
# reason is narrower and holds on its own: a config edit must never be able to
# un-check a safety file. `required_files` merges by REPLACE, so without a floor
# one line in `.ai/sync_config.json` drops the L0 startup trio (`CURRENT.md`,
# `TASK.md`, `BLOCKERS.md`), the tier rules `ROLE_POLICY.md` or the
# `protocol/VERSION` stamp from BOTH enforcement commands at once, and the
# governance layer the config is supposed to sit inside of stops being checked by
# anything. The floor is exactly those five: the optional tail it deliberately
# does NOT carry (DECISIONS.md, DECISIONS_INDEX.md, LATEST.md) is covered by the
# `budget DECISIONS` SKIP naming its own absence, so a project may opt out of a
# decision log and `tests/test_subprocess_hardening.py` pins that as the deal.
# `tests/test_validate_parity.py` is the agreement pin: it goes red the moment the
# two commands stop walking one list, so neither can drift into "not in my list,
# therefore not required".

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
    "check_timeout": int,
    "git_check_timeout": int,
}

# Scalars that must be a POSITIVE int, not a JSON boolean posing as one.
POSITIVE_INT_KEYS = {"decisions_max_active_entries": "entry cap",
                     "check_timeout": "seconds timeout",
                     "git_check_timeout": "seconds timeout"}

# Keys whose list entries are repo-relative paths.
PATH_LIST_KEYS = ("secret_files", "required_files")

# Magnitude ceilings for the numbers that ARE the governance layer (lane Z
# finding 4). Shape alone let six `999999999`s through: every budget line then
# measured nothing and still booked a PASS, which is the numeric twin of the
# explicit-`null` decline lane S2 turned into a SKIP. A cap nobody can fail is
# not a cap, so an out-of-range value is refused as `malformed:` and names the
# ceiling it broke.
#
# Each ceiling is derived from what the thing it bounds can actually be, not
# from a round number:
#   LINE_CAP_CEILING  10,000 lines. The largest built-in cap is 110
#                     (DECISIONS_INDEX) and the largest cap the installer is
#                     allowed to raise to is 81 (65 own + 16 managed block).
#                     Ten thousand lines is 90x the biggest real cap and far
#                     past any file a human reads at startup -- beyond it the
#                     file is an L2 archive, which this protocol forbids
#                     reading in full and so never budgets.
#   ENTRY_CAP_CEILING 2,000 entries. An active decision entry is capped at 15
#                     lines by the protocol's own template, so 2,000 active
#                     entries is a 30,000-line DECISIONS.md -- already past the
#                     line ceiling above, and the archive index that exists to
#                     bound it.
#   TIMEOUT_CEILING   86,400 seconds. One day of wall clock. The knobs default
#                     to 600 (project checks) and 30 (git check-ignore); a
#                     child a human will not wait a day for is a hung child,
#                     and the timeout stops being a bound above it.
LINE_CAP_CEILING = 10_000
ENTRY_CAP_CEILING = 2_000
TIMEOUT_CEILING = 86_400
POSITIVE_INT_CEILINGS = {"decisions_max_active_entries":
                         (ENTRY_CAP_CEILING, "entries"),
                         "check_timeout": (TIMEOUT_CEILING, "seconds"),
                         "git_check_timeout": (TIMEOUT_CEILING, "seconds")}


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


def _is_repo_relative_path(val) -> bool:
    """A path entry must stay inside the checkout the run is a report about.

    Lane S2 finding 4 (MEDIUM): `PATH_LIST_KEYS` checked `isinstance(str)` and
    nothing else, so `required_files: ["/etc/passwd"]` became `ROOT / p` ==
    `/etc/passwd` and printed a COUNTED PASS about a file outside the tree. On
    Windows `Path("/etc/passwd").is_absolute()` is False, so `root` and `drive`
    are named separately as well; `..` is refused by component and again by
    resolution. The resolution half needs `ROOT`, which a caller that never ran
    `main()` does not have — the by-name refusals hold there alone.
    """
    if not _is_path_str(val):
        return False
    p = Path(val)
    if p.is_absolute() or p.drive or p.root:
        return False
    if ".." in p.parts:
        return False
    if ROOT is not None:
        try:
            (ROOT / p).resolve().relative_to(ROOT.resolve())
        except (OSError, ValueError):
            return False
    return True


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
        escaping = [x for x in val if not _is_repo_relative_path(x)]
        if escaping:
            raise ConfigError(f"malformed: config key {key!r} entries must be "
                              f"repo-relative paths inside the checkout, not "
                              f"{escaping}")
    if key == "budgets":
        # Lane Z finding 1 (HIGH): the keys are paths and only the VALUES were
        # ever checked, so `{"../outside/x.md": 99999}` measured a file outside
        # the checkout and booked `[PASS] budget ../outside/x.md` at rc 0 --
        # `reference.md` documents these keys as repo-relative paths, so the
        # escape contradicts the shipped contract. Same predicate, same
        # refusal, as the list keys one branch above.
        escaping = sorted({str(k) for k in val if not _is_repo_relative_path(k)})
        if escaping:
            raise ConfigError(f"malformed: config key {key!r} keys must be "
                              f"repo-relative paths inside the checkout, not "
                              f"{escaping}")
        bad = sorted(str(k) for k, v in val.items()
                     if not (v is None or (isinstance(v, int)
                                           and not isinstance(v, bool))))
        if bad:
            raise ConfigError(f"malformed: budgets values must be line-count "
                              f"integers (or null to drop a default), not "
                              f"under {bad}")
    if key == "budgets":
        over = sorted((str(k), v) for k, v in val.items()
                      if isinstance(v, int) and not isinstance(v, bool)
                      and v > LINE_CAP_CEILING)
        if over:
            raise ConfigError(f"malformed: budgets values above "
                              f"{LINE_CAP_CEILING} lines cannot fail, so they "
                              f"measure nothing (see the derivation of "
                              f"LINE_CAP_CEILING); got {over}")
    if key == "decisions_file" and not _is_repo_relative_path(val):
        # Lane Z finding 1, second surface: this one string retargets the
        # decision cap, so `../outside/DECISIONS.md` reported 3 entries against
        # cap 20 while the repo's real 500-entry log went uncapped -- and the
        # drive-letter spelling escapes on Windows too.
        raise ConfigError(f"malformed: config key {key!r} must be a "
                          f"repo-relative path inside the checkout, got "
                          f"{val!r}")
    if key in POSITIVE_INT_KEYS and (
            isinstance(val, bool) or not isinstance(val, int) or val <= 0):
        # `true` is an int in Python and `n <= True` passes at 1 entry, so the
        # JSON boolean has to be named here rather than trusted to `int`.
        raise ConfigError(f"malformed: config key {key!r} must hold a positive "
                          f"integer {POSITIVE_INT_KEYS[key]}, got {val!r}")
    if key in POSITIVE_INT_CEILINGS and isinstance(val, int) \
            and not isinstance(val, bool) and val > POSITIVE_INT_CEILINGS[key][0]:
        ceiling, unit = POSITIVE_INT_CEILINGS[key]
        raise ConfigError(f"malformed: config key {key!r} must hold at most "
                          f"{ceiling} {unit}; above that the {POSITIVE_INT_KEYS[key]} "
                          f"cannot be reached, so it verifies nothing "
                          f"(derivation next to the constant), got {val!r}")
    if key == "secret_mirrors":
        for idx, pair in enumerate(val):
            if (not isinstance(pair, list) or len(pair) != 2
                    or not all(_is_repo_relative_path(p) for p in pair)):
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
    to_walk, floor_only = with_required_file_floor(declared)
    if not declared:
        record("required-file list", False,
               "config declares zero required_files; refusing to certify an "
               "unchecked install (the floor entries were checked anyway)")
    if floor_only:
        # Lane S2 finding 8 (MEDIUM): this used to record `True`, booking a PASS
        # for the config ATTEMPTING TO NARROW COVERAGE. It is a trace of the
        # same act the FAIL above names, not a verification: the files the floor
        # restored are counted by their own `required ...` lines below, so the
        # SKIP loses no evidence and stops inflating the numerator.
        record("required-file floor", None,
               f"SKIP(config listed {len(declared)} entries; floor restored "
               f"{floor_only} - these have no necessity check elsewhere, so "
               f"the key's replace policy does not reach them; each one is "
               f"counted by its own `required ...` line below)")
    for rel in to_walk:
        p = ROOT / rel
        if not p.exists():
            record(f"required {rel}", False, "missing")
        elif p.stat().st_size == 0:
            record(f"required {rel}", False, "empty")
        else:
            record(f"required {rel}", True, f"{p.stat().st_size} bytes")


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


# `.ai/protocol/VERSION` is a member of `REQUIRED_FILE_FLOOR`, so its PRESENCE is
# certified by a check that cannot be configured away. That check asks only for
# bytes, though: `nightly` satisfies it, and `compare_version` on such a stamp
# raises. This is the second question, the one D22 says nothing used to ask.
PROTOCOL_VERSION_FILE = ".ai/protocol/VERSION"


def check_protocol_version() -> None:
    """The installed stamp parses, so the next installer can compare it.

    `init_sync.check_version_match` refuses to proceed past a stamp it cannot
    parse, which covers the machine that runs the installer and nobody else: an
    install nobody re-ran, or one whose VERSION was hand-edited afterwards,
    reaches a second harness with a false stamp and a green report. Verification
    is where that case has to be caught.
    """
    path = ROOT / PROTOCOL_VERSION_FILE
    if not path.exists():
        record("protocol version readable", None,
               "SKIP(file is absent, and `required .ai/protocol/VERSION` is a "
               "floor entry that names the absence: nothing goes unasked here)")
        return
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        record("protocol version readable", False,
               f"{PROTOCOL_VERSION_FILE} cannot be read: "
               f"{type(exc).__name__}: {exc}")
        return
    try:
        stamped = ".".join(str(part) for part in parse_version(raw))
    except ValueError as exc:
        record("protocol version readable", False,
               f"{PROTOCOL_VERSION_FILE} holds no comparable version: {exc} - "
               "init_sync refuses to install over this until the file is fixed")
        return
    # Lane Z finding 7 (LOW/MEDIUM): "readable" was the whole question, so
    # `99.99.99` printed `[PASS]` while every later `--scripts-only` -- the
    # documented upgrade path -- refuses the tree as a downgrade. There was no
    # second witness because PROTOCOL_VERSION lived only in init_sync.py, which
    # is deliberately not installed; it is in ai_common.py now, so the stamp is
    # checked against the version the scripts standing in this tree implement.
    from ai_common import PROTOCOL_VERSION as BUILT, compare_version
    if stamped != BUILT:
        ahead = compare_version(stamped, BUILT) > 0
        why = ("it is NEWER than the installed scripts, so init_sync.py's "
               "upgrade path refuses this tree as a downgrade until the stamp "
               "is corrected -- the install can advertise a protocol nobody can "
               "honour AND block the only command that could fix it" if ahead
               else "the installed scripts implement a newer protocol, so this "
                    "install is half-upgraded: re-run init_sync.py "
                    "--scripts-only to rewrite the stamp with the scripts")
        record("protocol version matches installed scripts", False,
               f"{PROTOCOL_VERSION_FILE} reads {stamped} but the installed "
               f".ai/scripts/ implement {BUILT}: {why}")
        return
    record("protocol version readable", True,
           f"{stamped} ({PROTOCOL_VERSION_FILE}; matches the {BUILT} these "
           "scripts implement)")


def check_line_budgets(cfg: dict, nulled: set | None = None) -> None:
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
            # Lane S2 finding 1 (HIGH), the same shape one edit deeper than the
            # one F5 closed: this recorded `True`, so `{"budgets": {<every floor
            # name>: null}}` measured ZERO line budgets and still printed five
            # `[PASS]` lines with the line count of a healthy run at rc 0. The
            # config edit stays legal — the verdict is the claim the line makes,
            # and a decline claims nothing. Spec 4: WARN or SKIP, never PASS.
            record(f"cap opt-out {rel}", None,
                   f"SKIP({rel} is present and its cap was dropped by an "
                   f"explicit null in config: a considered act, not D3's "
                   f"accident, and nothing is measured here)")
        else:
            record(f"budget {rel}", False,
                   "file present, no cap in config and no explicit null - "
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
    # D11: this used to call `run()` bare, so the two things that can happen to
    # any child — it never finishes, or git is not installed — escaped as a
    # traceback that took the rest of the report with it. `run_git` cannot
    # raise; the two degradations are named here instead.
    if not is_git_repo(ROOT):
        record("secret ignored", False,
               "no git repository to ask (see the `git repository` check)")
        return
    # Lane S2 finding 7: its own knob. `git check-ignore` answers in
    # milliseconds, so it must not inherit the 600 s an `extra_checks` verifier
    # may legitimately need, and there is no constant to fall back to.
    timeout = cfg["git_check_timeout"]
    for target in cfg["secret_files"]:
        res = run_git(ROOT, ["check-ignore", "-v", target], timeout=timeout)
        if res.timed_out:
            record(f"secret ignored: {target}", False,
                   f"git check-ignore timed out after {timeout}s")
        elif res.rc == 0:
            # Lane S2 finding 11 (LOW): rc 0 proves an ignore RULE matched, not
            # that a secret is safely placed. With no file on disk this PASS is
            # about one line of `.gitignore`, and the reader is told so.
            rule = (decode(res.stdout).strip()
                    or f"git check-ignore rc={res.rc}")
            if not (ROOT / target).exists():
                rule += " (file absent -- the ignore rule is all this saw)"
            record(f"secret ignored: {target}", True, rule)
        else:
            detail = decode(res.stderr).strip().splitlines()
            record(f"secret ignored: {target}", False,
                   f"git check-ignore rc={res.rc}; "
                   f"{detail[-1][:160] if detail else 'no stderr'}")


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
    #
    # D6: mirrored secrets are git-IGNORED by design, so a second machine that
    # cloned the repo legitimately has neither side on disk. Recording that as a
    # FAIL made close-out unreachable there — the only way to go green was to
    # commit a secret, which is the failure this check exists to prevent. ONLY
    # that both-absent branch is a named SKIP. Lane T7 also skipped the
    # one-side-present case, and that went one branch too far: spec 4 lets an
    # absent file skip only once its absence is provably covered elsewhere, and
    # here nothing covers it. Exactly one side on disk is the single shape that
    # carries evidence of local drift — half a mirror, or a typo in
    # `secret_mirrors`, where a wrong path is indistinguishable from an absent
    # one — so it is a FAIL that names the missing side, at rc 1. What was
    # always a FAIL and stays one: both sides present and disagreeing.
    for pair in cfg["secret_mirrors"]:
        a, b = ROOT / pair[0], ROOT / pair[1]
        name = f"secret mirror {pair[0]} vs {pair[1]}"
        if not a.exists() and not b.exists():
            record(name, None, "SKIP(no mirrored secrets on this machine)")
            continue
        if not (a.exists() and b.exists()):
            here = pair[0] if a.exists() else pair[1]
            there = pair[1] if a.exists() else pair[0]
            record(name, False, f"present on this machine: {here}; "
                                f"absent: {there} - a mirror with one side "
                                f"missing is local drift (or a wrong path in "
                                f"secret_mirrors), not a per-machine "
                                f"difference: create the other side or "
                                f"delete the entry")
            continue
        ka, kb = keys(a), keys(b)
        record(name, ka == kb,
               f"{pair[0]}-only={sorted(ka - kb)}, {pair[1]}-only={sorted(kb - ka)}")


def check_extra(cfg: dict) -> None:
    # Entries are validated objects with a string name and a list cmd, so a
    # missing `cmd` is a named `malformed:` line rather than a KeyError.
    # Lane S2 finding 7: `check_timeout` is read, not defaulted. The merged
    # config always carries it and the in-process callers pass it, so there is
    # no second source of truth to keep in step with it.
    timeout = cfg["check_timeout"]
    for chk in cfg["extra_checks"]:
        name, cmd = chk["name"], chk["cmd"]
        if isinstance(cmd, str):
            # D21: a string argv is a shell string on one platform and an
            # unlaunchable filename on another, so the same config could carry a
            # governance check that exists on Windows and does not exist on
            # macOS. `_check_shape` refuses this on the way in; the refusal has
            # to live here too, because this is the function that makes the
            # promise.
            record(name, False, "extra_checks.cmd must be a JSON array of argv "
                                "words; got a string")
            continue
        res = run_argv(ROOT, cmd, timeout=timeout)
        label = " ".join(str(part) for part in cmd)
        tail = (decode(res.stdout) + decode(res.stderr)).strip().splitlines()
        evidence = tail[-1][:160] if tail else "(no output)"
        # A run we could not finish is never a PASS, and naming only `rc=-1`
        # threw the two facts the operator needs away: WHICH command, and
        # whether it timed out or never started. Both degradations below print
        # FAIL, so a hung or unlaunchable check cannot read as green.
        if res.timed_out:
            record(name, False, f"cmd `{label}` TIMEOUT: timed out after "
                                f"{timeout}s; {evidence}")
        elif res.rc == -1:
            record(name, False, f"cmd `{label}` could not run: {evidence}")
        elif res.rc == 0 and not res.stdout and not res.stderr:
            # Review finding A.2, and the last surviving instance of the class
            # this wave exists to end. Task 1 closed D5's DECODE path (bytes,
            # never `text=True`) but not `ok`: an exit 0 that wrote zero bytes
            # on BOTH streams was `[PASS] <name> rc=0; (no output)`, counted in
            # `== N/N checks passed ==`. rc == 0 is never sufficient, and a
            # check that observed nothing verifies nothing, so this is the
            # tri-state SKIP — named, with the command and the rc still in the
            # evidence, and kept out of the passed fraction by `_summarise()`.
            # A SILENT NONZERO exit stays a FAIL above: muteness is not a claim
            # of success, and softening it would turn a broken governance check
            # into a green run.
            record(name, None, f"cmd `{label}` rc=0; SKIP(child exited 0 but "
                               f"wrote nothing; nothing observed)")
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
    # Lane S2 finding 6 (MEDIUM): an empty `failed` list used to be the whole
    # test, so a run whose every record skipped printed `== 0/N checks passed, N
    # skipped ==` and exited 0. Honest text, unusable code: `returncode == 0` is
    # never sufficient, and findings 1, 2 and 8 add SKIP producers that make the
    # shape reachable rather than merely latent.
    if RESULTS and not passed:
        print("NOT VERIFIED: no check in this run produced a PASS -- every one "
              "of them skipped, so there is nothing behind an exit code of 0")
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
    # Pre-flight (D11, D12). A precondition that FAILED is named and stops the
    # run; a precondition that HELD used to print nothing at all, and that was
    # finding 6: check 0 had exactly one `record()` call and it was the FAIL, so
    # a `17/18 checks passed` report carried zero evidence the layout gate had
    # run -- the exact silence this wave's own new sentences (--prime, the
    # managed block, SYNC_PROMPT, installer step 3) say is not clean. The two
    # EARLY-RETURN branches below still end in `== 0/1 checks passed ==` to say
    # out loud that nothing else ran, which is why the passing record is booked
    # one line later, after the config read that can also stop the run: those
    # literals are pinned in tests/test_install_layout.py:53 and
    # tests/test_config_errors.py:115, and a run that died at an unreadable
    # config still names its single FAIL rather than padding the tally.
    if not git_available():
        # Before this, a machine with no git got seven `rc=128` lines and no
        # explanation, or (with the layout gate) one FAIL about a tree git could
        # not locate — which is the symptom, not the cause.
        record("git usable", False,
               "git not found on PATH; every git-shaped check below would fail "
               "for this same reason, so the run stops here")
        return _summarise()
    if not is_git_repo(ROOT):
        # Named and continued: `checkout_layout` below says MORE than this does
        # about a tree git cannot place, and refusing to report the rest is the
        # layout gate's job, not this one's.
        record("git repository", False,
               f"{ROOT} is not a git work tree; `git check-ignore` and the "
               f"mirror checks have nothing to answer about")
    # Task 7 step 1 (finding B7a-6): `checkout_layout(ROOT)` alone could not see
    # an `.ai` that was INVOKED THROUGH a link, because `resolve_roots()` above
    # had already resolved past it and ROOT named the relocation target's parent
    # — an ordinary-looking tree. `invocation_layout` probes the unresolved
    # invocation path first and falls back to the checkout question, which is
    # exactly what `checkpoint.install_layout` does before it writes a lock, so
    # the writer and the verifier now answer from one function.
    kind, layout_detail = invocation_layout(ROOT, __file__)
    if kind != "normal":
        # D15: a linked worktree keeps its own on-disk WRITER_LOCK.json and a
        # symlinked payload is not versioned in this tree, so the single-writer
        # rule this install claims may already be broken locally. "normal" is
        # only returned when git answered BOTH probes, so `outside-repo` means
        # "could not determine" — which is a FAIL, not a skip (spec 4). Not
        # `kind == "symlinked"`: the other two kinds falling through would let a
        # wrong-tree run print PASS.
        record("install layout", False,
               f"{kind}: {layout_detail} - every check below would be about a "
               f"tree that is not this checkout (both the path this script was "
               f"invoked through and the checkout ROOT names were probed; "
               f"coverage limit: an `.ai` reached only after resolve_roots() "
               f"resolved past it, i.e. one this script was NOT invoked "
               f"THROUGH, stays invisible here)")
        return _summarise()
    try:
        cfg, nulled = load_config()
        # The gate held, so book it: the kind git gave and its witness detail,
        # which is the same string the FAIL branch prints. `normal` is only
        # reachable when BOTH probes agreed, so this PASS is an assertion, not a
        # default -- a `could not determine` answer is the FAIL above it.
        record("install layout", True, f"normal: {layout_detail}")
        # as_posix(): the evidence line is read by agents on the other machines
        # too, and `.ai\sync_config.json` is not the path they wrote in config.
        record("config readable", True, CONFIG_PATH.relative_to(ROOT).as_posix())
    except ConfigError as exc:
        # Every other check is driven by this file, so there is nothing to
        # report on a failure — but the summary still has to say 0/1 rather
        # than looking like a run that checked something.
        record("config readable", False, str(exc))
        return _summarise()
    # Lane S2 finding 2 (HIGH): the run never recorded how many `extra_checks`
    # and `secret_mirrors` it was ASKED to run, so `{"extra_checks": []}` — or
    # deleting the key from a config that carried three governance verifiers —
    # removed every project check with no line at all and `N/N` green. Both keys
    # default to `[]`, so the merged dict cannot tell "never had" from "just
    # removed"; that is the same act ruled a FAIL for `required_files: []`, and
    # the same blindness `nulled` solved for budgets. Counted here on every run,
    # and an empty governance set is a SKIP: it costs the run its clean
    # `passed == total` without going red, because registering nothing is a
    # choice a project may make and not a machine that failed to look.
    registered = list(cfg["extra_checks"]) + list(cfg["secret_mirrors"])
    evidence = (f"{len(cfg['extra_checks'])} extra_checks, "
                f"{len(cfg['secret_mirrors'])} secret_mirrors registered")
    if not registered:
        evidence += " (nothing registered: no line in this report is evidence " \
                    "about the project's own checks)"
    record("registered project checks", True if registered else None, evidence)
    # Lane S2 finding 3 (MEDIUM-HIGH): "the verifier reports failures instead of
    # dying" covered CHILDREN only. Every check below reads user-shaped config
    # against the filesystem — a budget naming a directory (`IsADirectoryError`
    # out of `line_count`), a state file an editor saved as cp936
    # (`UnicodeDecodeError`), a mirror whose entry is `.` — and any one of them
    # raised out of `main()`: no summary printed, and every check after it gone.
    # Contained and NAMED now, so one broken check cannot delete the report.
    for label, run_check in (
            ("required files",
             lambda: check_required_files(cfg["required_files"])),
            ("protocol version", check_protocol_version),
            ("line budgets", lambda: check_line_budgets(cfg, nulled)),
            ("secrets ignored", lambda: check_secrets_ignored(cfg)),
            ("secret mirrors", lambda: check_secret_mirrors(cfg)),
            ("extra checks", lambda: check_extra(cfg))):
        try:
            run_check()
        except Exception as exc:  # noqa: BLE001 -- naming it IS the check
            record(f"{label} check", False,
                   f"check raised {type(exc).__name__}: {exc}")
    return _summarise()


if __name__ == "__main__":
    sys.exit(main())
