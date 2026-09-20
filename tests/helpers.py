import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
TEMPLATES_DIR = REPO_ROOT / "templates"


def decode(raw: bytes | None) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", "surrogateescape")


@dataclass
class Result:
    rc: int
    stdout: str
    stderr: str
    stdout_raw: bytes | None

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.stdout.splitlines() if ln.strip()]


def run_python(script: Path, args: Sequence[str] = (), cwd: Path = REPO_ROOT,
               env: dict | None = None) -> Result:
    proc = subprocess.run(
        [sys.executable, str(script), *args], cwd=str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return Result(proc.returncode, decode(proc.stdout), decode(proc.stderr),
                  proc.stdout)


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="surrogateescape")
    assert proc.returncode == 0, f"git {' '.join(args)} -> {proc.stderr}"
    return proc.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "Test Human")
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    return repo


def scaffold(repo: Path, *flags: str) -> Result:
    return run_python(SCRIPTS / "init_sync.py", [str(repo), *flags], cwd=repo)


def write_lock(repo: Path, raw: str) -> Path:
    lock = repo / ".ai" / "runtime" / "WRITER_LOCK.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(raw, encoding="utf-8")
    return lock
