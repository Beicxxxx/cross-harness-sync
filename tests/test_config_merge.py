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
    Lane S1's finding 2 added the half a replace cannot express: the merge may
    replace, and `sync_verify.REQUIRED_FILE_FLOOR` is then unioned back in, so
    the five files with no necessity check elsewhere are outside the key's
    reach. End-to-end pins for that live in `test_required_files.py`.

Two more things this file pins, both from lane S1: `merge_config` also returns
the set of budget names declined with an explicit `null` (finding 5 — the
merged dict cannot tell "no cap" from "cap declined" once the key is gone, so
the opt-out left no trace), and it deep-copies the defaults (finding 7 — an
unnamed key used to hand back `DEFAULT_CONFIG`'s own containers).

The three merge behaviours are pinned as units on `merge_config()` (so an
unknown key cannot inherit the wrong policy by accident) and the floors are
pinned end-to-end through the CLI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import load_script, run_python


sync_verify = load_script("sync_verify.py",
                          "_sync_verify_under_test_config_merge")


def write_cfg(repo: Path, data) -> None:
    (repo / ".ai" / "sync_config.json").write_text(
        json.dumps(data), encoding="utf-8")


def merge(defaults, user):
    """`merge_config` answers `(merged, nulled)`; unit tests want the dict."""
    return sync_verify.merge_config(defaults, user)[0]


# --------------------------------------------------------------------------
# the policy table itself


def test_every_governed_key_is_declared_and_replace_is_the_default():
    assert sync_verify.MERGE_POLICY["budgets"] == sync_verify.MERGE_DEEP
    assert sync_verify.MERGE_POLICY["secret_files"] == sync_verify.MERGE_UNION
    assert sync_verify.MERGE_POLICY["required_files"] == sync_verify.MERGE_REPLACE
    # The brief's DEEP_MERGE_KEYS stays importable, derived from the one table.
    # Wave 1b adds the second deep key BY CONTRACT (`governance`, so naming
    # `window_start_commit` cannot delete a sibling anchor the migrator wrote) and
    # names `protected_paths` as an explicit replace key; the pin therefore names
    # the whole table instead of freezing wave 1a's single-entry count.
    assert set(sync_verify.DEEP_MERGE_KEYS) == {"budgets", "governance"}
    assert sync_verify.MERGE_POLICY["governance"] == sync_verify.MERGE_DEEP
    assert sync_verify.MERGE_POLICY["protected_paths"] == sync_verify.MERGE_REPLACE
    assert merge({"extra_checks": [{"name": "a", "cmd": ["x"]}]},
                 {"extra_checks": []})["extra_checks"] == []


def test_deep_merge_keeps_every_cap_the_user_did_not_name():
    merged = merge({"budgets": {"a": 1, "b": 2}}, {"budgets": {"b": 9, "c": 3}})
    assert merged["budgets"] == {"a": 1, "b": 9, "c": 3}, merged


def test_a_null_budget_entry_is_an_explicit_opt_out():
    """Deep merge must not make a default impossible to decline. `null` is the
    considered, per-entry form of "this install has no such file" (what D18's
    `--no-agents-block` prune needs to keep working), and it cannot erase the
    other caps the way D3's one-key rewrite did."""
    merged, nulled = sync_verify.merge_config({"budgets": {"a": 1, "b": 2}},
                                              {"budgets": {"a": None}})
    assert merged["budgets"] == {"b": 2}, merged
    assert nulled == {"a"}, nulled
    # nulling something that was never a default is inert, not an added entry
    inert = sync_verify.merge_config({"budgets": {"a": 1}}, {"budgets": {"z": None}})
    assert inert[0]["budgets"] == {"a": 1}, inert[0]


def test_the_nulled_set_is_the_only_trace_an_opt_out_learns_about():
    """Finding 5: the checks read the MERGED dict, in which a declined cap and a
    cap that was never there look identical. `nulled` is what lets
    `check_line_budgets` tell a considered act from a deleted template line."""
    merged, nulled = sync_verify.merge_config(
        {"budgets": {"AGENTS.md": 65, "a": 1}},
        {"budgets": {"AGENTS.md": None, "b": 5}})
    assert nulled == {"AGENTS.md"}, nulled
    assert "AGENTS.md" not in merged["budgets"], merged
    assert sorted(merged["budgets"]) == ["a", "b"], merged
    # a config that says nothing declines nothing
    assert sync_verify.merge_config({"budgets": {"a": 1}}, {})[1] == set()


def test_merge_does_not_hand_back_the_default_containers():
    """Finding 7: `dict(defaults)` is a SHALLOW copy, so every key the user did
    not name came back aliasing `DEFAULT_CONFIG`'s own list/dict. Three tests in
    this batch call `load_config()` in-process, so the first `.pop()` or
    `.append()` would have poisoned the module default for the rest of the run."""
    first, _ = sync_verify.merge_config(sync_verify.DEFAULT_CONFIG, {})
    first["budgets"]["injected"] = 1
    first["required_files"].append("INJECTED.md")
    first["secret_files"].append("INJECTED.env")
    assert "injected" not in sync_verify.DEFAULT_CONFIG["budgets"], \
        "merge_config aliased DEFAULT_CONFIG['budgets']"
    assert "INJECTED.md" not in sync_verify.DEFAULT_CONFIG["required_files"], \
        "merge_config aliased DEFAULT_CONFIG['required_files']"
    assert "INJECTED.env" not in sync_verify.DEFAULT_CONFIG["secret_files"], \
        "merge_config aliased DEFAULT_CONFIG['secret_files']"
    second, _ = sync_verify.merge_config(sync_verify.DEFAULT_CONFIG, {})
    assert second["budgets"] == sync_verify.DEFAULT_CONFIG["budgets"], second
    assert second["required_files"] == \
        sync_verify.DEFAULT_CONFIG["required_files"], second


def test_the_built_in_budgets_cover_the_protocol_files_and_no_other_file():
    """`AGENTS.md` is installer-owned (D18 prunes it, D27 raises it), so a
    built-in default would resurrect a budget the install declined. It is in
    `BUDGET_FLOOR` instead, which asks only that a PRESENT AGENTS.md carry a cap
    or an explicit null."""
    assert sync_verify.DEFAULT_CONFIG["budgets"] == {
        ".ai/state/CURRENT.md": 60,
        ".ai/handoff/LATEST.md": 80,
        ".ai/handoff/NEXT_PROMPT.md": 100,
        ".ai/state/DECISIONS_INDEX.md": 110,
    }, sync_verify.DEFAULT_CONFIG["budgets"]
    assert sync_verify.BUDGET_FLOOR == tuple(
        sync_verify.DEFAULT_CONFIG["budgets"]) + ("AGENTS.md",)


def test_union_adds_to_the_secret_floor_and_cannot_drop_it():
    merged = merge({"secret_files": [".env"]}, {"secret_files": ["prod.env", ".env"]})
    assert merged["secret_files"] == [".env", "prod.env"], merged
    # The D3 shape: naming a new secret must not un-check the default one, and
    # an explicit empty list is not a way to disable the floor either.
    assert ".env" in merge({"secret_files": [".env"]},
                           {"secret_files": ["prod.env"]})["secret_files"]
    assert merge({"secret_files": [".env"]},
                 {"secret_files": []})["secret_files"] == [".env"]


def test_replace_is_what_happens_to_a_required_files_override():
    """A repo with no decision log must be able to say so — one entry, exactly
    the entry it named, with nothing from the default list left behind IN THE
    MERGE. The floor is unioned later, in `check_required_files`, so the
    evidence line can name which entries came back from it (finding 2)."""
    merged = merge({"required_files": ["a.md", "b.md"]}, {"required_files": ["only.md"]})
    assert merged["required_files"] == ["only.md"], merged


def test_the_scalar_keys_are_shape_checked_too():
    """`decisions_file` and `decisions_max_active_entries` are unlisted keys, so
    they used to reach the checks unvalidated and escape as TypeErrors."""
    for bad in ({"decisions_file": None}, {"decisions_file": 5},
                {"decisions_max_active_entries": "20"},
                {"decisions_max_active_entries": True},
                {"decisions_max_active_entries": 0},
                {"decisions_max_active_entries": -1}):
        with pytest.raises(sync_verify.ConfigError) as excinfo:
            sync_verify.merge_config(sync_verify.DEFAULT_CONFIG, bad)
        assert str(excinfo.value).startswith("malformed:"), bad
        assert "decisions" in str(excinfo.value), (bad, excinfo.value)


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
    a cap that vanishes from the config while its file is still there is a
    named gap rather than a shorter run."""
    write_cfg(ai_repo, {"budgets": {".ai/state/CURRENT.md": 60}})
    res = run_python(sv, cwd=ai_repo)
    # AGENTS.md is present in this install and this config no longer caps it,
    # which is finding 5's shape: the gap has to cost the run its green.
    assert res.rc == 1, res.stdout
    assert budget_names(res) == {
        ".ai/state/CURRENT.md",
        ".ai/handoff/LATEST.md",
        ".ai/handoff/NEXT_PROMPT.md",
        ".ai/state/DECISIONS_INDEX.md",
        "AGENTS.md",
        "DECISIONS active entries",
    }, res.lines
    assert any(ln.startswith("[FAIL] budget AGENTS.md") and "no cap in config" in ln
               for ln in res.lines), res.lines
