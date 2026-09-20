"""Task 2 (D3): config merge is per-key, and one key cannot erase a floor.

`load_config()` used to do `merged.update(cfg)`, so a single user key replaced
the whole default value for that key. That is correct for some keys and a
fail-open for others, and the two demands are opposite:

  * `budgets` — an **install shape**: which files this project keeps, and to
    what cap. A custom cap must not silently un-monitor the other four files
    (D3's symptom), so this key deep-merges.
  * `secret_files` — a **governance floor**: `.env` is a secret in every
    project that ships the protocol. One config edit must not be able to
    un-check it, which is exactly what a replace would allow, so this key
    unions.
  * `required_files` — an **install shape** again: a repo that legitimately
    has no decision log or no authorization records must be able to say so, so
    this key replaces. Replace is also the default for every unlisted key.

The three behaviours are pinned as units on `merge_config()` (so an unknown key
cannot inherit the wrong policy by accident) and the two floors are pinned
end-to-end through the CLI.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from helpers import SCRIPTS, run_python


def _load_sync_verify():
    """The repo's `sync_verify.py`, loaded under a private name.

    Importing it runs its own `from ai_common import ...`, which registers the
    repo copy under the shared name; that value is restored so an in-process
    load in another test file still executes the install next to it.
    """
    saved = sys.modules.pop("ai_common", None)
    name = "_sync_verify_under_test_config_merge"
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / "sync_verify.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.modules.pop(name, None)
        sys.modules.pop("ai_common", None)
        if saved is not None:
            sys.modules["ai_common"] = saved


sync_verify = _load_sync_verify()


def write_cfg(repo: Path, data) -> None:
    (repo / ".ai" / "sync_config.json").write_text(
        json.dumps(data), encoding="utf-8")


# --------------------------------------------------------------------------
# the policy table itself


def test_every_governed_key_is_declared_and_replace_is_the_default():
    assert sync_verify.MERGE_POLICY["budgets"] == sync_verify.MERGE_DEEP
    assert sync_verify.MERGE_POLICY["secret_files"] == sync_verify.MERGE_UNION
    assert sync_verify.MERGE_POLICY["required_files"] == sync_verify.MERGE_REPLACE
    # The brief's DEEP_MERGE_KEYS stays importable, derived from the one table.
    assert sync_verify.DEEP_MERGE_KEYS == ("budgets",)
    merged = sync_verify.merge_config({"extra_checks": [{"name": "a", "cmd": ["x"]}]},
                             {"extra_checks": []})
    assert merged["extra_checks"] == [], merged


def test_deep_merge_keeps_every_cap_the_user_did_not_name():
    merged = sync_verify.merge_config({"budgets": {"a": 1, "b": 2}},
                                      {"budgets": {"b": 9, "c": 3}})
    assert merged["budgets"] == {"a": 1, "b": 9, "c": 3}, merged


def test_a_null_budget_entry_is_an_explicit_opt_out():
    """Deep merge must not make a default impossible to decline. `null` is the
    considered, per-entry form of "this install has no such file" (what D18's
    `--no-agents-block` prune needs to keep working), and it cannot erase the
    other caps the way D3's one-key rewrite did."""
    merged = sync_verify.merge_config({"budgets": {"a": 1, "b": 2}},
                                      {"budgets": {"a": None}})
    assert merged["budgets"] == {"b": 2}, merged
    # nulling something that was never a default is inert, not an added entry
    assert sync_verify.merge_config({"budgets": {"a": 1}},
                                    {"budgets": {"z": None}})["budgets"] == {"a": 1}


def test_the_built_in_budgets_cover_the_protocol_files_and_no_other_file():
    """`AGENTS.md` is installer-owned (D18 prunes it, D27 raises it), so a
    built-in default would resurrect a budget the install declined."""
    assert sync_verify.DEFAULT_CONFIG["budgets"] == {
        ".ai/state/CURRENT.md": 60,
        ".ai/handoff/LATEST.md": 80,
        ".ai/handoff/NEXT_PROMPT.md": 100,
        ".ai/state/DECISIONS_INDEX.md": 110,
    }, sync_verify.DEFAULT_CONFIG["budgets"]


def test_union_adds_to_the_secret_floor_and_cannot_drop_it():
    merged = sync_verify.merge_config({"secret_files": [".env"]},
                             {"secret_files": ["prod.env", ".env"]})
    assert merged["secret_files"] == [".env", "prod.env"], merged
    # The D3 shape: naming a new secret must not un-check the default one, and
    # an explicit empty list is not a way to disable the floor either.
    assert ".env" in sync_verify.merge_config(
        {"secret_files": [".env"]}, {"secret_files": ["prod.env"]})["secret_files"]
    assert sync_verify.merge_config({"secret_files": [".env"]},
                           {"secret_files": []})["secret_files"] == [".env"]


def test_replace_is_what_happens_to_a_required_files_override():
    """A repo with no decision log must be able to say so — one entry, exactly
    the entry it named, with nothing from the default list left behind."""
    merged = sync_verify.merge_config({"required_files": ["a.md", "b.md"]},
                             {"required_files": ["only.md"]})
    assert merged["required_files"] == ["only.md"], merged


# --------------------------------------------------------------------------
# end-to-end: the same two facts through the installed CLI


def test_user_budget_entry_does_not_erase_other_caps(ai_repo, sv):
    """D3: one custom cap used to replace all five defaults."""
    (ai_repo / ".ai" / "state" / "CURRENT.md").write_text(
        "\n".join(f"line {i}" for i in range(90)), encoding="utf-8")
    write_cfg(ai_repo, {"budgets": {".ai/handoff/LATEST.md": 5}})
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1
    assert any(ln.startswith("[FAIL] budget .ai/state/CURRENT.md")
               for ln in res.lines), res.lines


def test_user_secret_files_still_covers_env(ai_repo, sv):
    """The union must ADD prod.env to the list, not replace it. `.env` itself
    PASSES because init_sync writes it into .gitignore, so git check-ignore
    succeeds — asserting FAIL here would demand the opposite of correct."""
    write_cfg(ai_repo, {"secret_files": ["prod.env"]})
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 1, res.stdout
    assert any(ln.startswith("[PASS] secret ignored: .env")
               for ln in res.lines), res.lines
    assert any(ln.startswith("[FAIL] secret ignored: prod.env")
               for ln in res.lines), res.lines


def budget_names(res) -> set[str]:
    """The set of files the run actually monitored, read off its own lines."""
    out = set()
    for ln in res.lines:
        if ln.startswith(("[PASS] budget ", "[FAIL] budget ")):
            out.add(ln.split("] budget ", 1)[1].split(":")[0])
    return out


def test_which_files_get_a_budget_is_decided_by_config_plus_the_floor(ai_repo, sv):
    """A config that names one cap still monitors the four protocol files, and
    monitors nothing the installer never declared — both halves at once, read
    off the run's own evidence lines."""
    write_cfg(ai_repo, {"budgets": {".ai/state/CURRENT.md": 60}})
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout
    assert budget_names(res) == {
        ".ai/state/CURRENT.md",
        ".ai/handoff/LATEST.md",
        ".ai/handoff/NEXT_PROMPT.md",
        ".ai/state/DECISIONS_INDEX.md",
        "DECISIONS active entries",
    }, res.lines
