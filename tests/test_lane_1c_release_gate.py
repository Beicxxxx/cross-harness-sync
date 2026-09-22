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
