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

Three further pins carry the contract's edges: the command writes no byte
anywhere under `.ai` (the claim its ungated dispatch rests on), two live
authorization records print as `[AMBIGUOUS AUTHORIZATION]` instead of one of
them winning a sort order, and a missing verifier exits 2 with `[VERIFY HALT`
inside block 3 — the only non-zero code the rc contract allows.
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


def _ai_tree(repo):
    """`{path: bytes}` for every file under `.ai` except CPython's own caches.

    The whole install, because "writes nothing" is a claim about bytes and the
    cheapest place to check it without missing a side effect is everywhere the
    command could put one. `__pycache__` is the one exclusion: block 3 launches
    the verifier, which IMPORTS `ai_common`, so a `.pyc` appearing there is
    CPython's artifact from importing a module — not protocol state, and not
    something a read-only command can be asked to prevent. The run below pins
    `PYTHONDONTWRITEBYTECODE` so the child does not create one either; this
    filter is what keeps the assertion measuring the command, not the
    interpreter's leftovers from a test that ran earlier in this fixture.
    """
    base = repo / ".ai"
    return {p.relative_to(base).as_posix(): p.read_bytes()
            for p in sorted(base.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


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


def test_two_accepted_records_are_named_ambiguous(ai_repo, cp):
    """Spec 6's N1 shape reached through the review tool: two live authorizations.

    Quietly showing whichever file this machine's sort order returned first
    reopens the concurrency gap with the very tool meant to make it visible, so
    all of them print and the ambiguity is named. rc stays 0: a named ambiguity
    is a complete answer, and rc 2 is reserved for the block that cannot be
    produced at all.
    """
    first = f"AMBIGUOUS-ONE-{int(time.time())}"
    second = f"AMBIGUOUS-TWO-{int(time.time())}"
    _write_auth(ai_repo, "0001-alpha.md",
                f"# Authorization -- alpha\n\n{first}\n\n## Governance\n"
                + GOV_ACCEPTED)
    _write_auth(ai_repo, "0002-beta.md",
                f"# Authorization -- beta\n\n{second}\n\n## Governance\n"
                + GOV_ACCEPTED)
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, f"rc {res.rc}:\n{res.stdout}\n{res.stderr}"
    body = _sections(res)[HEADERS[0]]
    assert "[AMBIGUOUS AUTHORIZATION]" in body, \
        f"two accepted records must print the named branch:\n{body}"
    assert "0001-alpha.md" in body and "0002-beta.md" in body, \
        f"the named branch must list every contender:\n{body}"
    assert first in body and second in body, \
        f"neither record may be dropped:\n{body}"
    assert NO_AUTH not in body, \
        f"an ambiguous tree is not an unauthorized one:\n{body}"


def test_recorded_expiry_is_shown_but_never_gates_active(ai_repo, cp):
    """Predicate ruling: "active" is `verdict == accepted` plus `status != closed`,
    and nothing else.

    `expires_at` is D10's WRITER-LOCK field, not one of spec 6's authorization
    record keys, and `sync_verify.py`'s swarm count does not read it — so a
    record this command called stale while the verifier called it live would put
    two answers to "what is authorized" on one tree with nothing to check them
    against. The date is still printed, because a reviewer can weigh it and a
    predicate must not swallow it.

    `status` IS read, by both readers, for the opposite reason: it is the
    record's own claim that its stage is finished, which the verifier's boundary
    answers with. A claim this command ignored would be the same contradiction
    in the other direction.
    """
    marker = f"PAST-EXPIRY-{int(time.time())}"
    _write_auth(ai_repo, "0001-stage.md",
                f"# Authorization -- time-boxed\n\n{marker}\n\n## Governance\n"
                "```governance\n"
                "tier: T2\n"
                "verdict: accepted\n"
                "expires_at: 2000-01-01T00:00:00+00:00\n"
                "```\n")
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, res.stdout + res.stderr
    body = _sections(res)[HEADERS[0]]
    assert marker in body, \
        f"a verdict-accepted record must print as active:\n{body}"
    assert "0001-stage.md" in body, f"the record is not identified:\n{body}"
    assert "2000-01-01T00:00:00+00:00" in body, \
        f"the recorded expiry must stay on screen as detail:\n{body}"
    assert NO_AUTH not in body, \
        f"the block both showed and denied the record:\n{body}"


def test_a_closed_stage_is_not_the_active_authorization_printed(ai_repo, cp):
    """The reviewer must be shown the live scope, not a finished one.

    Two accepted records used to mean `[AMBIGUOUS AUTHORIZATION]` with both texts
    printed, which is right for a swarm and wrong for a repository that has simply
    run two stages one after the other. `status: closed` distinguishes them, so
    the closed stage must drop out of the count here exactly as it does in
    `swarm boundary`, and its text must not be passed off as the live scope.
    """
    live_marker = f"LIVE-STAGE-{int(time.time())}"
    closed_marker = f"CLOSED-STAGE-{int(time.time())}"
    _write_auth(ai_repo, "0001-done.md",
                f"# Authorization -- done\n\n{closed_marker}\n\n## Governance\n"
                "```governance\ntier: T2\nverdict: accepted\nstatus: closed\n```\n")
    _write_auth(ai_repo, "0002-live.md",
                f"# Authorization -- live\n\n{live_marker}\n\n## Governance\n"
                + GOV_ACCEPTED)
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, f"rc {res.rc}:\n{res.stdout}\n{res.stderr}"
    body = _sections(res)[HEADERS[0]]
    assert "[AMBIGUOUS AUTHORIZATION]" not in body, \
        f"a finished stage is not a second live writer:\n{body}"
    assert "active authorization: .ai/state/authorizations/0002-live.md" in body, \
        body
    assert live_marker in body and closed_marker not in body, \
        f"only the live record's text may print as the scope:\n{body}"
    # ... but the spent record is still NAMED: "one live and one spent" is a
    # different fact from "one", and a silent omission is how a reviewer starts
    # believing the set is complete.
    assert "[closed stage authorization]" in body and "0001-done.md" in body, \
        f"the closed record vanished from the prompt:\n{body}"
    assert NO_AUTH not in body, body


def test_a_tree_whose_only_accepted_record_is_closed_says_so(ai_repo, cp):
    """Named, not silently green and not an empty block.

    `status: closed` takes a record out of the live count, so a tree holding no
    open stage must report `[NO ACTIVE AUTHORIZATION]` and name the closed record
    as the reason -- otherwise the reviewer reads "no authorization" where the
    tree says "the stage that had one is finished".
    """
    _write_auth(ai_repo, "0001-done.md",
                "# Authorization -- done\n\nCLOSED-ONLY\n\n## Governance\n"
                "```governance\ntier: T2\nverdict: accepted\nstatus: closed\n```\n")
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 0, f"rc {res.rc}:\n{res.stdout}\n{res.stderr}"
    body = _sections(res)[HEADERS[0]]
    assert NO_AUTH in body, body
    assert "0001-done.md" in body, body
    assert "finished stage" in body, \
        f"the reason must distinguish closed from declined:\n{body}"


def test_review_prompt_writes_no_bytes_anywhere(ai_repo, cp):
    """The load-bearing "reads only" invariant, measured rather than asserted.

    `cmd_review_prompt` is dispatched OUTSIDE `_guard_state_writes` precisely
    because it writes nothing — no STATUS.json bump, no ACTIVE_AGENT, no lock —
    which is also what lets a reviewer run it on a tree another agent holds.
    STATUS.json is seeded with known bytes first: a file that never existed
    "staying absent" proves less than a file that survives a byte-for-byte
    comparison, and the run must complete (three blocks, rc 0) for the
    comparison to mean the command actually ran.
    """
    status = ai_repo / ".ai" / "runtime" / "STATUS.json"
    seeded = json.dumps({"session": "seeded-for-the-read-only-run",
                         "last_agent": "codex"}) + "\n"
    # write_bytes, not write_text: on Windows text mode would translate the
    # newline and the byte comparison below would measure the fixture.
    status.write_bytes(seeded.encode("utf-8"))
    runtime_dir = ai_repo / ".ai" / "runtime"
    lock = runtime_dir / "WRITER_LOCK.json"
    active = runtime_dir / "ACTIVE_AGENT"
    assert not lock.exists() and not active.exists(), \
        "the fixture already carries lock state, so its absence proves nothing"
    before = _ai_tree(ai_repo)
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo,
                     env={"PYTHONDONTWRITEBYTECODE": "1"})
    assert res.rc == 0, f"rc {res.rc}:\n{res.stdout}\n{res.stderr}"
    _sections(res)
    assert status.read_bytes() == seeded.encode("utf-8"), \
        "--review-prompt rewrote runtime/STATUS.json"
    after = _ai_tree(ai_repo)
    assert after == before, \
        "the read set changed the install: " + "; ".join(
            sorted(f"{k} {'added' if k not in before else ('removed' if k not in after else 'rewritten')}"
                   for k in set(before) | set(after)
                   if before.get(k) != after.get(k)))
    assert not active.exists(), "--review-prompt created runtime/ACTIVE_AGENT"
    assert not lock.exists(), "--review-prompt took the writer lock"


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


def test_no_verifier_means_rc_two_and_a_named_halt(ai_repo, cp):
    """The failure side of the exit-code contract: block 3 is not skippable.

    With the verifier gone there is no child output to embed, so the block
    carries its named halt instead of an empty body and the process exits 2 —
    the difference between "the review prompt is incomplete" and "the review
    prompt checked nothing", which is exactly what rc must not let a caller
    collapse.
    """
    (ai_repo / ".ai" / "scripts" / "sync_verify.py").unlink()
    res = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert res.rc == 2, \
        f"a tree with no verifier must exit 2, got {res.rc}:\n{res.stdout}\n{res.stderr}"
    body = _sections(res)[HEADERS[2]]
    assert VERIFY_HALT in body, f"the rc-2 path must name its halt:\n{body}"
    assert "sync_verify.py" in body, f"the missing child must be named:\n{body}"
    assert "not a pass" in body, \
        f"the halt has to say what it is not:\n{body}"


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


# ------------------------------------------------ one record set (I-4) ------
#
# Final review I-4, MEASURED: `sync_verify` scanned the authorizations directory
# with `rglob("*.md")` and a case-SENSITIVE `name == "INDEX.md"`, while this
# command used `glob("*.md")` and `name.upper() == "INDEX.MD"`. A record in a
# nested directory was therefore counted by the verifier and invisible to the
# reviewer — the reviewer signs off on the change while the file that authorises
# it sits in a block they never saw — and the template documents a FLAT
# directory, so the extra nesting is a hole, not a feature. Both readers now call
# `ai_common.authorization_records()`, so there is one walk and one answer.


def test_the_verifier_and_the_review_prompt_see_the_same_records(ai_repo, cp, sv):
    """Two accepted records flat, one nested: BOTH commands answer with the SAME
    record set — same two names, same count, and the nested file treated the same
    way by both (I-4).

    The layout `templates/authorizations/INDEX.md` documents is FLAT ("one file per
    stage, named `<YYYY-MM-DD>-<stage>.md`"), so the flat walk is the contract.
    What was broken is that the two readers disagreed about it: `sync_verify`
    walked recursively and `--review-prompt` did not, so a nested record's
    `## Editable files` covered the coverage walk while the reviewer never saw the
    document they were being asked to approve. One walk now, in both directions:
    the nested record counts for nothing anywhere.
    """
    _write_auth(ai_repo, "flat-one.md",
                "# Authorization -- one\n\nFLAT-ONE-MARKER\n\n## Governance\n"
                + GOV_ACCEPTED)
    _write_auth(ai_repo, "flat-two.md",
                "# Authorization -- two\n\nFLAT-TWO-MARKER\n\n## Governance\n"
                + GOV_ACCEPTED)
    nested = ai_repo / ".ai" / "state" / "authorizations" / "sub"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "nested-stage.md").write_text(
        "# Authorization -- nested\n\nNESTED-MARKER\n\n## Governance\n"
        + GOV_ACCEPTED, encoding="utf-8")

    res = run_python(sv, [], cwd=ai_repo)
    swarm = [ln for ln in res.lines
             if "swarm boundary" in ln and ln.startswith("[")]
    assert len(swarm) == 1, res.lines
    assert swarm[0].startswith("[FAIL] swarm boundary:"), swarm[0]
    assert "2 concurrent accepted authorizations" in swarm[0], swarm[0]
    assert "flat-one.md" in swarm[0] and "flat-two.md" in swarm[0], swarm[0]
    assert "nested-stage.md" not in swarm[0], swarm[0]

    prompt = run_python(cp, ["--review-prompt"], cwd=ai_repo)
    assert prompt.rc == 0, f"rc {prompt.rc}:\n{prompt.stdout}\n{prompt.stderr}"
    body = _sections(prompt)[HEADERS[0]]
    assert "[AMBIGUOUS AUTHORIZATION] 2 accepted records" in body, \
        f"the reviewer must count exactly what the verifier counted:\n{body}"
    assert "flat-one.md" in body and "flat-two.md" in body, body
    assert "FLAT-ONE-MARKER" in body and "FLAT-TWO-MARKER" in body, body
    assert "nested-stage.md" not in body, \
        f"a record outside the documented flat layout counts for nothing in " \
        f"BOTH readers:\n{body}"
