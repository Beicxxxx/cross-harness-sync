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


def test_c4_11_an_anchor_outside_heads_ancestry_governs_nothing(ai_repo):
    """The tip guard was a string compare, so a DESCENDANT anchor emptied the range.

    A side-branch tip or a sha left behind by `git reset` is a well-formed 40-hex
    commit that is not in HEAD's past: `<anchor>..HEAD` then reaches nothing, and the
    walk books `PASS, 0 covered` over a shipped commit no record authorised.
    """
    setup(ai_repo, release_paths=["scripts/*"])
    empty_release_dir(ai_repo)
    git(ai_repo, "checkout", "-q", "-b", "side")
    (ai_repo / "side.txt").write_text("side\n", encoding="utf-8")
    git(ai_repo, "add", "side.txt")
    git(ai_repo, "commit", "-q", "-m", "side branch tip")
    side = git(ai_repo, "rev-parse", "HEAD").strip()
    git(ai_repo, "checkout", "-q", "main")
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["release_window_start_commit"] = side
    cfg_path.write_text(json.dumps(cfg, indent=2) + chr(10), encoding="utf-8")

    res = run(ai_repo)
    assert line(res, "[PASS] release authorization:") is None, res.lines
    bad = line(res, "[FAIL] release authorization:")
    assert bad and "ancestor" in bad, res.lines


def test_c4_12_the_release_directory_cannot_be_the_runtime_one(ai_repo):
    """One line of config must not let a stage note certify a publication.

    `release_authorizations_dir` is repo-relative, so `.ai/state/authorizations`
    passes that test while pointing the release gate at the very directory the split
    exists to keep it away from. That is the whole distinction, dissolved by a
    default-looking string, so it is refused rather than discouraged.
    """
    setup(ai_repo, release_paths=["scripts/*"])
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg["release_authorizations_dir"] = ".ai/state/authorizations"
    cfg_path.write_text(json.dumps(cfg, indent=2) + chr(10), encoding="utf-8")
    res = run(ai_repo)
    assert res.rc == 2, (res.rc, res.lines[-5:])
    assert any("release_authorizations_dir" in ln and "runtime" in ln
               for ln in res.lines), res.lines


def _set_cfg(repo, **keys):
    cfg_path = repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text("utf-8"))
    cfg.update(keys)
    cfg_path.write_text(json.dumps(cfg, indent=2) + chr(10), encoding="utf-8")


def test_c4_13_an_empty_authorisations_directory_stops_the_run(ai_repo):
    """Unusable config, not a FAIL line: rc 2 before any check reads the key.

    There is deliberately no "directory is empty" branch in the check itself — the
    shape refusal happens first, so such a branch would be unreachable code claiming
    to be a guard.
    """
    setup(ai_repo, release_paths=["scripts/*"], release_authorizations_dir="")
    res = run(ai_repo)
    assert res.rc == 2, (res.rc, res.lines[-4:])
    assert any("release_authorizations_dir" in ln for ln in res.lines), res.lines


def test_c4_14_a_non_commit_anchor_fails_rather_than_reading_empty(ai_repo):
    """The shape guard applies to the release window, not only the runtime one."""
    setup(ai_repo, release_paths=["scripts/*"])
    empty_release_dir(ai_repo)
    _set_cfg(ai_repo, release_window_start_commit="HEAD")
    res = run(ai_repo)
    bad = line(res, "[FAIL] release authorization:")
    assert bad and "commit id" in bad, res.lines


def test_c4_15_no_window_at_all_skips_by_name(ai_repo):
    """No anchor anywhere is 'nothing to govern yet', never 'covered'."""
    setup(ai_repo, release_paths=["scripts/*"])
    empty_release_dir(ai_repo)
    _set_cfg(ai_repo, release_window_start_commit="",
             governance={"window_start_commit": ""})
    res = run(ai_repo)
    skip = line(res, "[SKIP] release authorization:")
    assert skip and "no-window" in skip, res.lines


def test_c4_16_a_shallow_history_cannot_certify_a_release(ai_repo, tmp_path):
    """Truncated history cannot tell 'never authorised' from 'authorised, object gone'.

    `--no-local` matters: a plain-path clone is hardlinked and stays a full
    repository, and the first cut of this test therefore passed by walking an
    ordinary history while claiming to test a shallow one. `is_shallow_true` asks
    git directly rather than importing the shipped module — putting `scripts/` on
    sys.path leaked into `test_ai_common.py`, which checks that an installed script
    loads the `ai_common` beside it.
    """
    setup(ai_repo, release_paths=["scripts/*"])
    empty_release_dir(ai_repo)
    git(ai_repo, "add", ".ai")
    git(ai_repo, "commit", "-q", "-m", "test: commit the install for cloning")
    shallow = tmp_path / "shallow"
    git(ai_repo, "clone", "--quiet", "--no-local", "--depth", "1",
        str(tmp_path / "project"), str(shallow))
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "true", \
        "the clone is not shallow; this would certify nothing about truncated history"
    _set_cfg(shallow, release_paths=["scripts/*"])
    res = run_python(shallow / ".ai" / "scripts" / "sync_verify.py", [], cwd=shallow)
    bad = line(res, "[FAIL] release authorization:")
    assert bad and "shallow" in bad, res.lines
