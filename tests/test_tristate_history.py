"""Three-valued history probes: TRUE / FALSE / UNKNOWN, and UNKNOWN never collapses.

Measured on this host's git (spec §6's numbers, re-verified here):
`merge-base --is-ancestor` -> 0 / 1 / 128 for ancestor / present-but-not-ancestor /
cannot-determine; `cat-file -e <absent>^{commit}` -> **128** (not 1, which is why
`commit_exists` splits rc 128 on shallowness instead of answering TRUE-or-UNKNOWN for
every absent commit); `rev-parse --verify <absent>` -> 0 while echoing the string, the
probe §6 rejects. The asymmetry is the point: ancestry for an sha git cannot resolve is
UNKNOWN, existence for the same sha in a whole repository is FALSE, and no boolean
carries both facts.
"""
import importlib.util
import sys

import pytest

from helpers import SCRIPTS, git, make_repo


def _load(name):
    # Registered under a private name only while the module executes (see
    # tests/test_ai_common.py finding C): binding the repo copy as `ai_common`
    # makes an in-process load of an INSTALLED script import this object instead
    # of the file that ships.
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "ai_common.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    try:
        spec.loader.exec_module(m)
    finally:
        sys.modules.pop(name, None)
    return m


ai = _load("_b0_tri_ai_common")

ABSENT_SHA = "0" * ai.SHA_HEX_LEN
# `core.quotepath` (default true) makes git C-quote non-ASCII paths, so without `-z`
# this directory arrives as `"...303\251..."`. A double quote would be a harsher test
# and is not available here: `"`, control chars and leading/trailing spaces are illegal
# in a Windows filename, so a fixture that needs them could only ever run on one host.
ODD_DIR = "docs-with-é"


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path)


def test_real_head_is_ancestor_of_itself_and_exists(repo):
    head = git(repo, "rev-parse", "HEAD")
    assert ai.git_ancestor(repo, head, head) == "TRUE"
    assert ai.commit_exists(repo, head) == "TRUE"


def test_absent_sha_is_two_different_answers_not_one(repo):
    """rc-128 ancestry stays UNKNOWN while rc-128 existence, in a whole repo, is FALSE."""
    head = git(repo, "rev-parse", "HEAD")
    assert ai.commit_exists(repo, ABSENT_SHA) == "FALSE"
    assert ai.git_ancestor(repo, ABSENT_SHA, head) == "UNKNOWN"
    assert ai.git_ancestor(repo, head, ABSENT_SHA) == "UNKNOWN"


def test_a_blob_id_is_not_a_commit(repo):
    """`^{commit}` is load-bearing: the bare id exists, as that type it does not."""
    blob = git(repo, "rev-parse", "HEAD:README.md")
    assert ai.commit_exists(repo, blob) == "FALSE"


def test_present_but_not_ancestor_is_false_not_unknown(repo):
    """rc 1 is a real answer: the histories diverged, and saying so is decidable."""
    git(repo, "checkout", "-q", "-b", "side")
    (repo / "side.txt").write_text("side\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "on side")
    side = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    (repo / "main.txt").write_text("main\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "on main")
    main_head = git(repo, "rev-parse", "HEAD")

    assert ai.git_ancestor(repo, side, main_head) == "FALSE"
    assert ai.git_ancestor(repo, f"{side}~1", main_head) == "TRUE"


def test_is_shallow_answers_for_an_ordinary_repo(repo):
    assert ai.is_shallow(repo) == "FALSE"


@pytest.mark.posix
def test_shallow_clone_turns_ancestry_into_unknown(tmp_path):
    """The end-to-end shallow case: a truncated history must not answer FALSE.

    POSIX-only: `file://` cloning is the portable half and the Windows half is the
    one this wave has no fixture for. The marker is enforced by conftest, so the
    test cannot "pass" by asserting about a platform it is not on — which matters
    here, because its assertions are measured on git behaviour this host cannot
    reproduce.
    """
    src = make_repo(tmp_path / "src")
    (src / "one.txt").write_text("1\n", encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "first")
    first = git(src, "rev-parse", "HEAD")
    (src / "two.txt").write_text("2\n", encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "second")
    tip = git(src, "rev-parse", "HEAD")

    shallow = tmp_path / "shallow"
    git(src, "clone", "-q", "--depth", "1", "--", src.as_uri(), str(shallow))

    assert ai.is_shallow(shallow) == "TRUE"
    assert ai.commit_exists(shallow, tip) == "TRUE"
    assert ai.git_ancestor(shallow, first, tip) == "UNKNOWN"


def _res(rc=0, timed_out=False):
    return ai.GitResult(rc=rc, stdout=b"", stderr=b"", timed_out=timed_out)


def test_tri_keeps_every_unexpected_rc_as_unknown():
    """128 and friends are 'cannot determine'; only 0 and 1 are evidence."""
    def yes_when_zero(rc):
        return rc == 0

    assert ai._tri(_res(rc=0), yes_when_zero) == "TRUE"
    assert ai._tri(_res(rc=1), yes_when_zero) == "FALSE"
    for rc in (2, 127, 128, 129, 255):
        assert ai._tri(_res(rc=rc), yes_when_zero) == "UNKNOWN", rc


def test_tri_treats_a_timeout_as_unknown_even_at_rc_zero():
    """A killed git leaves whatever it flushed; rc alone cannot be trusted."""
    assert ai._tri(_res(rc=0, timed_out=True), lambda rc: rc == 0) == "UNKNOWN"
    assert ai._tri(_res(rc=1, timed_out=True), lambda rc: rc == 0) == "UNKNOWN"


def test_tri_honours_the_callers_polarity():
    """`rev-list --count` style probes want rc 1 to be the yes; the reduction is shared."""
    assert ai._tri(_res(rc=1), lambda rc: rc == 1) == "TRUE"
    assert ai._tri(_res(rc=0), lambda rc: rc == 1) == "FALSE"


def test_log_paths_returns_nul_records_and_the_caller_splits_them(repo):
    """§6.3 pass 1: with `--pretty=format:%H` each record is `sha \\n first path`."""
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("a\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add doc")
    head = git(repo, "rev-parse", "HEAD")

    paths, err = ai.log_paths(
        repo, ["--no-merges", "--full-history", "--pretty=format:%H"], ["docs"])
    assert err is None
    assert paths == [f"{head}\ndocs/a.md"], paths
    # ... which is why a coverage walk cannot read this list as bare paths:
    sha, _, first_path = paths[0].partition("\n")
    assert (sha, first_path) == (head, "docs/a.md")


def test_log_paths_distinguishes_no_commits_from_failure(repo):
    """Empty is a real answer; a failed query is None plus a named reason."""
    paths, err = ai.log_paths(repo, ["--no-merges", "--full-history"],
                              ["no-such-dir"])
    assert err is None
    assert paths == []

    bad_paths, bad_err = ai.log_paths(repo, ["--no-merges", "definitely-not-a-ref"],
                                      ["docs"])
    assert bad_paths is None
    assert bad_err and "git log" in bad_err, bad_err


def test_log_paths_survives_a_quoting_hostile_path(repo):
    """`-z` is why this works: the path git would otherwise C-quote arrives whole."""
    (repo / ODD_DIR).mkdir()
    (repo / ODD_DIR / "n.md").write_text("n\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "odd path")

    paths, err = ai.log_paths(
        repo, ["--no-merges", "--full-history", "--pretty=format:%H"], [ODD_DIR])
    assert err is None
    assert any(p.endswith(f"{ODD_DIR}/n.md") for p in paths), paths
    assert not any(p.startswith('"') or "\\303" in p for p in paths), paths
