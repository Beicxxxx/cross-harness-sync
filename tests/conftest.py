import pytest
from helpers import SCRIPTS, TEMPLATES_DIR, make_repo, scaffold


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one commit, not yet scaffolded."""
    return make_repo(tmp_path)


@pytest.fixture
def ai_repo(repo):
    """A freshly scaffolded repo. Asserts the v2.0 green-scaffold baseline."""
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    return repo


@pytest.fixture
def cp(repo):
    """Path to the copied-in checkpoint.py inside this repo's install."""
    return repo / ".ai" / "scripts" / "checkpoint.py"


@pytest.fixture
def sv(repo):
    return repo / ".ai" / "scripts" / "sync_verify.py"
