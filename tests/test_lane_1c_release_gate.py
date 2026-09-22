"""Wave 1c C4: the release face needs its own authority, and it is not a stage note.

`protected_paths` answers "was this stage allowed to edit files in its own tree".
That is not "did anyone accept shipping these files to other people", and until this
lane the same list answered both, so a repository that happens to host the product
could certify its own publication by writing a record in `.ai/state/authorizations/`.
Wave 1b's dogfood did exactly that to its own `scripts/` and `templates/`.

The load-bearing case is the pending record (C4-3): an unreviewed stage must not be
able to publish by asserting its own verdict, so `is_accepted()` is the only door.
"""
from __future__ import annotations

import json

from helpers import git, run_python

GOV = ("```governance\ntier: T2\nexecutor: test/executor\n"
       "reviewer: test/reviewer\nverdict: %s\n"
       "red_before_green: true\nuser_authorized: true\n```\n")


def setup(repo, **keys):
    """Register a release face, commit a change to it, and anchor the window."""
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "scripts").mkdir(exist_ok=True)
    (repo / "scripts" / "engine.py").write_text("X = 1\n", encoding="utf-8")
    git(repo, "add", "scripts/engine.py")
    git(repo, "commit", "-q", "-m", "feat: ship an engine")
    cfg_path = repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["protected_paths"] = []          # the runtime face is deliberately out of it
    cfg["governance"] = {"window_start_commit": base}
    cfg.update(keys)
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    git(repo, "add", ".ai/sync_config.json")
    git(repo, "commit", "-q", "-m", "chore: register the release face")
    return base


def empty_release_dir(repo):
    """The directory exists and holds only its index: an empty source, not a missing one."""
    directory = repo / "docs" / "release-authorizations"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "INDEX.md").write_text("# index", encoding="utf-8")
    git(repo, "add", str(directory.relative_to(repo).as_posix()))
    git(repo, "commit", "-q", "-m", "docs: open the release directory")


def write_release_record(repo, verdict, editable="`scripts/*`", name="2026-09-22-ship.md"):
    directory = repo / "docs" / "release-authorizations"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        "# Release authorization\n\n## Editable files\n\n- " + editable + "\n\n"
        + (GOV % verdict if verdict else ""), encoding="utf-8")
    git(repo, "add", str(directory.relative_to(repo).as_posix()))
    git(repo, "commit", "-q", "-m", "docs: authorise the release face")


def run(repo):
    return run_python(repo / ".ai" / "scripts" / "sync_verify.py", [],
                     cwd=repo)


def line(res, prefix):
    return next((ln for ln in res.lines if ln.startswith(prefix)), None)


def test_c4_1_a_release_touch_with_no_record_is_uncovered(ai_repo):
    """Nothing published a change here, so the walk must say so by name.

    The directory exists and holds only its index: an empty authorisation source is
    a different fact from a missing one, which C4-5 tests separately.
    """
    setup(ai_repo, release_paths=["scripts/*"])
    directory = ai_repo / "docs" / "release-authorizations"
    directory.mkdir(parents=True)
    (directory / "INDEX.md").write_text("# index\n", encoding="utf-8")
    git(ai_repo, "add", "docs/release-authorizations/INDEX.md")
    git(ai_repo, "commit", "-q", "-m", "docs: create the release index")
    res = run(ai_repo)
    found = line(res, "[FAIL] release authorization:")
    assert found and "1 uncovered of" in found and "scripts/engine.py" in found, res.lines


def test_c4_2_an_accepted_release_record_covers_it(ai_repo):
    setup(ai_repo, release_paths=["scripts/*"])
    write_release_record(ai_repo, "accepted")
    res = run(ai_repo)
    assert line(res, "[PASS] release authorization:"), res.lines


def test_c4_3_a_pending_record_certifies_nothing(ai_repo):
    """The whole point: the stage cannot publish itself by writing `verdict`.

    A record that says `pending` is one nobody reviewed. If it counted, every stage
    could clear the release gate by editing its own authorization file, which is the
    failure this check exists to close.
    """
    setup(ai_repo, release_paths=["scripts/*"])
    write_release_record(ai_repo, "pending")
    res = run(ai_repo)
    found = line(res, "[FAIL] release authorization:")
    assert found and "1 uncovered of" in found, res.lines
    assert "not accepted" in found, found


def test_c4_4_an_unconfigured_release_face_skips_by_name(ai_repo):
    """A normal project ships nothing; that is an answer, not a failure."""
    setup(ai_repo)
    res = run(ai_repo)
    found = line(res, "[SKIP] release authorization:")
    assert found and "no-release-paths" in found, res.lines


def test_c4_5_a_release_face_with_no_directory_fails(ai_repo):
    """Registering patterns and no authorisation source is a configuration hole."""
    setup(ai_repo, release_paths=["scripts/*"],
          release_authorizations_dir="docs/nowhere-authorizations")
    res = run(ai_repo)
    found = line(res, "[FAIL] release authorization:")
    assert found and "does" in found and "not exist" in found, res.lines


def test_c4_6_an_unreadable_record_is_neither_absent_nor_accepted(ai_repo, tmp_path):
    """cp936 bytes in an authorisation file must not read as an empty directory."""
    setup(ai_repo, release_paths=["scripts/*"])
    write_release_record(ai_repo, "accepted")
    record = (ai_repo / "docs" / "release-authorizations" / "2026-09-22-ship.md")
    record.write_bytes("accept\xe9\r\n".encode("latin-1") + b"\xff\xfe\xfa not utf-8\n")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "test: a record the verifier cannot decode")
    res = run(ai_repo)
    found = line(res, "[FAIL] release authorization:")
    assert found and "unreadable" in found, res.lines


def test_c4_7_a_misspelled_release_set_governs_nothing(ai_repo):
    """`scrips/*` matches nothing, so the walk would report a clean 0 of 0.

    `path coverage` already refuses this shape through `_protected_set_is_void`;
    copying that guard is the point, because a permanently green line is how a typo
    hides. Named SKIP, never PASS.
    """
    setup(ai_repo, release_paths=["scrips/*"])
    empty_release_dir(ai_repo)
    res = run(ai_repo)
    assert line(res, "[PASS] release authorization:") is None, res.lines
    skip = line(res, "[SKIP] release authorization:")
    assert skip and "void-release-set" in skip, res.lines


def test_c4_8_an_anchor_at_the_tip_is_not_a_window(ai_repo):
    """`window = HEAD` makes `HEAD..HEAD` empty, which is a config error wearing a verdict.

    The shape predicate accepts a 40-hex tip, so this passes the older guard and
    books `PASS, 0 touches covered` while an unauthorised shipped commit sits in the
    range the operator meant to write.
    """
    setup(ai_repo, release_paths=["scripts/*"])
    empty_release_dir(ai_repo)
    # The anchor has to BE the tip at run time; taken before setup() commits, the
    # seed sha is merely older than the tip and the window is legitimately empty.
    head = git(ai_repo, "rev-parse", "HEAD").strip()
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["release_window_start_commit"] = head
    cfg_path.write_text(json.dumps(cfg, indent=2) + chr(10), encoding="utf-8")
    res = run(ai_repo)
    assert line(res, "[PASS] release authorization:") is None, res.lines
    bad = line(res, "[FAIL] release authorization:")
    assert bad and "tip" in bad, res.lines


def test_c4_9_the_release_directory_cannot_point_outside_the_repo(ai_repo):
    """One config key retargets the authorisation SOURCE; it must be repo-relative.

    `authorizations_dir` learned this the hard way (an escaping path let one line
    read another tree's records and still print PASS). A new sibling key with the
    same power needs the same refusal on the day it is written, not later.
    """
    setup(ai_repo, release_paths=["scripts/*"],
          release_authorizations_dir="../elsewhere-authorizations")
    res = run(ai_repo)
    assert res.rc == 2, (res.rc, res.lines[-6:])


def test_c4_10_an_unreadable_record_is_not_a_clean_window(ai_repo):
    """Zero touches plus a record we could not read is 'cannot determine', not clean."""
    setup(ai_repo, release_paths=["docs/nosuch/*"])
    write_release_record(ai_repo, "accepted")
    target = ai_repo / "docs" / "release-authorizations" / "2026-09-22-ship.md"
    target.write_bytes(b"\xff\xfe\xfa not utf-8 at all\n")
    git(ai_repo, "add", "-A")
    git(ai_repo, "commit", "-q", "-m", "test: unreadable release record")
    res = run(ai_repo)
    assert line(res, "[PASS] release authorization:") is None, res.lines
    skip = line(res, "[SKIP] release authorization:")
    assert skip and "unreadable" in skip, res.lines
