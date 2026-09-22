"""Wave 1d D-lane: the copy that RUNS must be the copy that SHIPS.

`.ai/scripts/*.py` is what governs an installing repository — every check a green
run reports is executed from those bytes, not from `scripts/*.py`. Wave 1c edited
the source twice and hand-copied it over, going green both times, and nothing in
the verifier could tell a faithful copy from a stale one. Path coverage cannot
answer this either: it asks whether an edit was authorised, and a record that
names both walks authorises a mismatch as readily as a match.

The discrimination this lane has to get right is "which tree is this". An ordinary
install has no `scripts/` inside the checkout at all, and one that does (a project
with its own `scripts/` directory) must not be held to a comparison its install
never made. `scripts/init_sync.py` is the witness: it is the one file in that
directory the installer never copies into `.ai/scripts/`, so its presence says
"this tree is the skill's own checkout" rather than "this tree happens to have a
scripts directory".
"""
from __future__ import annotations

import shutil

from helpers import run_python

INSTALLED = (".ai/scripts/ai_common.py", ".ai/scripts/checkpoint.py",
             ".ai/scripts/sync_verify.py")


def promote(repo):
    """Turn the fixture into a source checkout: twins first, then the witness.

    Copies byte-for-byte from the install itself, so the PASS case compares real
    pairs rather than files this test authored.
    """
    (repo / "scripts").mkdir(exist_ok=True)
    for rel in INSTALLED:
        src = repo / rel
        if src.is_file():
            shutil.copy2(str(src), str(repo / "scripts" / src.name))
    # The installer is never installed; its presence is what this check reads as
    # "the source tree", so a fixture that wants that answer has to write it.
    (repo / "scripts" / "init_sync.py").write_text("# installer\n",
                                                   encoding="utf-8")


def write_source(repo, name, text):
    (repo / "scripts" / name).write_text(text, encoding="utf-8")


def run(repo):
    return run_python(repo / ".ai" / "scripts" / "sync_verify.py", [], cwd=repo)


def line(res, prefix):
    return next((ln for ln in res.lines if ln.startswith(prefix)), None)


def test_d_1_a_drifted_installed_copy_is_named_and_red(ai_repo):
    """The defect as published: the running verifier is not the shipped one."""
    promote(ai_repo)
    write_source(ai_repo, "sync_verify.py", "# drifted: source moved, copy did not\n")
    res = run(ai_repo)
    found = line(res, "[FAIL] governing copy:")
    assert found and ".ai/scripts/sync_verify.py" in found, res.lines
    assert "scripts/sync_verify.py" in found, found


def test_d_2_identical_copies_pass_and_say_how_many(ai_repo):
    promote(ai_repo)
    res = run(ai_repo)
    found = line(res, "[PASS] governing copy:")
    assert found and "3 installed files" in found, res.lines


def test_d_3_an_ordinary_install_skips_by_name(ai_repo):
    """No source checkout here, so there is no comparison to fail.

    The fixture's install has `.ai/scripts/` and no in-tree `scripts/`; a project
    that keeps its own code in a directory of that name is covered by D-5.
    """
    res = run(ai_repo)
    found = line(res, "[SKIP] governing copy:")
    assert found and "not-source-checkout" in found, res.lines


def test_d_4_a_copy_with_no_source_twin_is_red(ai_repo):
    """The installed half of a pair can be deleted from the source walk instead
    of edited, which strands a file that runs with no author anywhere."""
    promote(ai_repo)
    (ai_repo / "scripts" / "checkpoint.py").unlink()
    res = run(ai_repo)
    found = line(res, "[FAIL] governing copy:")
    assert found and "checkpoint.py" in found, res.lines
    assert "no source twin" in found, found


def test_d_5_a_source_file_that_was_never_installed_is_not_drift(ai_repo):
    """`scripts/` holds more than the install copies; only the running side is held.

    Without this case the check's cheap reading — compare both directories — makes
    `init_sync.py` itself a permanent FAIL in the only tree where the check runs.
    """
    promote(ai_repo)
    write_source(ai_repo, "engine.py", "# shipped, never installed\n")
    res = run(ai_repo)
    assert line(res, "[PASS] governing copy:"), res.lines


def test_d_6_an_unreadable_side_fails_rather_than_skipping(ai_repo):
    """Fail-closed, on the wave-1c rule: a file this host denies is not a file
    that matched.

    The unreadable side is the SOURCE, not the installed copy: `sync_verify.py`
    imports `ai_common` from `.ai/scripts/` before any check runs, so an
    uninstallable install there exits rc 2 and this line never prints — which is
    its own answer, and not the one this case is about. A directory stands in for
    a denied read because it raises the same `OSError` on every platform; a real
    ACL denial is unverifiable on this host.
    """
    promote(ai_repo)
    twin = ai_repo / "scripts" / "ai_common.py"
    twin.unlink()
    twin.mkdir()
    res = run(ai_repo)
    found = line(res, "[FAIL] governing copy:")
    assert found and "ai_common.py" in found, res.lines
    assert "could not be read" in found, found


def test_d_7_a_stranger_named_init_sync_is_not_reported_as_a_verdict(ai_repo):
    """The witness is a filename, and a filename can collide (review finding).

    A project that owns its own `scripts/init_sync.py` — a deploy script, say — is
    an ordinary install. Under the single-file witness alone it was read as the
    skill's checkout and answered `[FAIL] governing copy: 3 of 3 installed files
    are not the bytes their source says`, a red it cannot configure away and has no
    way to interpret. The tightened answer also requires an installed name to appear
    in `scripts/` — but that condition cannot tell "this is not the checkout" from
    "the source half of the checkout was deleted", and the first version of its
    message asserted the one reading anyway. So the token names the ambiguity, and
    neither reading is booked as a pass.
    """
    (ai_repo / "scripts").mkdir(exist_ok=True)
    (ai_repo / "scripts" / "init_sync.py").write_text("# my own deploy script\n",
                                                      encoding="utf-8")
    res = run(ai_repo)
    found = line(res, "[SKIP] governing copy:")
    assert found and "undecidable-source-walk" in found, res.lines
    assert "cannot tell" in found, found
    assert "this tree is an install" not in found, found
    assert not any(ln.startswith("[FAIL] governing copy:") for ln in res.lines), \
        res.lines


def test_d_9_one_drifted_twin_alone_is_still_a_fail(ai_repo):
    """The case no other test reaches: `scripts/` holds exactly one installed name,
    and it is the drifted one.

    Zero shared names is an ambiguous tree (D-7); one shared name is the checkout,
    so the single comparison the check exists to make must still be reported. A
    variant of `shared` that compared digests instead of names passed the whole lane
    while flipping exactly this tree from FAIL to SKIP, which is what showed the case
    was missing rather than that the mutant was clever.
    """
    promote(ai_repo)
    for name in ("ai_common.py", "checkpoint.py"):
        (ai_repo / "scripts" / name).unlink()
    write_source(ai_repo, "sync_verify.py", "# drifted, and the only twin left\n")
    res = run(ai_repo)
    found = line(res, "[FAIL] governing copy:")
    assert found and "digests to" in found, res.lines
    assert ".ai/scripts/sync_verify.py" in found, found
