"""The on-disk governance RECORDS (spec §6 format, §8's canonical home).

Two things had no answer in v2.0: the authorization template declared tiers and
reviewers in PROSE that no checker could read, and the protocol mandated "one
stage = one authorization file" while giving those files no home that anything
required or read. Wave 1b closes both — a fenced `## Governance` block in the
template, and `.ai/state/authorizations/` with an `INDEX.md` that is now a
required file.

The required-file flip and the template that fills it ship in ONE commit, so no
install can be required to have a file nothing creates.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from helpers import SCRIPTS, TEMPLATES_DIR, run_python, scaffold

INDEX_REL = ".ai/state/authorizations/INDEX.md"
RECORD_KEYS = ("tier", "executor", "reviewer", "verdict")


def _load(name: str, path: Path):
    saved = sys.modules.pop("ai_common", None)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
        sys.modules.pop("ai_common", None)
        if saved is not None:
            sys.modules["ai_common"] = saved
    return mod


ai_common = _load("_b3_records_ai_common", SCRIPTS / "ai_common.py")


# ---------------------------------------------------------------------------
# the template's `## Governance` block


def test_the_authorization_template_carries_a_parseable_governance_block():
    text = (TEMPLATES_DIR / "AUTHORIZATION.md").read_text("utf-8")
    assert "## Governance" in text, text
    fields, err = ai_common.parse_governance_block(text)
    assert err is None, err
    assert fields is not None, "the template carries no ```governance block"
    for key in RECORD_KEYS:
        assert key in fields, (key, fields)
        assert fields[key].strip(), (key, fields)
    # `red_before_green` / `user_authorized` are the "where applicable" pair the
    # format names; the template spells them out so a T3 stage has something to
    # edit rather than invent.
    assert "red_before_green" in fields, fields
    assert "user_authorized" in fields, fields
    assert "```governance" in text and text.count("```") >= 2, text


def test_the_templates_governance_values_are_fillable_not_fabricated():
    """A copied-but-untouched template must not read as an accepted record.

    The sanctioned sentinels (`n/a`, `NOT_REPORTED`) are what makes that true
    while keeping the block PARSEABLE — an unfilled `<...>` value is fatal to the
    parser by design, so it could not be used here without making the shipped
    template an unreadable file.
    """
    text = (TEMPLATES_DIR / "AUTHORIZATION.md").read_text("utf-8")
    fields, _err = ai_common.parse_governance_block(text)
    assert fields is not None, fields
    assert fields["verdict"].lower() != "accepted", fields
    assert "<" not in "".join(fields.values()), fields


def test_a_record_copied_from_the_template_is_decidable(ai_repo):
    """The point of the block: the verifier can read a real record's verdict.

    `swarm boundary` must answer with a counted record rather than the
    `SKIP(no-verdict: ...)` a blockless (or verdict-less) document gets — the
    SKIP token B1 ships for "undecided" must not fire on a template-shaped but
    complete record, or every governed install reads as undecided.
    """
    dest = ai_repo / ".ai/state/authorizations/2026-09-21-stage.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text((TEMPLATES_DIR / "AUTHORIZATION.md").read_text("utf-8"),
                    encoding="utf-8")
    res = run_python(ai_repo / ".ai/scripts/sync_verify.py", [], cwd=ai_repo)
    swarm = [ln for ln in res.lines if ln.startswith(("[PASS] swarm boundary",
                                                      "[SKIP] swarm boundary",
                                                      "[FAIL] swarm boundary"))]
    assert len(swarm) == 1, res.lines
    assert "no-verdict" not in swarm[0], swarm[0]
    assert "0 accepted" in swarm[0], swarm[0]
    assert not any(ln.startswith("[FAIL] pin violation") for ln in res.lines), \
        res.lines
    assert "[PASS] pin violation" in "\n".join(res.lines), res.lines


# ---------------------------------------------------------------------------
# the INDEX: created on a fresh install, required, and never read as a record


def test_a_fresh_install_creates_the_index_and_the_list_requires_it():
    assert INDEX_REL in ai_common.DEFAULT_REQUIRED_FILES, \
        ai_common.DEFAULT_REQUIRED_FILES
    shipped = json.loads(
        (TEMPLATES_DIR / "sync_config.json").read_text("utf-8"))
    assert INDEX_REL in shipped["required_files"], shipped["required_files"]
    assert shipped["authorizations_dir"] == ".ai/state/authorizations", shipped


def test_the_index_lands_in_the_authorizations_dir_on_init(tmp_path):
    repo = tmp_path / "project"
    repo.mkdir(parents=True)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    index = repo / INDEX_REL
    assert index.is_file(), res.lines
    assert index.stat().st_size > 0, "an empty required file is a FAIL"
    # the directory's `.gitkeep` (D16) still exists beside it: a second tracked
    # file in that directory is what `test_second_machine.py` walks a clone for.
    assert (repo / ".ai/state/authorizations/.gitkeep").is_file()


def test_the_index_is_not_read_as_an_authorization_record(ai_repo, sv):
    """`INDEX.md` is a table of contents; fabricating a record from one would
    invent an audit source (spec 6 keeps it, §8 creates it)."""
    assert (ai_repo / INDEX_REL).is_file()
    res = run_python(sv, [], cwd=ai_repo)
    assert any(ln.startswith("[PASS] required " + INDEX_REL)
               for ln in res.lines), res.lines
    assert any(ln.startswith("[SKIP] pin violation: SKIP(no-authorizations)")
               for ln in res.lines), res.lines
    assert any("0 accepted authorizations" in ln for ln in res.lines
               if ln.startswith("[SKIP] swarm boundary")
               or ln.startswith("[PASS] swarm boundary")), res.lines


def test_the_required_file_flip_moves_the_fresh_install_count_exactly(ai_repo,
                                                                      sv):
    """The count B1 baselined at `== 19/23 checks passed, 4 skipped ==`, then
    `20/24` at the required-file flip, is now `21/25`: wave 1c's
    `unfilled template slots` is one more check and one more PASS, and still
    NO new skip.

    Exact and positive on purpose (wave 1a's ruling). This is the tripwire the
    required-file flip is supposed to pull — B4 re-measures it against the
    merged tree, and a fourth skip here would mean the index arrived without
    anything writing it. It has now pulled twice: a fifth check arriving without
    the installer filling the slots it owns would read as a new SKIP here.
    """
    res = run_python(sv, [], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    summary = [ln for ln in res.lines if "checks passed" in ln]
    assert len(summary) == 1, res.lines
    assert summary[0] == "== 21/25 checks passed, 4 skipped ==", summary[0]



# ------------------------------------------------ one walk, one verdict -----
#
# I-4's predicate half: the file list and the accepted test both live in
# `ai_common` now, so what `sync_verify` counts is exactly what
# `checkpoint --review-prompt` prints. The behaviour half — a nested record the
# verifier used to see and the reviewer did not — is pinned in
# `tests/test_review_prompt.py::test_the_verifier_and_the_review_prompt_see_the_same_records`.


def test_the_record_walk_is_flat_and_keeps_the_index_out(ai_repo):
    """Flat `*.md`, index aside (case-insensitively), nothing else.

    The nested entry is the I-4 asymmetry: `rglob` in one reader and `glob` in the
    other meant the same directory held two different record sets. One flat walk
    is now the only answer either command can give, and
    `templates/authorizations/INDEX.md` documents exactly that layout.
    """
    adir = ai_repo / ".ai" / "state" / "authorizations"
    assert (adir / "INDEX.md").is_file(), "the fixture install has no index"
    # A directory whose only entries are the index and a `.gitkeep` is an EMPTY
    # record set: that is what keeps a fresh install reading as "no live stage"
    # rather than as one, in both readers.
    assert ai_common.authorization_records(adir) == [], \
        [p.as_posix() for p in ai_common.authorization_records(adir)]
    (adir / "b-stage.md").write_text("b\n", encoding="utf-8")
    (adir / "a-stage.md").write_text("a\n", encoding="utf-8")
    (adir / "notes.txt").write_text("not a record\n", encoding="utf-8")
    (adir / "sub").mkdir()
    (adir / "sub" / "nested.md").write_text("nested\n", encoding="utf-8")

    got = ai_common.authorization_records(adir)
    assert [p.name for p in got] == ["a-stage.md", "b-stage.md"], \
        [p.as_posix() for p in got]


def test_accepted_is_one_normalised_predicate_for_both_readers():
    """`verdict: Accepted `, `verdict: accepted`, and nothing else (spec 6)."""
    assert ai_common.is_accepted({"verdict": "accepted"}) is True
    assert ai_common.is_accepted({"verdict": "  ACCEPTED  "}) is True
    assert ai_common.is_accepted({"verdict": "pending"}) is False
    assert ai_common.is_accepted({"verdict": "rejected"}) is False
    assert ai_common.is_accepted({}) is False
    assert ai_common.is_accepted(None) is False, \
        "a legacy record with no governance block is never accepted"
