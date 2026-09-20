import pytest
from helpers import make_repo, scaffold

# `.ai/...` paths that must exist for an install to be called installed.
# Every fixture below funnels through this tuple, so a scaffold that exits 0
# without producing an install fails here instead of quietly handing ~44 later
# tests a repo that only looks set up.
INSTALL_SENTINELS = (
    ".ai/state/CURRENT.md",
    ".ai/sync_config.json",
    ".ai/scripts/ai_common.py",
    ".ai/scripts/checkpoint.py",
    ".ai/scripts/sync_verify.py",
)


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo with one commit, not yet scaffolded."""
    return make_repo(tmp_path)


@pytest.fixture
def ai_repo(repo):
    """A freshly scaffolded repo: rc 0, non-empty output, sentinel paths present.

    rc alone proves nothing (the D5 fail-open class is exactly "exit 0, saw
    nothing"), so the fixture — not each individual test — carries the
    existence proof.
    """
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert res.stdout_raw, "scaffold exited 0 without writing any output"
    for rel in INSTALL_SENTINELS:
        assert (repo / rel).exists(), f"{rel} missing after scaffold:\n{res.stdout}"
    return repo


@pytest.fixture
def cp(ai_repo):
    """Path to the copied-in checkpoint.py inside this repo's install.

    Depends on `ai_repo`, not `repo`: this fixture promises an install exists,
    and `run_python` on a nonexistent script returns rc 2 with empty stdout,
    which would let every negative stdout assertion pass vacuously.
    """
    return ai_repo / ".ai" / "scripts" / "checkpoint.py"


@pytest.fixture
def sv(ai_repo):
    """Path to the copied-in sync_verify.py; see `cp` for the ai_repo rationale."""
    return ai_repo / ".ai" / "scripts" / "sync_verify.py"
