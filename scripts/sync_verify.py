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
import subprocess
import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent
ROOT = AI_DIR.parent
CONFIG_PATH = AI_DIR / "sync_config.json"

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


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)


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
        proc = run(["git", "check-ignore", "-v", target])
        record(f"secret ignored: {target}", proc.returncode == 0,
               proc.stdout.strip() or f"git check-ignore rc={proc.returncode}")


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
        try:
            proc = run(cmd)
        except (OSError, subprocess.TimeoutExpired) as e:
            record(name, False, f"could not run {cmd}: {e}")
            continue
        tail = (proc.stdout + proc.stderr).strip().splitlines()
        evidence = tail[-1][:160] if tail else "(no output)"
        record(name, proc.returncode == 0, f"rc={proc.returncode}; {evidence}")


def main() -> int:
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
