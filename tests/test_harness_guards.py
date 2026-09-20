"""Harness guards: the platform markers must filter, and no helper may reach
the real repository.

Two cheap belt-and-braces closures, neither of which is the fix for the
cross-drive `cd` + `git add -A` incident disclosed in task-1-report.md (that was
an operator error, not a helper bug), but both of which made the blast radius
bigger than it needed to be:

  * `pytest.ini` declares the `posix` / `windows` markers, and nothing anywhere
    reads them. A later `@pytest.mark.posix` therefore silently does nothing on
    Windows: the test runs, and "passes" by asserting about a platform it is not
    on. `tests/conftest.py` now turns the declared markers into real skips.
  * `helpers.run_python` defaulted `cwd` to `REPO_ROOT`, so a call that forgot
    the argument ran a shipped script with the live repository as its working
    directory, and `helpers.git` accepted any path — including the repository
    under test, whose `.git` a test could stage, commit into, or rewrite.

Assertions here are positive (a named exception message, a named skip marker)
rather than "nothing was printed".
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import conftest
import pytest
from helpers import (REPO_ROOT, SCRIPTS, TEMPLATES_DIR, git, is_inside_repo,
                     make_repo, run_python)


# --------------------------------------------------------------------------
# the posix / windows markers must actually filter


def test_pytest_ini_declares_both_platform_markers():
    """The hook below keys off these names, so a rename has to break something."""
    text = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert re.search(r"^\s{4}posix:\s*\S", text, re.M), text
    assert re.search(r"^\s{4}windows:\s*\S", text, re.M), text


@pytest.mark.parametrize("platform_name,expected", [
    ("nt", "posix"),      # Windows runs the `windows` tests only
    ("posix", "windows"),  # Linux/macOS runs the `posix` tests only
])
def test_the_marker_that_must_be_skipped_is_the_other_platforms(
        platform_name, expected):
    assert conftest.platform_skip_marker(platform_name) == expected


class _StubItem:
    """Just enough of `pytest.Item` for the collection hook: marker lookup plus
    a record of what the hook added."""

    def __init__(self, name: str, markers: tuple[str, ...]):
        self.name = name
        self.markers = set(markers)
        self.added: list = []

    def get_closest_marker(self, name: str):
        if name in self.markers:
            return type("M", (), {"name": name})()
        return None

    def add_marker(self, marker) -> None:
        self.added.append(marker)


def _run_hook(monkeypatch, platform_name: str, items):
    monkeypatch.setattr(conftest, "_current_platform", lambda: platform_name)
    conftest.pytest_collection_modifyitems(object(), items)
    return {it.name: it.added for it in items}


def test_the_collection_hook_skips_only_the_foreign_platform_tests(monkeypatch):
    items = [_StubItem("posix_one", ("posix",)),
             _StubItem("windows_one", ("windows",)),
             _StubItem("unmarked", ())]
    added = _run_hook(monkeypatch, "nt", items)

    assert [m.name for m in added["posix_one"]] == ["skip"], added
    reason = added["posix_one"][0].mark.kwargs["reason"]
    assert "posix" in reason and "nt" in reason, reason
    assert added["windows_one"] == [], added
    assert added["unmarked"] == [], added

    on_posix = _run_hook(monkeypatch, "posix", [
        _StubItem("posix_one", ("posix",)), _StubItem("windows_one", ("windows",))])
    assert on_posix["posix_one"] == [], on_posix
    assert [m.name for m in on_posix["windows_one"]] == ["skip"], on_posix


@pytest.mark.posix
def test_posix_marker_probe_does_not_execute_on_windows():
    """Reaching the body on Windows means the markers are still decorative."""
    raise AssertionError(f"posix-marked test executed on os.name={os.name!r}")


@pytest.mark.windows
def test_windows_marker_probe_executes_here():
    assert os.name == "nt", os.name


# --------------------------------------------------------------------------
# helpers must not be able to touch the repository under test


def test_is_inside_repo_answers_for_the_root_and_its_children():
    assert is_inside_repo(REPO_ROOT) is True
    assert is_inside_repo(TEMPLATES_DIR) is True
    assert is_inside_repo(Path(__file__)) is True
    assert is_inside_repo(str(REPO_ROOT / "scripts")) is True
    assert is_inside_repo(REPO_ROOT.parent) is False
    # a sibling whose NAME starts with the same characters is not "inside"
    assert is_inside_repo(Path(str(REPO_ROOT) + "-sibling")) is False


def test_git_helper_refuses_the_repository_under_test():
    """The point of the guard: no test may let git write into this checkout."""
    for target in (REPO_ROOT, REPO_ROOT / "scripts"):
        with pytest.raises(RuntimeError) as excinfo:
            git(target, "rev-parse", "--show-toplevel")
        message = str(excinfo.value)
        assert "refusing to run git" in message, message
        assert "cross-harness-sync" in message, message


def test_git_helper_still_serves_a_throwaway_repo(tmp_path):
    """The guard is scoped to this checkout, not to every path on purpose."""
    repo = make_repo(tmp_path)
    out = git(repo, "rev-parse", "--show-toplevel")
    assert Path(out).resolve() == repo.resolve(), out


def test_make_repo_refuses_to_build_inside_the_checkout():
    """Refused before anything is created, so no nested repo appears here."""
    with pytest.raises(RuntimeError) as excinfo:
        make_repo(REPO_ROOT / "scratch-fixture")
    assert "refusing to build a fixture repo" in str(excinfo.value), excinfo.value
    assert not (REPO_ROOT / "scratch-fixture").exists(), "the guard came too late"
    assert not (REPO_ROOT / "scratch-fixture" / "project").exists()


def test_run_python_has_no_default_cwd():
    """A forgotten `cwd=` used to mean "run inside the live repository"."""
    with pytest.raises(TypeError) as excinfo:
        run_python(SCRIPTS / "sync_verify.py")
    message = str(excinfo.value)
    assert "cwd" in message, message
