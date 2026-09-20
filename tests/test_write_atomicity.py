"""Task 5: lock writes are atomic and two writers cannot share one temp name
(D8, D9).

The old `write_json` wrote `STATUS.tmp` / `WRITER_LOCK.tmp` — one name per
target, so two local writers overwrote each other's partial file — and then
moved it with shutil's move, which is not atomic on Windows (`os.rename` raises
when the target exists, so it degrades to copy+unlink and can leave a truncated
tracked file behind). The two source-text checks below are the specification
pins; the concurrency test is the behavioural one.

The third and fourth tests pin what that fix exposed: on Windows a concurrent
`os.replace` makes both the replacing call and the paired read fail
transiently, so both go through one bounded retry.
"""
import importlib.util
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from helpers import SCRIPTS, run_python

CHECKPOINT = SCRIPTS / "checkpoint.py"


def shutil_copy(name, dest_dir):
    shutil.copy2(str(SCRIPTS / name), str(dest_dir / name))


def _load_checkpoint(name):
    """Load scripts/checkpoint.py as a module so write_json can be pinned."""
    spec = importlib.util.spec_from_file_location(name, CHECKPOINT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tmp_names_used_by_the_repo_source():
    text = CHECKPOINT.read_text(encoding="utf-8")
    return "with_suffix(\".tmp\")" in text or "with_suffix('.tmp')" in text


def test_write_json_no_longer_shares_one_tmp_name():
    assert not _tmp_names_used_by_the_repo_source()


def test_os_replace_is_used_for_the_tracked_lock():
    text = CHECKPOINT.read_text(encoding="utf-8")
    assert "os.replace" in text and "shutil.move" not in text


def test_a_sharing_denial_is_retried_and_still_lands(tmp_path, monkeypatch):
    """WinError 5 on the replace is what two live writers really produce here.

    The retry must recover, not swallow: the last check proves a permanent
    denial still raises and leaves no temp file behind.
    """
    mod = _load_checkpoint("cp_atomic_retry")
    target = tmp_path / "STATUS.json"
    real_replace = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied", str(dst))
        real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", flaky)
    mod.write_json(target, {"checkpoint_count": 1})
    assert json.loads(target.read_text("utf-8")) == {"checkpoint_count": 1}
    assert len(calls) == 3, calls

    def always_denied(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(mod.os, "replace", always_denied)
    with pytest.raises(PermissionError):
        mod.write_json(target, {"checkpoint_count": 2})
    temps = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert temps == [], f"write_json leaked temp files: {temps}"


def test_the_paired_read_retries_too(tmp_path, monkeypatch):
    """Replacing a file makes reading it transiently fail on Windows.

    This is the failure the traced children actually died of
    (`PermissionError: [Errno 13] ... STATUS.json` inside
    read_json_or_error), so retrying only the writer moved the crash, it did
    not remove it.
    """
    mod = _load_checkpoint("cp_atomic_read")
    target = tmp_path / "STATUS.json"
    mod.write_json(target, {"checkpoint_count": 7})

    real_read = Path.read_bytes
    reads = []

    def flaky_read(self):
        reads.append(str(self))
        if len(reads) < 3:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", flaky_read)
    data, err = mod.read_json_or_error(target)
    assert err is None, err
    assert data == {"checkpoint_count": 7}, data
    assert len(reads) == 3, reads


def test_concurrent_status_writes_leave_valid_json(tmp_path):
    """D9: two local writers used to clobber each other's single .tmp file.

    V-5's consequence, applied HERE rather than to the gate: the bare checkpoint
    now classifies the checkout before it writes, so an install in a directory git
    cannot resolve is refused (rc 1, nothing written) exactly as `--lock` had
    already refused it. The fixture is therefore a real repository, which is what
    every other state-writing test in this suite already runs against; the local
    import keeps this file's import block untouched.
    """
    from helpers import make_repo
    root = make_repo(tmp_path)
    ai = root / ".ai" / "scripts"
    ai.mkdir(parents=True)
    for name in ("checkpoint.py", "ai_common.py"):
        shutil_copy(name, ai)
    target = root / ".ai" / "runtime" / "STATUS.json"
    target.parent.mkdir()

    results = []

    def one(i):
        # run_python, not a hand-rolled subprocess: the hermetic env is applied
        # for us and cannot be forgotten here.
        results.append(run_python(ai / "checkpoint.py", ["--agent", f"a{i}"],
                                  cwd=root))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, range(8)))

    data = json.loads(target.read_text("utf-8-sig"))
    assert data["checkpoint_count"] >= 1, data
    failed = [f"rc={r.rc} stderr-tail:\n{r.stderr.strip()[-500:]}"
              for r in results if r.rc]
    assert not failed, f"{len(failed)} of {len(results)} writers failed:\n{failed}"
    assert any("Checkpoint #" in r.stdout for r in results), \
        [r.stdout + r.stderr for r in results]
    temps = [p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")]
    assert temps == [], f"write_json leaked temp files: {temps}"
