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

Exit 0 = every check that ran passed, 1 = at least one FAIL, 2 = no verdict
(`ai_common.py` missing, install root unresolvable, config unusable). Every check prints
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
import hashlib
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
    # The MODULE as well as its names: the wave-1b governance checks call the
    # three-valued history probes (`ai_common.is_shallow`, `ai_common.log_paths`)
    # and `ai_common.glob_match` by name, so a reader of a check body sees which
    # primitive answers each halt question instead of trusting a bare import.
    import ai_common
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
    # Wave 1c C4: the release face. `protected_paths` governs how THIS install is
    # worked on; these govern what gets published from it, and they are separate
    # because a repository that uses the protocol must not be able to certify its
    # own product by writing a record in its own runtime state. Empty means "this
    # tree ships nothing", which is the honest answer for a normal project and
    # skips by name.
    "release_paths": [],
    "release_authorizations_dir": "docs/release-authorizations",
    "release_window_start_commit": "",
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
    # ---- wave 1b governance surface (spec 6, 7) --------------------------------
    # The paths an authorization has to cover. Default EMPTY, and spec 7 is
    # explicit that this is not a weakening: with nothing registered the
    # coverage check reports `SKIP(no-protected-paths)` by name instead of
    # pretending to govern, which is what keeps the documented failure mode --
    # "one honest permanently-red week, then `protected_paths: []` and zero
    # coverage" -- from being the cheap option. Globs are allowed (`*`/`?` do
    # not make an entry non-repo-relative), and D14's case policy is recorded in
    # the key below rather than inherited from the host.
    "protected_paths": [],
    "protected_paths_case": "case-sensitive",
    # Where the authorization records live. `ai_common.AUTHORIZATIONS_SUBDIR`
    # spells the same directory `.ai`-relatively; this key is repo-relative like
    # every other path key, because `_check_shape` validates it with the same
    # repo-relative predicate the secret/required lists get.
    "authorizations_dir": ".ai/state/authorizations",
    # SHA-256 of `.ai/state/ROLE_POLICY.md`. Empty means "unpinned" and the
    # integrity check SKIPs by name; a non-empty value must be 64 lowercase hex,
    # which is what makes "changing the governance document requires a config
    # edit" a real statement rather than a formatting preference.
    "role_policy_sha256": "",
    # Migration's window anchor (`governance.window_start_commit`, spec 8), read
    # by the coverage walk. DEEP so a project can add a governance namespace
    # without dropping one the migrator wrote.
    "governance": {},
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
    # An install shape, like `required_files`: a repo that governs nothing or
    # keeps its authorization records elsewhere must be able to SAY so in one
    # key, and a union would leave it permanently red for a question it has
    # already answered.
    "protected_paths": MERGE_REPLACE,
    # A namespace of anchors, not a set: naming `window_start_commit` must not
    # delete a key the migrator wrote (D3's class, one layer down).
    "governance": MERGE_DEEP,
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
    "protected_paths": list,
    "protected_paths_case": str,
    "authorizations_dir": str,
    "release_paths": list,
    "release_authorizations_dir": str,
    "release_window_start_commit": str,
    "role_policy_sha256": str,
    "governance": dict,
}

# The only two answers D14 can be recorded as. A third spelling would silently
# pick one platform's case behaviour, which is the defect the key exists to end.
PROTECTED_PATH_CASES = frozenset(("case-sensitive", "case-insensitive"))

# A `role_policy_sha256` that is not 64 lowercase hex is not a SHA-256, so it
# cannot pin anything: `""` (unpinned) or this, and nothing between.
SHA256_RE = re.compile(r"[0-9a-f]{64}")

# Scalars that must be a POSITIVE int, not a JSON boolean posing as one.
POSITIVE_INT_KEYS = {"decisions_max_active_entries": "entry cap",
                     "check_timeout": "seconds timeout",
                     "git_check_timeout": "seconds timeout"}

# Keys whose list entries are repo-relative paths.
PATH_LIST_KEYS = ("secret_files", "required_files", "protected_paths")

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
    tag = {True: "PASS", False: "FAIL", None: "SKIP"}[verdict]
    # Lane Z finding 5 (MEDIUM): this appended FIRST and printed second, so a
    # print that raised left the record in the tally anyway -- a child emitting
    # non-UTF-8 bytes gave 19 counted PASSes against 18 printed `[PASS]` lines.
    # The numerator is now derived from what was actually written: the append
    # happens only after the line survived the stream, and a line that does not
    # survive becomes a NAMED degradation instead of a silent increment.
    try:
        print(f"[{tag}] {name}: {evidence}")
    except UnicodeEncodeError as exc:
        safe = f"[{tag}] {name}: {evidence}".encode(
            "utf-8", "backslashreplace").decode("utf-8")
        try:
            print(safe)
        except UnicodeEncodeError:
            pass
        RESULTS.append((f"{name} (unprintable)", False,
                        f"the line above could not be written to stdout "
                        f"({type(exc).__name__}: {exc}); an evidence line "
                        "nobody can read is not a verification, so this is "
                        "counted as a FAIL instead of the "
                        f"{tag} it would have been"))
        return
    RESULTS.append((name, verdict, evidence))


def _is_path_str(val) -> bool:
    return isinstance(val, str) and val.strip() != ""


def _under_ai(val) -> bool:
    """True when a configured directory resolves into `.ai/`, the runtime state."""
    raw = str(val or "").strip().replace("\\", "/")
    if not raw:
        return False
    parts = [seg for seg in raw.split("/") if seg not in ("", ".")]
    # `..` is rejected separately by the repo-relative check; here the question is
    # only whether the target lands under the runtime directory, so a leading `..`
    # cannot make a `.ai/` path look clean.
    return bool(parts) and parts[0] == ai_common.AI_DIR_NAME


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
        # R4 finding 5 (MINOR): this ceiling rule arrived as a SECOND
        # `if key == "budgets":` branch one line below the shape rules above, so
        # the key's contract lived in two places at once. Nothing was shadowed --
        # they are separate `if`s, and the `bad` raise above means only ints
        # reach here -- but a third budgets rule would have landed in whichever
        # branch its author noticed, which is how D3's shallow merge survived as
        # long as it did. One branch, same three refusals, same order.
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
    if key == "release_authorizations_dir" and str(val or "").strip() != val:
        raise ConfigError(f"malformed: config key {key!r} must not carry leading or "
                          f"trailing space, got {val!r}")
    if key == "release_authorizations_dir" and _under_ai(val):
        # The split this key exists to enforce: a release authorisation read from
        # `.ai/state/authorizations` would let a stage note certify a publication,
        # which is the exact collapse the two directories are kept apart to prevent.
        # Repo-relative alone does not stop it -- `.ai/...` is repo-relative.
        raise ConfigError(f"malformed: config key {key!r} must not point into the "
                          f"runtime state directory (.ai/), got {val!r}: the release "
                          f"face is authorised by a release record, not by the "
                          f"repository's own stage note")
    if key in ("authorizations_dir", "release_authorizations_dir")             and not _is_repo_relative_path(val):
        # `release_authorizations_dir` decides which files may authorise a
        # publication, so an escaping path is the same hole one key over: one line
        # would point the verifier at another tree's records and still print PASS.
        # Same class, one key over: this one retargets the RECORD SOURCE every
        # governance check reads, so an absolute or escaping path would let one
        # config line point the verifier at another tree's authorizations and
        # still print `[PASS] swarm boundary`.
        raise ConfigError(f"malformed: config key {key!r} must be a "
                          f"repo-relative path inside the checkout, got "
                          f"{val!r}")
    if key == "protected_paths_case" and val not in PROTECTED_PATH_CASES:
        raise ConfigError(f"malformed: config key {key!r} must be one of "
                          f"{sorted(PROTECTED_PATH_CASES)}, got {val!r}")
    if key == "role_policy_sha256" and val != "" \
            and not SHA256_RE.fullmatch(val.strip()):
        # `d41d8cd9...` truncated by a copy-paste, or a SHA-1 left by v2.0's
        # hash habit, would pin a digest no file can ever match: permanently red
        # at best, and at worst a check that can never be satisfied is a check
        # that gets deleted. Empty is the honest "unpinned" answer and SKIPs by
        # name instead.
        raise ConfigError(f"malformed: config key {key!r} must be empty (not "
                          f"pinned) or 64 lowercase hex characters, got "
                          f"{val!r}")
    if key == "governance":
        if not all(isinstance(k, str) for k in val):
            raise ConfigError(f"malformed: config key {key!r} keys must be "
                              f"strings, got {sorted(map(str, val))}")
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


def check_unfilled_slots() -> None:
    # Wave 1c C1. The slot list lives in `ai_common.INSTALLER_SLOTS` beside the
    # installer that fills them, so the writer and the checker cannot drift into
    # disagreeing about what counts as unfinished.
    hits = []
    for rel, slots in ai_common.INSTALLER_SLOTS.items():
        try:
            body = (ROOT / rel).read_text("utf-8")
        except FileNotFoundError:
            continue  # absence is `required …`'s and the layout check's verdict
        except (OSError, UnicodeDecodeError) as exc:
            hits.append(f"{rel}: unreadable ({type(exc).__name__})")
            continue
        found = [slot for slot in slots if slot in body]
        if found:
            hits.append(f"{rel}: {', '.join(found)}")
    if hits:
        record("unfilled template slots", False,
               "; ".join(hits) + " -- the installer left its own slots blank")
    else:
        record("unfilled template slots", True,
               f"{len(ai_common.INSTALLER_SLOTS)} installer-owned files carry no slot")


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
        # R4 finding 3 (MODERATE, S4): this body ran inside the SECTION-level
        # `except Exception` in `main()`, so ONE unreadable key --
        # `{".ai/state": 10}`, which `line_count()` answers with
        # `PermissionError [Errno 13]` on this host (`IsADirectoryError` on
        # POSIX) -- replaced the whole budget layer's evidence with a single
        # `[FAIL] line budgets check: check raised PermissionError` at `17/19`.
        # Fail-closed, but denial-of-evidence is still evidence lost: the caps
        # that had not printed yet, and the DECISIONS cap below, stopped being
        # measured by a key that has nothing to do with them. Per-entry now: the
        # raising key is one named FAIL naming its error, the rest still report.
        # The same wrap covers the floor loop, which asks `exists()` about a
        # fixed list of names and reaches the identical funnel (S1's shape).
        try:
            p = ROOT / rel
            if not p.exists():
                record(f"budget {rel}", False, f"missing (cap {cap})")
                continue
            n = line_count(p)
            record(f"budget {rel}", n <= cap, f"{n} lines (cap {cap})")
        except Exception as exc:
            record(f"budget {rel}", False,
                   f"could not be measured: {type(exc).__name__}: {exc}")
    # The floor half: a present file with no cap and no explicit null is a
    # silently unchecked file, and `absent so unchecked` is not a shape spec 4
    # allows. An explicit null IS allowed, and gets its own line so the opt-out
    # leaves a trace instead of vanishing from the evidence.
    for rel in BUDGET_FLOOR:
        try:
            if rel in budgets:
                continue
            if not (ROOT / rel).exists():
                continue
            if rel in nulled:
                # Lane S2 finding 1 (HIGH), the same shape one edit deeper than
                # the one F5 closed: this recorded `True`, so `{"budgets":
                # {<every floor name>: null}}` measured ZERO line budgets and
                # still printed five `[PASS]` lines with the line count of a
                # healthy run at rc 0. The config edit stays legal — the verdict
                # is the claim the line makes, and a decline claims nothing.
                # Spec 4: WARN or SKIP, never PASS.
                record(f"cap opt-out {rel}", None,
                       f"SKIP({rel} is present and its cap was dropped by an "
                       f"explicit null in config: a considered act, not D3's "
                       f"accident, and nothing is measured here)")
            else:
                record(f"budget {rel}", False,
                       "file present, no cap in config and no explicit null - "
                       "name the cap or decline it with null")
        except Exception as exc:
            record(f"budget {rel}", False,
                   f"could not be measured: {type(exc).__name__}: {exc}")
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
        elif res.ok and re.match(r"^(FAIL|ERROR)\b", evidence):
            # R4 finding 2 (MAJOR, S3): the last surviving "rc == 0 is
            # sufficient" hole on the only project-extensible surface this
            # protocol has. A child writing `FAIL: nope` to stderr and exiting 0
            # booked `[PASS] <name> ... rc=0; FAIL: nope` inside `== 20/20 ==`,
            # so a green run could carry a line that says, in its own evidence,
            # that the thing it checked failed. The child contradicts itself, and
            # neither reading is defensible: honouring the exit code certifies a
            # FAIL, honouring the line fails a project check we do not own. So
            # the run neither passes nor fails it -- it names the contradiction
            # and keeps it out of the passed fraction (spec 4: a degradation names
            # itself, and a check we cannot vouch for is unverified).
            record(name, None, f"cmd `{label}` rc=0; SKIP(child contradicted its "
                               f"own exit code: it exited 0 and its last line "
                               f"reads `{evidence}` -- not certified either way)")
        else:
            record(name, res.ok, f"cmd `{label}` rc={res.rc}; {evidence}")


# ---------------------------------------------------------------------------
# Wave 1b: the governance surface (spec 6.1, 6.2, 6.3 and N1).
#
# All four read `.ai/state/authorizations/`, the directory v2.0 mandated ("one
# stage = one authorization file") without ever giving instances a canonical
# home, so there was nothing for a verifier to open. What is checked is
# deliberately only what is decidable inside the repo: OMITSION, a forbidden
# pin, a changed governance document, and more than one live authorization.
# None of it can detect a fabricated record -- nothing here binds a recorded
# name to an actual model invocation -- and the docstrings say so rather than
# claiming "enforced".
#
# Every history question is three-valued and UNKNOWN halts (spec 6): a walk
# that could not run is a FAIL naming why, never the green an empty log would
# have printed.
# ---------------------------------------------------------------------------

# The four files the protocol rewrites every few minutes. Pinning one is the
# real incident spec 6.1 encodes: a routine edit stalled on its own state file.
PINNED_STATE_FILES = ("CURRENT.md", "TASK.md", "BLOCKERS.md", "LATEST.md")

# `INDEX.md` is the directory's index (the `DECISIONS_INDEX.md` idiom, kept by
# spec 6), not a stage record. Reading it as one would fabricate a governance
# record out of a table of contents. The name — and the case-INSENSITIVE way it
# is recognised, and the flat walk that honours it — live in `ai_common`, because
# `checkpoint.py --review-prompt` reads the SAME directory and the two readers
# must not hand the reviewer and the verifier different record sets (I-4).
AUTHORIZATION_INDEX_NAME = ai_common.AUTHORIZATION_INDEX_NAME


def _authorization_dir(cfg) -> Path:
    """The record source. An empty key falls back to the canonical home rather
    than to "look nowhere", which would turn a config typo into a silent
    `SKIP(no-authorizations)` on a governed install."""
    rel = str(cfg.get("authorizations_dir", "") or "").strip()
    if not rel:
        return AI_DIR / ai_common.AUTHORIZATIONS_SUBDIR
    return ROOT / rel


def _authorization_dir_label(cfg) -> str:
    """Where the records were looked for, in the spelling the OTHER machine
    reads: repo-relative and forward-slashed, or the absolute path if a custom
    `authorizations_dir` somehow points outside (which `_check_shape` refuses,
    but an evidence line must never raise on its own formatting)."""
    adir = _authorization_dir(cfg)
    try:
        return adir.relative_to(ROOT).as_posix()
    except ValueError:
        return adir.as_posix()


def _authorization_records(cfg):
    """`(records, dir_absent)`; each record is a dict with `rel`, `text`,
    `read_err`, `fields`, `gov_err`.

    Decoded as BYTES then `surrogateescape` (D5's rule: an odd filename must not
    kill the reader thread and leave rc 0 with nothing seen), and a parse
    failure is kept as a string rather than raised: one unreadable audit file
    must not delete the other three checks' evidence, but it must not be counted
    as absent either.
    """
    adir = _authorization_dir(cfg)
    if not adir.is_dir():
        return [], True
    records = []
    try:
        found = ai_common.authorization_records(adir)
    except OSError as exc:
        return [{"rel": _authorization_dir_label(cfg), "text": None,
                 "read_err": f"{type(exc).__name__}: {exc}",
                 "fields": None, "gov_err": None}], False
    for path in found:
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()
        text, read_err = None, ""
        try:
            text = decode(path.read_bytes())
        except OSError as exc:
            read_err = f"{type(exc).__name__}: {exc}"
        fields, gov_err = (None, None)
        if text is not None:
            try:
                fields, gov_err = ai_common.parse_governance_block(text)
            except Exception as exc:  # noqa: BLE001 -- never trust a parser
                gov_err = f"parse raised {type(exc).__name__}: {exc}"
        records.append({"rel": rel, "text": text, "read_err": read_err,
                        "fields": fields, "gov_err": gov_err})
    return records, False


def _section_bullets(text: str, heading: str) -> list:
    """The `- ` bullets under `## <heading>`, each reduced to its leading path.

    The path is the FIRST thing on the bullet: a backtick-quoted span if there is
    one (the shipped template's shape), else the first whitespace token with a
    trailing colon removed. That rule is what keeps `## Pinned baselines`' own
    explanatory bullet -- which NAMES all four state files in prose while telling
    the reader not to pin them -- from reading as four violations. Coverage
    (§6.3) and pins (§6.1) are both decided by this one parser, so the two
    checks cannot disagree about what a record lists.
    """
    out = []
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped[3:].strip().lower() == heading.lower()
            continue
        if not in_section or not stripped.startswith("-"):
            continue
        token = stripped[1:].strip()
        if not token:
            continue
        if token.startswith("`"):
            _, tick, tail = token.partition("`")
            if not tick:
                continue
            # Close the span: `partition` hands back everything AFTER the opening
            # tick, which still carries the closing one. Reading a pattern as
            # `protected/*`` matches nothing, and a coverage walk that matches
            # nothing is the fail-open this check exists to close.
            candidate = tail.partition("`")[0].strip()
        else:
            candidate = token.split()[0].rstrip(":").strip()
        if candidate:
            out.append(candidate)
    return out


def _sha_header(line: str) -> bool:
    """Is this line a `%H` commit id, or a path that merely looks like one?

    Two constraints, both measured on this host rather than assumed. `git log
    --pretty=format:%H --name-only -z` glues the id to its own commit's FIRST
    path and puts every later path in a record of its own, so a header line is
    always the first line of a MULTI-LINE record; a single-line record is a path,
    not a commit. And `%H` always prints lower case. Requiring both is what stops
    a real top-level file named `deadbeef…` (40 hex chars) from being read as the
    start of a new commit -- which is exactly what the old "40 chars, all hex,
    upper case allowed" sniffing did to such a file listed after another path in
    one commit: the name was swallowed as a sha, its path vanished from the walk,
    and coverage printed a PASS over the touch it never saw. The residual
    ambiguity runs the safe way: a path that loses its header is re-parented to
    the previous commit and still counted, so a wrong answer here can only cost a
    FAIL naming an odd sha, never a green.
    """
    return (len(line) == ai_common.SHA_HEX_LEN
            and all(c in "0123456789abcdef" for c in line))


def _walk_touches(records):
    """`(sha, rel_path)` pairs out of `ai_common.log_paths` RECORDS.

    An element of that list is NOT a bare path: the first record of a commit is
    `"<sha>\\n<first path>"` and each later path of the same commit arrives as
    its own single-line `"<path>"` record, because `-z` terminates records, not
    lines. So ONLY the first line of a multi-line record may be read as the
    commit header and every line after it is a path; anything else is a path too,
    re-parented to the last sha seen. Dropping a path would under-count coverage,
    and under-counted coverage is the fail-open this walk exists to close, so the
    continuation branch keeps every line.
    """
    out = []
    current = ""
    for rec in records:
        head, sep, rest = rec.partition("\n")
        if sep and _sha_header(head):
            current = head
            lines = rest.split("\n")
        else:
            lines = rec.split("\n")
        for raw in lines:
            if raw.strip():
                out.append((current, raw.replace("\\", "/")))
    return out


def _case_sensitive(cfg) -> bool:
    return str(cfg["protected_paths_case"]) != "case-insensitive"


def _pin_names_state_file(pin: str, cfg) -> bool:
    """Does this pinned entry name one of the four fast-changing state files?

    Decided on the LAST component, so `.ai/state/CURRENT.md` and a bare
    `CURRENT.md` both count, and under `case-insensitive` on the case-folded
    pair -- a `current.md` pin evading the rule by spelling is the same D14
    host-dependence the config key exists to record.
    """
    name = pin.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not name:
        return False
    if _case_sensitive(cfg):
        return name in PINNED_STATE_FILES
    return name.lower() in {n.lower() for n in PINNED_STATE_FILES}


def _protected_pathspec(paths, cfg) -> list:
    """The `git log -- <pathspec>` entries that MEAN the recorded D14 policy.

    Final review I-2, measured: with `protected_paths: ["SRC/*"]` and
    `protected_paths_case: "case-insensitive"` the walk printed
    `[PASS] path coverage: 0 protected touches covered` over a commit that
    touched `src/engine.py`, because the case policy only ever filtered the
    EDITABLE side (`glob_match`) while the candidate side asked git with a plain,
    case-SENSITIVE pathspec. The governed work never reached the comparison, so
    the more the pattern under-matched the greener the run read — under-govern,
    and book the PASS. `:(icase)` is git's own case-insensitive pathspec magic,
    which makes the recorded policy mean one thing on both sides of the check.
    An entry that already carries its own magic prefix is left alone.
    """
    if _case_sensitive(cfg):
        return list(paths)
    return [p if p.startswith(":(") else f":(icase){p}" for p in paths]


def _protected_set_is_void(pathspec):
    """`(void, why)` — does ANY tracked file match this protected set at all?

    A typo'd pattern, a renamed directory, or a list written for a different
    layout produces the same permanently-green shape as a genuinely quiet window:
    zero candidates, zero touches, one PASS. §4 forbids reading a degradation as
    a verdict, so the run says so by name. `why` is non-None when git could not
    answer, which is its own named degradation and never a licence for the PASS.
    """
    res = ai_common.run_git(ROOT, ["ls-files", "-z", "--", *pathspec],
                            timeout=15)
    if res.timed_out:
        return None, "`git ls-files` timed out"
    if res.rc != 0:
        detail = ai_common.decode(res.stderr).strip().splitlines()
        return None, (f"`git ls-files` exited {res.rc}: "
                      f"{detail[-1][:160] if detail else 'no stderr'}")
    return (not [b for b in res.stdout.split(b"\x00") if b]), None


def _degenerate_empty_window(window: str, pathspec):
    """Why a walk that saw zero touches may be governing nothing, or None if not.

    `(kind, evidence)` with kind in {"fail", "skip"}; None means the empty answer is
    a genuinely quiet window and may be reported as coverage.

    Called by `release authorization` only, and that is a scope decision rather than
    an oversight: `test_a_protected_set_that_does_match_tracked_files_books_the_pass`
    anchors at the tip on purpose and expects a PASS for a window with no protected
    commit, so the same three lines turned two settled runtime-walk tests red. The
    walk over this repository's own state has the hole as well. It is recorded in
    `.ai/state/DECISIONS.md` and left alone here, because a check's reach should not
    be widened by whatever else this PR happens to be touching.

    Both shapes below produce the same permanently-green figure as a real quiet
    window -- zero candidates, zero touches, one PASS -- and spec 4 forbids reading
    either of them as a verdict.
    """
    tip = ai_common.run_git(ROOT, ["rev-parse", "HEAD"], timeout=15)
    if tip.ok and tip.out().strip() == window:
        return "fail", ("the window anchor IS the current tip (" + window[:8] +
                         "), so `<anchor>..HEAD` is empty by construction and can "
                         "cover nothing: name the commit before the first change "
                         "meant to be governed")
    # Comparing the anchor to the tip as a STRING catches only one degenerate
    # choice. A side-branch tip or a sha left behind by `git reset` is a real,
    # well-formed commit that simply is not in HEAD's past, and the range it
    # bounds is just as empty -- so ancestry, not equality, is the question.
    anc = ai_common.git_ancestor(ROOT, window, "HEAD")
    if anc == "UNKNOWN":
        return "fail", ("cannot tell whether the window anchor " + window[:8] +
                        " is in HEAD's past (shallow or absent object): an empty "
                        "walk here is unknown coverage, not quiet history")
    if anc != "TRUE":
        return "fail", ("the window anchor " + window[:8] + " is not an ancestor of "
                        "HEAD, so `<anchor>..HEAD` reaches no commit at all: the "
                        "empty result is the configuration, not a quiet window")
    void, void_why = _protected_set_is_void(pathspec)
    if void_why is not None:
        return "fail", ("cannot determine whether the registered set matches "
                        f"anything: {void_why} -- not knowing is not a clean verdict")
    if void:
        return "skip", None
    return None


def check_coverage_walk(cfg: dict) -> None:
    """spec 6.3: every protected-path touch in the window is covered by an
    ACCEPTED authorization's own `## Editable files` list.

    Omission only. A commit whose path is listed nowhere is a named FAIL; a walk
    git could not answer is a named FAIL too; only a run with nothing to govern
    (no registered paths, no window) skips, and it says which of the two.
    """
    paths = list(cfg["protected_paths"])
    if not paths:
        record("path coverage", None,
               "SKIP(no-protected-paths): the install registers nothing to "
               "govern")
        return
    governance = cfg.get("governance") or {}
    window = str(governance.get("window_start_commit", "") or "")
    if window in ("", "NO_HISTORY"):
        record("path coverage", None, f"SKIP(no-window: {window or 'unset'})")
        return
    if not ai_common.window_is_valid(window):
        # Final review I-1, measured: `window_start_commit: "HEAD"` made
        # `git log HEAD..HEAD` a permanently empty range, and the walk booked
        # `[PASS] path coverage: 0 protected touches covered` at rc 0 while the
        # window held a real protected commit nobody authorised. The shape
        # predicate that refuses such an anchor used to live in `init_sync` as a
        # private `_window_is_valid`, so only the writer of the field enforced it
        # and every other reader governed whatever the rev happened to resolve
        # to. An anchor that is not a commit id is not an empty window.
        record("path coverage", False,
               f"window anchor is not a commit id: "
               f"`governance.window_start_commit` is {window!r}, which is "
               f"neither a {ai_common.SHA_HEX_LEN}-lowercase-hex commit id nor "
               f"`{ai_common.NO_HISTORY}`, so the range this walk is bounded by "
               f"cannot be read (spec 8 writes, spec 6.3 reads: a malformed "
               f"anchor is a FAIL, not the empty log it would have printed)")
        return
    if not is_git_repo(ROOT):
        record("path coverage", False,
               "no git repository to walk (see the `git repository` check), so "
               "coverage cannot be certified")
        return
    shallow = ai_common.is_shallow(ROOT)
    if shallow != "FALSE":
        # TRUE: history is truncated, so an absent commit is not evidence of an
        # unreviewed change. UNKNOWN: git could not even answer that. Both halt
        # (spec 6: `UNKNOWN` halts, and a bounded walk is bounded by history
        # availability, which is why this may not skip its way to green).
        record("path coverage", False,
               f"shallow/indeterminate history ({shallow.lower()}): the bounded "
               f"walk cannot certify coverage of window {window[:8]}..HEAD")
        return
    pathspec = _protected_pathspec(paths, cfg)
    rev = f"{window}..HEAD"
    nonmerge, why = ai_common.log_paths(
        ROOT, ["--no-merges", "--full-history", "--pretty=format:%H", rev],
        pathspec)
    if nonmerge is None:
        record("path coverage", False, f"walk halted: {why}")
        return
    merges, why = ai_common.log_paths(
        ROOT, ["--merges", "-m", "--first-parent", "--pretty=format:%H", rev],
        pathspec)
    if merges is None:
        record("path coverage", False, f"walk halted: {why}")
        return
    touched = sorted(set(_walk_touches(nonmerge) + _walk_touches(merges)))
    if not touched:
        void, void_why = _protected_set_is_void(pathspec)
        if void_why is not None:
            print(f"[WARN] path coverage: the registered set could not be "
                  f"matched against the tracked files ({void_why}), so this "
                  f"line certifies coverage of nothing it confirmed exists")
            # Re-review NEW-1: this arm printed the WARN and then fell through to
            # the PASS two blocks below, so a `git ls-files` that timed out or
            # could not read the index produced
            # `[PASS] path coverage: 0 protected touches covered` at rc 0 -- the
            # shape 4 forbids, and the reverse of what `_protected_set_is_void`
            # 's docstring promises. Not knowing whether the registered set is
            # empty is a different fact from the window being quiet, and only the
            # second one would be a pass.
            record("path coverage", None,
                   f"SKIP(void-check-unavailable): {void_why} -- the walk saw "
                   f"no protected touch and the registered set could not be "
                   f"shown non-empty either, so this line is not evidence")
            return
        elif void:
            print(f"[WARN] path coverage: no tracked file matches any of the "
                  f"{len(paths)} protected_paths pattern(s), so the walk has no "
                  f"candidate to govern")
            record("path coverage", None,
                   "SKIP(void-protected-set): no tracked file matches any "
                   f"registered protected_paths pattern ({', '.join(paths[:6])}"
                   f"{', ...' if len(paths) > 6 else ''}) -- a typo'd or "
                   "renamed protected set governs nothing, and a permanently "
                   "green line is how that hides (spec 4: named, never PASS)")
            return
    records, _absent = _authorization_records(cfg)
    editable = []
    for rec in records:
        if ai_common.is_accepted(rec["fields"]) and rec["text"] is not None:
            editable += _section_bullets(rec["text"], "Editable files")
    uncovered = [(sha, rel) for sha, rel in touched
                 if not ai_common.glob_match(rel, editable,
                                             case_sensitive=_case_sensitive(cfg))]
    if uncovered:
        shown = ", ".join(f"<{sha[:8]} {rel}>" for sha, rel in uncovered[:8])
        more = f" (+{len(uncovered) - 8} more)" if len(uncovered) > 8 else ""
        record("path coverage", False,
               f"{len(uncovered)} uncovered of {len(touched)} protected "
               f"touches: {shown}{more} -- no accepted authorization's "
               f"`## Editable files` lists these paths (spec 6.3: this is "
               f"omission, and a fabricated record would look the same here)")
        return
    record("path coverage", True, f"{len(touched)} protected touches covered")


def check_release_authorization(cfg: dict) -> None:
    """Wave 1c C4: what gets published needs a release record, not a stage note.

    Same walk as `path coverage`, different path set and a different directory,
    because the two questions only look alike: "was this stage allowed to edit files
    in its own tree" versus "did anyone accept shipping these files to other people".
    Registering the release face under `protected_paths` merges them and lets the
    repository that happens to host a product certify its own publication, which is
    what wave 1b's dogfood did to itself. Only an ACCEPTED record counts here; a
    pending one is a stage that has not been reviewed, and it publishes nothing.
    """
    paths = list(cfg.get("release_paths") or [])
    if not paths:
        record("release authorization", None,
               "SKIP(no-release-paths): this tree registers nothing it publishes")
        return
    # No empty-value arm here on purpose: `release_authorizations_dir: ""` is refused
    # by the config shape check at rc 2 before any check runs, so a branch for it
    # would be unreachable code claiming to be a guard.
    rel_dir = str(cfg.get("release_authorizations_dir") or "").strip()
    governance = cfg.get("governance") or {}
    # The release face starts where the concept starts. Falling back to the runtime
    # window would reach back through every commit made before a repository had any
    # notion of a release record, and a rule cannot govern the period before it
    # existed: measured here, a shared anchor reported 46 uncovered of 46, all but
    # eight of them older than this check. An explicit anchor is how the boundary is
    # recorded rather than assumed, and the shape predicate still refuses a fake one.
    window = str(cfg.get("release_window_start_commit", "")
                 or governance.get("window_start_commit", "") or "")
    if window in ("", "NO_HISTORY"):
        record("release authorization", None, f"SKIP(no-window: {window or 'unset'})")
        return
    if not ai_common.window_is_valid(window):
        record("release authorization", False,
               f"window anchor is not a commit id: {window!r} bounds no readable "
               "range, and an unreadable bound is not the empty log it would print")
        return
    if not is_git_repo(ROOT):
        record("release authorization", False,
               "no git repository to walk, so what ships here is unverifiable")
        return
    shallow = ai_common.is_shallow(ROOT)
    if shallow != "FALSE":
        # Same rule as the runtime walk: a truncated history cannot distinguish
        # "never authorised" from "authorised, then the object went away", and
        # UNKNOWN halts for the same reason.
        record("release authorization", False,
               f"shallow or indeterminate history ({shallow.lower()}): the bounded "
               f"walk cannot certify coverage of window {window[:8]}..HEAD")
        return
    pathspec = _protected_pathspec(paths, cfg)
    rev = f"{window}..HEAD"
    nonmerge, why = ai_common.log_paths(
        ROOT, ["--no-merges", "--full-history", "--pretty=format:%H", rev], pathspec)
    if nonmerge is None:
        record("release authorization", False, f"walk halted: {why}")
        return
    merges, why = ai_common.log_paths(
        ROOT, ["--merges", "-m", "--first-parent", "--pretty=format:%H", rev], pathspec)
    if merges is None:
        record("release authorization", False, f"walk halted: {why}")
        return
    touched = sorted(set(_walk_touches(nonmerge) + _walk_touches(merges)))

    directory = ROOT / Path(rel_dir)
    try:
        entries = sorted(p for p in directory.iterdir()
                         if p.suffix.lower() == ".md" and p.name.upper() != "INDEX.MD")
    except (FileNotFoundError, NotADirectoryError):
        record("release authorization", False,
               f"`release_paths` registers {len(paths)} pattern(s) but {rel_dir} does "
               "not exist: no record here can have authorised these commits")
        return
    except OSError as exc:
        record("release authorization", False,
               f"{rel_dir} could not be read ({type(exc).__name__}): a directory that "
               "cannot be read is not a directory holding no authorisations")
        return

    accepted, pending, unreadable, undecidable, bases = [], 0, [], [], []
    for path in entries:
        try:
            text = path.read_text("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append(f"{path.name} ({type(exc).__name__})")
            continue
        fields, gov_err = ai_common.parse_governance_block(text)
        if gov_err:
            undecidable.append(f"{path.name} ({gov_err})")
        if ai_common.is_accepted(fields):
            accepted += _section_bullets(text, "Editable files")
            bases.append((path.name,
                          str((fields or {}).get(
                              "window_start_commit", "") or "").strip(),
                          ai_common.is_live_stage(fields)))
        else:
            pending += 1

    # A release record enumerates; it does not glob. The bullets are matched with
    # `fnmatch`, where `*` crosses `/`, and accepted records keep their force for the
    # rest of the window -- so one `*` here would cover every future shipped commit,
    # forever, from a file that was already approved. Enumeration is the whole
    # reason this list exists, so a glob is a FAIL and not a style preference.
    globs = [b for b in accepted if any(ch in b for ch in "*?[")]
    if globs:
        record("release authorization", False,
               f"{len(globs)} accepted release bullet(s) use a glob instead of a "
               f"path: {', '.join(sorted(set(globs))[:4])} -- `*` crosses `/` and an "
               "accepted record never expires within the window, so one wildcard "
               "authorises the whole release face for every later commit")
        return

    conflicts = _release_base_conflicts(bases, window)
    if conflicts:
        record("release authorization", False,
               f"{len(conflicts)} accepted release record(s) do not bound the "
               f"window that was walked: "
               + "; ".join(f"{n} {w}" for n, w in conflicts))
        return

    if not touched:
        # Same predicate, one extra arm: a quiet release window whose only record
        # could not be read is "cannot determine", and the shared helper has no way
        # to know a record was unreadable.
        kind, evidence = _degenerate_empty_window(window, pathspec) or (None, None)
        if kind == "fail":
            record("release authorization", False,
                   f"{evidence} (an empty range is not authorisation)")
            return
        if unreadable:
            record("release authorization", None,
                   f"SKIP(release-records-unreadable): the window is quiet and "
                   f"{len(unreadable)} record(s) could not be read "
                   f"({', '.join(unreadable[:3])}) -- nothing was confirmed here, "
                   "and an unreadable authorisation is not an absent one that proves "
                   "there is nothing to publish")
            return
        if not bases and kind is None:
            # An empty range with nothing accepted in the directory is not a
            # certified quiet window: `release_window_start_commit` is a config
            # line, and moving it forward is indistinguishable from a project that
            # shipped nothing -- from inside the walk. Spec 4: named, never PASS.
            record("release authorization", None,
                   f"SKIP(quiet-window-unanchored): the range is empty and "
                   f"{len(entries)} record(s) in {rel_dir} carry no accepted "
                   "`verdict`, so nothing states where a release stage began -- an "
                   "unbounded empty walk proves only that it did not look")
            return
        if kind is None:
            record("release authorization", True,
                   f"0 release-face (commit, path) pairs covered "
                   f"({len(entries)} record(s) in {rel_dir})")
            return
        print("[WARN] release authorization: no tracked file matches any of the "
              f"{len(paths)} release_paths pattern(s), so this line governs nothing")
        record("release authorization", None,
               "SKIP(void-release-set): no tracked file matches any release_paths "
               f"pattern ({', '.join(paths[:6])}"
               f"{', ...' if len(paths) > 6 else ''}) -- a typo'd release set is "
               "permanently green, which is exactly how it hides (spec 4: named, "
               "never PASS)")
        return

    if unreadable:
        # A record that cannot be read is neither absent nor accepted. Until now it
        # appeared only inside the evidence string of a PASS over whatever the
        # readable records happened to cover -- a green booked while part of the
        # authority set was unread, which is the shape `pin violation` refuses.
        record("release authorization", False,
               f"{len(unreadable)} release record(s) are unreadable "
               f"({', '.join(unreadable[:3])}): could not be read, so the accepted "
               "set below is not the whole authority set and a coverage claim "
               "about it is not a fact")
        return

    uncovered = [(sha, rel) for sha, rel in touched
                 if not ai_common.glob_match(rel, accepted,
                                             case_sensitive=_case_sensitive(cfg))]
    origin = f"{len(entries)} record(s) in {rel_dir}"
    if undecidable:
        # "not accepted" and "cannot be told" are different answers, and the
        # runtime records name which of them applies (`swarm boundary`'s `broken`
        # bucket); a release record whose block does not parse used to be counted
        # with the declined ones, which reads as a stage nobody approved.
        origin += (f", {len(undecidable)} with an unparseable `## Governance` "
                   f"block ({', '.join(undecidable[:3])})")
    if uncovered:
        shown = ", ".join(f"<{sha[:8]} {rel}>" for sha, rel in uncovered[:8])
        more = f" (+{len(uncovered) - 8} more)" if len(uncovered) > 8 else ""
        files = len({rel for _sha, rel in touched})
        record("release authorization", False,
               f"{len(uncovered)} uncovered of {len(touched)} release-face "
               f"(commit, path) pairs across {files} files: "
               f"{shown}{more} -- {origin}, {pending} not accepted. A pending record "
               "certifies nothing: an unreviewed stage cannot publish on its own word")
        return
    record("release authorization", True,
           f"{len(touched)} release-face (commit, path) pairs covered by "
           f"accepted record(s) "
           f"({origin})")


def _release_base_conflicts(bases, window):
    """`(name, why)` for each LIVE accepted release record whose own base the
    walked window has left behind; empty when every one still bounds its history.

    The anchor is a config line and the walk's reach is exactly that line, so
    advancing `release_window_start_commit` past a record's declared base drops
    the commits that record authorised — and they then read as COVERED, because
    nothing walks them any more. `_degenerate_empty_window` catches the two
    shapes that empty the range entirely; this catches the one that merely
    narrows it.

    A `status: closed` record is exempt, and that is the same split W19 had to
    make for `swarm boundary`: re-anchoring the release window at a new wave is
    the lifecycle, so binding a finished stage's base to it forever would make
    the second wave of any project permanently red — the remedy would then be to
    edit or delete an approved record, which is strictly worse than the hole.
    What is refused is shrinking the window out from under a stage still open.
    An accepted record must still state its base: `verdict: accepted` naming no
    range is a claim nobody can check.
    """
    out = []
    for name, base, live in bases:
        if not live:
            continue
        if not base:
            out.append((name, "declares no `window_start_commit`, so the window it "
                              "authorises cannot be checked against the one walked"))
            continue
        if not ai_common.window_is_valid(base):
            out.append((name, f"names {base!r} as its base, which is not a commit "
                              "id (a base that resolves to something else governs "
                              "a different range than the record says)"))
            continue
        if ai_common.commit_exists(ROOT, base) != "TRUE":
            out.append((name, f"names base {base[:8]} which is not a commit in this "
                              "history, so no range can be bounded by it"))
            continue
        if ai_common.git_ancestor(ROOT, window, base) != "TRUE":
            out.append((name, f"its base {base[:8]} is not at-or-after the walked "
                              f"window's anchor {window[:8]}: the anchor has been "
                              "moved past the commits this record authorised, so "
                              "the walk reports them neither uncovered nor covered "
                              "-- it never looks"))
    return out


def check_pin_violation(cfg: dict) -> None:
    """spec 6.1: the only proposed check whose falsifiable fact lies entirely
    inside the repo -- a pin on a fast-changing state file."""
    records, _absent = _authorization_records(cfg)
    if not records:
        record("pin violation", None, "SKIP(no-authorizations)")
        return
    unreadable = [r for r in records if r["text"] is None]
    if unreadable:
        record("pin violation", False,
               "cannot read the authorization record(s) "
               + ", ".join(f"{r['rel']} ({r['read_err']})" for r in unreadable)
               + "; an unreadable pin list is not an empty one")
        return
    offenders = [(r["rel"], pin) for r in records
                 for pin in _section_bullets(r["text"], "Pinned baselines")
                 if _pin_names_state_file(pin, cfg)]
    if offenders:
        record("pin violation", False,
               f"{len(offenders)} forbidden pin(s): "
               + "; ".join(f"{rel} pins {pin}" for rel, pin in offenders)
               + " -- CURRENT/TASK/BLOCKERS/LATEST are rewritten every few "
                 "minutes, so pinning one stalls the routine edit it names "
                 "(spec 6.1)")
        return
    record("pin violation", True,
           f"{len(records)} authorization record(s), no state file pinned")


def check_role_policy_integrity(cfg: dict) -> None:
    """spec 6.2: the governance document's SHA-256 is pinned in config, so
    changing it requires a diff a human reads. Anchor grepping was rejected --
    `"T1" in text` is satisfied by "R12" -- so this asks one decidable
    question: do the bytes hash to the promise?"""
    want = str(cfg["role_policy_sha256"] or "").strip()
    if not want:
        record("role policy integrity", None, "SKIP(no-sha-pinned)")
        return
    if not SHA256_RE.fullmatch(want):
        # `_check_shape` refuses this on the way in; the check repeats the rule
        # because an in-process caller hands this function a dict directly, and
        # a digest that cannot match anything must fail rather than compare.
        record("role policy integrity", False,
               f"config's role_policy_sha256 is not 64 lowercase hex "
               f"({want!r}), so nothing could satisfy it")
        return
    # `AI_DIR / state / ROLE_POLICY.md` is the repo-relative
    # `.ai/state/ROLE_POLICY.md`; AI_DIR is the resolved one (D19), and
    # `required .ai/state/ROLE_POLICY.md` (a floor entry) already certifies
    # presence for the default path. Here the question is identity, not presence.
    path = AI_DIR / "state" / "ROLE_POLICY.md"
    rel = ".ai/state/ROLE_POLICY.md"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        record("role policy integrity", False,
               f"{rel} is missing while config pins its digest: the pinned "
               f"document is not on disk to verify")
        return
    except OSError as exc:
        record("role policy integrity", False,
               f"{rel} could not be read: {type(exc).__name__}: {exc}")
        return
    got = hashlib.sha256(raw).hexdigest()
    if got == want:
        record("role policy integrity", True,
               f"{rel} digests to the pinned {want} ({len(raw)} bytes)")
        return
    record("role policy integrity", False,
           f"{rel} digests to {got} but config pins {want}: the governance "
           f"document changed without the config edit that makes the change "
           f"visible")


def _closed_note(closed, live):
    """The tail that says which accepted records stepped out of the count.

    Without it `2 accepted authorization(s) of 2 record(s)` beside a PASS reads as
    a check that lost a record: the reader cannot see which one the boundary
    treated as finished, or that it still authorises the commits it names.
    `accepted` keeps its meaning (a verdict of `accepted`) in both halves of the
    line; the live set is what gets compared to one.
    """
    if not closed:
        return ""
    return (f" -- {len(live)} of them live, {len(closed)} closed "
            f"({', '.join(sorted(closed))}): a closed stage still covers the "
            "commits it was accepted for, and the boundary compares the live "
            "count to one")


def check_swarm_boundary(cfg: dict) -> None:
    """N1: SKILL.md declares concurrent swarms out of scope and the protocol
    mandates one live authorization per stage, yet two accepted records used to
    verify green because every other check reads one file at a time.

    The count that IS decidable breaks the boundary first, so a blockless or
    verdict-less record cannot be used to hide a second accepted one. The count is
    of LIVE stages (`status: closed` steps out): a repository that has run two
    finished stages has two accepted records, and making that red forever is what
    tempted wave 1c to retire a record and uncover its own history instead.
    """
    records, _absent = _authorization_records(cfg)
    if not records:
        record("swarm boundary", True,
               f"0 accepted authorizations: no stage record in "
               f"{_authorization_dir_label(cfg)}, so nothing is live and "
               f"nothing can be concurrent")
        return
    broken, legacy, undecided = [], [], []
    accepted, live, closed = [], [], []
    for rec in records:
        if rec["text"] is None:
            broken.append(f"{rec['rel']} (unreadable: {rec['read_err']})")
        elif rec["gov_err"]:
            broken.append(f"{rec['rel']} ({rec['gov_err']})")
        elif rec["fields"] is None:
            legacy.append(rec["rel"])
        elif not str(rec["fields"].get("verdict", "") or "").strip():
            # A block that parsed but names no verdict is not a decidable record
            # either. Leaving it out of every bucket used to print
            # `PASS 0 accepted authorization(s) of 1 record(s)` -- a green booked
            # on the very file whose status is unknown, which is the fail-open
            # spec 4 forbids ("a degradation may produce a named WARN/SKIP,
            # never PASS"), so it is carried as an undecided name instead.
            undecided.append(f"{rec['rel']} (its `## Governance` block names no "
                             f"`verdict:`)")
        elif ai_common.is_accepted(rec["fields"]):
            accepted.append(rec["rel"])
            # Split on `status`, not on `verdict`: a stage that has finished is
            # still the authority over the commits it was accepted for, so
            # retiring it by rewriting its verdict uncovered its own history.
            # `accepted` stays the full set because the report has to say how
            # many records were accepted; `live` is what can be concurrent, and
            # it is the shared predicate -- one definition for this and for
            # `checkpoint`'s review prompt, because two readers deciding "live"
            # separately is the contradiction the tree cannot check.
            if ai_common.is_live_stage(rec["fields"]):
                live.append(rec["rel"])
            else:
                closed.append(rec["rel"])
    if len(live) > 1:
        record("swarm boundary", False,
               f"{len(live)} concurrent accepted authorizations ({', '.join(sorted(live))}): "
               f"SKILL.md declares concurrent swarms out of scope, and one "
               f"stage = one live authorization"
               + _closed_note(closed, live))
        return
    if broken:
        record("swarm boundary", False,
               f"{len(broken)} record(s) carry a governance block that cannot "
               f"be parsed, so the accepted count is not decidable and cannot "
               f"be certified either way: " + "; ".join(broken))
        return
    if legacy or undecided:
        record("swarm boundary", None,
               f"SKIP(no-verdict: {', '.join(sorted(legacy + undecided))}): a "
               f"record with no `## Governance` block, or with a block that "
               f"names no `verdict:`, is a legacy or incomplete stage record "
               f"(spec 6 names it, it never PASSes), carries no verdict, and is "
               f"therefore not counted as accepted -- so the concurrency "
               f"question stays open here rather than booking a PASS over the "
               f"file whose status is unknown")
        return
    record("swarm boundary", True,
           f"{len(accepted)} accepted authorization(s) of {len(records)} "
           f"record(s) in the window" + _closed_note(closed, live))


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
        # Lane Z finding 6 (LOW): SKILL.md's exit-code table documents rc 2 for
        # "config unusable" and the code answered 1, so a run that reached NO
        # verdict read as a verdict of FAIL -- the distinction checkpoint.py
        # goes out of its way to keep (`--validate` rc 2 for an unreadable
        # record, `--force` without `--reason` rc 2). The table was right; this
        # is the half that was wrong. The printed `== 0/1 checks passed ==` and
        # the FAILED line are unchanged, so no total moves -- only the code.
        _summarise()
        print("NOT VERIFIED: the config is unusable, so every check that reads "
              "it was skipped; this is a missing verdict (rc 2), not a failed "
              "one")
        return 2
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
            ("unfilled template slots", check_unfilled_slots),
            ("protocol version", check_protocol_version),
            ("line budgets", lambda: check_line_budgets(cfg, nulled)),
            ("secrets ignored", lambda: check_secrets_ignored(cfg)),
            ("secret mirrors", lambda: check_secret_mirrors(cfg)),
            ("extra checks", lambda: check_extra(cfg)),
            # Wave 1b: the four governance checks, last on purpose. Everything
            # above asks about THIS install; these ask about the records the
            # install keeps about its own history, and they need a config that
            # parsed and a layout that held before they can mean anything.
            ("path coverage", lambda: check_coverage_walk(cfg)),
            ("release authorization", lambda: check_release_authorization(cfg)),
            ("pin violation", lambda: check_pin_violation(cfg)),
            ("role policy integrity", lambda: check_role_policy_integrity(cfg)),
            ("swarm boundary", lambda: check_swarm_boundary(cfg))):
        try:
            run_check()
        except Exception as exc:  # noqa: BLE001 -- naming it IS the check
            record(f"{label} check", False,
                   f"check raised {type(exc).__name__}: {exc}")
    return _summarise()


if __name__ == "__main__":
    sys.exit(main())
