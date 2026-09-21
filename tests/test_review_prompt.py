"""Task B2: `checkpoint.py --review-prompt` emits exactly three blocks.

Spec §6.4's point is that the honest review path is the CHEAP one: a reviewer
gets {the active authorization, the diff, the verify output} and nothing else,
instead of re-running the executor's full suite or reading the whole tree. So
the contract under test here is mostly about SHAPE — three delimited blocks, in
order, with nothing outside them — and about the two ways a prompt-generator
lies: an empty block that reads as "nothing to review", and a stubbed block that
reads as "the verifier ran".

Consequently every assertion is positive: a named header, a named reason, or a
line taken from the child that really ran. The verify block is asserted by
comparison with an INDEPENDENT direct run of `sync_verify.py` in the same tree
(its own `checks passed` summary line, or, when the verifier itself cannot
answer, this command's named `[VERIFY HALT`), never by a green count — a count
would tie this file to another lane's check list.
"""
import json
import re
import time

from helpers import git, run_python

HEADERS = ("== REVIEW PROMPT: AUTHORIZATION ==",
           "== REVIEW PROMPT: DIFF ==",
           "== REVIEW PROMPT: VERIFY ==")
NO_AUTH = "[NO ACTIVE AUTHORIZATION]"
VERIFY_HALT = "[VERIFY HALT"
GOV_ACCEPTED = ("```governance\n"
                "tier: T2\n"
                "executor: codex\n"
                "reviewer: claude-code\n"
                "verdict: accepted\n"
                "```\n")


def _sections(res):
    """The three block bodies, asserting the shape that makes them blocks.

    Ordered, each header exactly once, nothing printed before the first one, and
    no fourth header anywhere: that is what "exactly three and nothing else"
    means, and it is the only place the promise is checkable.
    """
    text = res.stdout
    assert text.lstrip().startswith(HEADERS[0]), \
        f"--review-prompt printed a preamble before block 1:\n{text[:400]}"
    positions = []
    for header in HEADERS:
        assert text.count(header) == 1, \
            f"{header!r} appeared {text.count(header)} times:\n{text}"
        positions.append(text.index(header))
    assert positions == sorted(positions), \
        f"blocks out of order (authorization, diff, verify is the contract):\n{text}"
    assert len(re.findall(r"(?m)^== REVIEW PROMPT:", text)) == 3, \
        f"a fourth block appeared:\n{text}"
    bodies = {}
    for i, header in enumerate(HEADERS):
        start = positions[i] + len(header)
        end = positions[i + 1] if i + 1 < len(HEADERS) else len(text)
        bodies[header] = text[start:end]
    for header, body in bodies.items():
        assert body.strip(), f"{header} is an empty block, which reads as 'clean'"
    return bodies


def _write_auth(repo, name, text):
    d = repo / ".ai" / "state" / "authorizations"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def _set_config(repo, **top_level):
    path = repo / ".ai" / "sync_config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(top_level)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def test_three_blocks_in_order_and_rc_zero(ai_repo, cp):
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, f"rc {res.rc}:\n{res.stdout}\n{res.stderr}"
    assert res.stdout_raw, "rc 0 with no output is the D5 fail-open shape"
    _sections(res)


def test_no_active_authorization_is_named_not_silent(ai_repo, cp):
    """A fresh install has no authorization record; the block says so BY NAME."""
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    body = _sections(res)[HEADERS[0]]
    assert NO_AUTH in body, \
        f"zero authorizations must print the named branch, got:\n{body}"
    assert body.strip(), "the named branch may not be an empty block"


def test_accepted_authorization_is_shown_in_full(ai_repo, cp):
    marker = f"UNIQUE-AUTH-BODY-{int(time.time())}"
    _write_auth(ai_repo, "0001-stage.md",
                f"# Authorization -- stage\n\n{marker}\n\n## Editable files\n\n"
                "- `scripts/x.py`\n\n## Governance\n" + GOV_ACCEPTED)
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    body = _sections(res)[HEADERS[0]]
    assert marker in body, f"the active authorization's text is missing:\n{body}"
    assert "0001-stage.md" in body, f"the record is not identified:\n{body}"
    assert NO_AUTH not in body, f"a live record was not found:\n{body}"


def test_expired_authorization_is_not_promoted_as_active(ai_repo, cp):
    _write_auth(ai_repo, "0001-stage.md",
                "# Authorization -- stale\n\nbody\n\n## Governance\n"
                "```governance\n"
                "tier: T2\n"
                "verdict: accepted\n"
                "expires_at: 2000-01-01T00:00:00+00:00\n"
                "```\n")
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    body = _sections(res)[HEADERS[0]]
    assert NO_AUTH in body, f"an expired record printed as active:\n{body}"
    assert "expired" in body.lower(), \
        f"the expiry must be the NAMED reason, not a silent drop:\n{body}"


def test_legacy_record_without_governance_block_is_shown_and_named(ai_repo, cp):
    """§6: an absent governance block is a named degradation, never a PASS."""
    marker = f"LEGACY-BODY-{int(time.time())}"
    _write_auth(ai_repo, "0000-legacy.md",
                f"# Authorization -- legacy\n\n{marker}\n")
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    body = _sections(res)[HEADERS[0]]
    assert marker in body, f"the legacy record must still be shown:\n{body}"
    assert "governance: absent" in body, \
        f"the missing governance block must be named:\n{body}"


def test_verify_block_carries_the_child_real_output(ai_repo, cp, sv):
    """The verify block embeds what `sync_verify.py` actually printed.

    The direct run above is the witness: the line asserted into the block is
    taken from that child's own stdout, so a stubbed or re-implemented block
    cannot satisfy it whatever another lane's check list looks like.
    """
    direct = run_python(sv, cwd=ai_repo)
    summary = next((ln.strip() for ln in direct.stdout.splitlines()
                    if "checks passed" in ln), None)
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, f"rc {res.rc}:\n{res.stdout}\n{res.stderr}"
    body = _sections(res)[HEADERS[2]]
    assert "sync_verify.py" in body, f"the block never names its child:\n{body}"
    assert "exit rc=" in body, \
        f"the child's exit code must be on screen, not inferred:\n{body}"
    if summary:
        assert summary in body, \
            f"the verifier's real summary {summary!r} is absent:\n{body}"
    else:
        assert VERIFY_HALT in body, \
            f"no summary line and no named halt:\n{body}"


def test_diff_block_names_a_real_window_and_the_patch(ai_repo, cp):
    """With no `governance` key the window falls back — and SAYS so."""
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    body = _sections(res)[HEADERS[1]]
    assert "HEAD~1" in body, f"the fallback window is not named:\n{body}"
    assert "governance.window_start_commit" in body, \
        f"the fallback must say WHICH key was unset:\n{body}"


def test_diff_block_uses_the_recorded_window(ai_repo, cp):
    window = git(ai_repo, "rev-parse", "HEAD")
    (ai_repo / "worker.py").write_text("print('changed')\n", encoding="utf-8")
    git(ai_repo, "add", "worker.py")
    git(ai_repo, "commit", "-q", "-m", "lane: one commit after the window")
    _set_config(ai_repo, governance={"window_start_commit": window})
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, f"rc {res.rc}:\n{res.stdout}\n{res.stderr}"
    body = _sections(res)[HEADERS[1]]
    assert window in body, f"the recorded window sha is not named:\n{body}"
    assert "worker.py" in body, \
        f"the commit under review is not in the diff:\n{body}"
    assert "HEAD~1" not in body, f"a recorded window must not fall back:\n{body}"


def test_diff_block_names_why_when_git_cannot_answer(ai_repo, cp):
    """A window the clone does not have is a NAMED halt, not an empty diff."""
    _set_config(ai_repo, governance={"window_start_commit": "0" * 40})
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    body = _sections(res)[HEADERS[1]]
    assert "0000000" in body, f"the unusable window must be named:\n{body}"
    assert "[DIFF" in body, \
        f"an undiffable window must print a named reason:\n{body}"
