"""spec 6.1 — the pin-violation check: the one falsifiable claim wholly inside
the repo.

An authorization that pins `CURRENT.md`, `TASK.md`, `BLOCKERS.md` or `LATEST.md`
pins a file the protocol rewrites every few minutes, which is the real incident
this check encodes: a routine edit stalled because its own state file was a
pinning target. The rule is about the NAME of the pinned artifact, so the
repo-relative path (`​.ai/state/CURRENT.md`) and the bare name both count.
"""
import json

from helpers import run_python

STATE_FILES = (".ai/state/CURRENT.md", ".ai/state/TASK.md",
               ".ai/state/BLOCKERS.md", ".ai/handoff/LATEST.md")


def _auth(repo, name, editable=("src/app.py",), pinned=(), verdict="accepted"):
    adir = repo / ".ai" / "state" / "authorizations"
    adir.mkdir(parents=True, exist_ok=True)
    lines = [f"# Authorization — {name}", "", "## Editable files", ""]
    lines += [f"- `{p}`" for p in editable]
    if pinned:
        lines += ["", "## Pinned baselines", ""]
        lines += [f"- `{p}`: SHA-256 `{'a' * 64}`" for p in pinned]
    text = "\n".join(lines) + "\n"
    if verdict is not None:
        text += ("\n## Governance\n\n```governance\n"
                 "tier: T2\nexecutor: harness-a/model-1\n"
                 f"reviewer: harness-b/model-2\nverdict: {verdict}\n```\n")
    (adir / f"{name}.md").write_text(text, encoding="utf-8")


def test_every_pinned_state_file_is_a_named_fail(ai_repo, sv):
    for rel in STATE_FILES:
        for stale in (ai_repo / ".ai" / "state" / "authorizations").glob("*.md"):
            stale.unlink()
        _auth(ai_repo, "bad-pin", pinned=(rel,))
        res = run_python(sv, cwd=ai_repo)
        assert res.rc == 1, (rel, res.stdout + res.stderr)
        fails = [ln for ln in res.lines if ln.startswith("[FAIL] pin violation:")]
        assert len(fails) == 1, (rel, res.lines)
        assert rel.rsplit("/", 1)[-1] in fails[0], fails[0]


def test_a_frozen_artifact_pin_passes(ai_repo, sv):
    _auth(ai_repo, "good-pin", pinned=("data/frozen-input.csv",))
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    assert any(ln.startswith("[PASS] pin violation:") for ln in res.lines), res.lines


def test_no_authorizations_is_a_named_skip(ai_repo, sv):
    adir = ai_repo / ".ai" / "state" / "authorizations"
    # The installer creates the directory (spec 6: it is the canonical home
    # v2.0 never gave the records); what makes the check skip is that it holds
    # no stage record. Wave 1b's `--migrate`/install DOES put `INDEX.md` there
    # (it is a required file now), and `_authorization_records()` skips it by
    # name — so the honest form of "no record" is "nothing but the index".
    assert [p.name for p in adir.glob("*.md")] == ["INDEX.md"], \
        list(adir.iterdir())
    res = run_python(sv, cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    skips = [ln for ln in res.lines if ln.startswith("[SKIP] pin violation:")]
    assert len(skips) == 1, res.lines
    assert "no-authorizations" in skips[0], skips[0]


def test_the_pinned_baselines_heading_only_line_is_not_a_pin(ai_repo, sv):
    """The shipped template's explanatory bullet sits under `## Pinned
    baselines` and NAMES all four state files in prose. Reading that as a pin
    would make every fresh authorization red for quoting the rule."""
    body = ("# Authorization — template-shaped\n\n## Editable files\n\n"
            "- `src/app.py`\n\n## Pinned baselines\n\n"
            "- `<path>`: SHA-256 `<hash>` (one per line)\n"
            "- Only frozen artifacts may be pinned. NEVER pin `CURRENT.md`, "
            "`TASK.md`,\n  `BLOCKERS.md`, or `LATEST.md` — they change too fast.\n")
    adir = ai_repo / ".ai" / "state" / "authorizations"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "quote.md").write_text(body, encoding="utf-8")
    cfg_path = ai_repo / ".ai" / "sync_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["protected_paths"] = []
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    res = run_python(sv, cwd=ai_repo)
    assert not any(ln.startswith("[FAIL] pin violation:")
                   for ln in res.lines), res.lines
