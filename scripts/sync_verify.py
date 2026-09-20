#!/usr/bin/env python3
"""One-command sync-system health check (cross-harness-sync skill).

Config-driven; project-specific checks are declared in `.ai/sync_config.json`,
not hardcoded here. Checks, in order:

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
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from ai_common import RepoError, decode, protect_stdio, resolve_roots, \
        run_argv, run_git
except ImportError:
    print("[FAIL] install layout: ai_common.py is missing from .ai/scripts/ — "
          "re-run init_sync.py so the shared primitives are copied in")
    sys.exit(2)

# Assigned by main() from resolve_roots(), never by arithmetic on __file__: D19
# was this pair of paths silently pointing one level too high.
AI_DIR: Path | None = None
ROOT: Path | None = None
CONFIG_PATH: Path | None = None

RESULTS: list[tuple[str, bool, str]] = []

DEFAULT_CONFIG = {
    "budgets": {
        "AGENTS.md": 65,
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


def record(name: str, ok: bool, evidence: str) -> None:
    RESULTS.append((name, ok, evidence))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {evidence}")


def load_config() -> dict:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: cannot read {CONFIG_PATH} ({e}); using built-in defaults")
        cfg = {}
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    return merged


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
        return {ln.split("=", 1)[0].strip()
                for ln in p.read_text(encoding="utf-8").splitlines()
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
        res = run_argv(ROOT, cmd, timeout=600)
        tail = (decode(res.stdout) + decode(res.stderr)).strip().splitlines()
        evidence = tail[-1][:160] if tail else "(no output)"
        record(name, res.ok, f"rc={res.rc}; {evidence}")


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
    cfg = load_config()
    check_required_files()
    check_token_budgets(cfg)
    check_secrets_ignored(cfg)
    check_secret_mirrors(cfg)
    check_extra(cfg)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed ==")
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
