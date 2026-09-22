"""Wave 1c lane: governance text that contradicts itself and slots nobody filled.

Found by using the protocol rather than reading it: executing this stage meant
opening `.ai/state/ROLE_POLICY.md`, and the file that carries the review rules
was still half template. Three distinct defects, one per group of tests below.

  C1  `role_policy_sha256` pins a document whose Adopted line is
      `<YYYY-MM-DD HH:MM:SS> … by <who>` and whose section 7 is the template's
      own instruction to the author. `required …` and `budget …` both pass on
      it, so the digest proved only that nobody had looked.
  C2  R3 makes a different model family a requirement at T2/T3 while R5 says the
      family is recorded and is never a gate. Both ship, and a stage that obeys
      R5 reads as a violation of R3 — which is how the dogfood record ended up
      asserting there was no conflict to resolve.
  C3  `templates/AGENTS.md` orders `git add -A` two lines above its own rule
      against committing secrets, and leaves `<NAME> <<EMAIL>>` unfilled because
      no installer code touches it.

Needles are built by concatenation so this file stays clean under the greps it
runs, the way `test_doc_wording.py` does.

Red-at-base provenance is recorded in the stage evidence file, not here, because
a number in a docstring is a claim about a tree that no longer exists.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from helpers import REPO_ROOT, git, make_repo, run_python, scaffold

TEMPLATE_ROLE = REPO_ROOT / "templates" / "ROLE_POLICY.md"
TEMPLATE_AGENTS = REPO_ROOT / "templates" / "AGENTS.md"
TEMPLATE_NEXT = REPO_ROOT / "templates" / "handoff" / "NEXT_PROMPT.md"

# C1's slots, spelled so this file is not a hit on its own scan.
SLOT_ADOPTED = "<YYYY-MM-DD " + "HH:MM:SS>"
SLOT_WHO = "by <who>"
SLOT_NAME = "<NAME> <<E" + "MAIL>>"
BLANK_SECTION7 = "<List standing "

# C3's banned instruction.
ADD_ALL = "git add " + "-A"


def _git_grep(pattern: str, *paths: str) -> list[str]:
    res = subprocess.run(["git", "grep", "-l", pattern, "--", *paths],
                         cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode in (0, 1), res.stderr  # 1 = no match, which is legal
    return sorted(res.stdout.split())


# ---------------------------------------------------------------- C1: slots


def test_c1_verifier_names_an_unfilled_slot_in_an_installed_state_file(ai_repo):
    """A required, digest-pinned file that is still template text must not pass.

    The whole point of the check is that it catches the shipped case, so the
    fixture starts from the install a fresh `init_sync.py` actually produces.
    """
    (ai_repo / ".ai" / "state" / "ROLE_POLICY.md").write_text(
        "# Role policy\n\n> Adopted: " + SLOT_ADOPTED + ", " + SLOT_WHO + ".\n",
        encoding="utf-8")
    res = run_python(ai_repo / ".ai" / "scripts" / "sync_verify.py", [], cwd=ai_repo)
    assert any(ln.startswith("[FAIL] unfilled template slots:") and "ROLE_POLICY.md" in ln
               for ln in res.lines), res.lines


def test_c1_control_a_filled_in_install_adds_no_slot_failure(ai_repo):
    """CONTROL: the check must not manufacture a failure where the text is real."""
    target = ai_repo / ".ai" / "state" / "ROLE_POLICY.md"
    text = target.read_text("utf-8")
    target.write_text(text.replace(SLOT_ADOPTED, "2026-09-22 11:04:30 (+10:00)")
                      .replace(SLOT_WHO, "by the user")
                      .replace(BLANK_SECTION7, "Project boundaries"), encoding="utf-8")
    res = run_python(ai_repo / ".ai" / "scripts" / "sync_verify.py", [], cwd=ai_repo)
    assert not any(ln.startswith("[FAIL] unfilled template slots:") for ln in res.lines), res.lines


def test_c1_init_sync_leaves_no_unfilled_slot_in_the_tree_it_writes(tmp_path):
    """Whatever the templates contain, the install a user gets must not.

    Scoped to the two files the installer is responsible for, exactly as
    `ai_common.INSTALLER_SLOTS` scopes the check that reports them: the angle
    brackets in CURRENT/TASK/BLOCKERS are the next agent's scaffolding, and an
    install with no work done yet is idle, not broken.
    """
    repo = make_repo(tmp_path)
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    by_file = {
        "AGENTS.md": (SLOT_NAME, "<PROJECT NAME>", "<REMOTE URL>", "<private/public>"),
        ".ai/state/ROLE_POLICY.md": (SLOT_ADOPTED, SLOT_WHO, BLANK_SECTION7),
    }
    offenders = []
    for rel, slots in by_file.items():
        body = (repo / rel).read_text("utf-8")
        offenders += [f"{rel}: {slot}" for slot in slots if slot in body]
    assert offenders == [], offenders


# ---------------------------------------------------------------- C2: R3/R5


def test_c2_role_policy_ships_the_downgrade_it_enforces():
    """Cross-family is the default; a same-family review is allowed when named.

    The user's ruling for wave 1c. Before it, R3 demanded a different family at
    T2/T3 while R5 said family is recorded and never gates, so the shipped
    policy contradicted itself and every same-family review was simultaneously
    compliant and non-compliant.
    """
    text = TEMPLATE_ROLE.read_text("utf-8")
    assert "same-family" in text, "no recorded-downgrade path in the shipped policy"
    unconditional = re.search(r"[Mm]ust be a different model \*{0,2}family\*{0,2}", text)
    assert unconditional is None, (
        "R3 still gates on family: " + (text[unconditional.start():][:120]
                                         if unconditional else ""))


def test_c2_no_shipped_text_gates_on_model_family():
    """The preference may appear anywhere; the requirement may appear nowhere.

    R3's old wording had a copy in three templates, so a harness that can load
    one model was told on three sides that it cannot do T2 work at all.
    """
    hits = _git_grep("must be a different model", "templates")
    assert hits == [], hits


def test_c2_template_takeover_prompt_states_the_rule_it_ships():
    """`templates/handoff/NEXT_PROMPT.md` told the next agent to stop for an
    unconditional cross-family review, which the policy does not require."""
    text = TEMPLATE_NEXT.read_text("utf-8")
    assert "cross-family" in text.lower()
    assert "same-family" in text, "the takeover line offers no recorded downgrade"


# ---------------------------------------------------------------- C3: AGENTS


def test_c3_no_shipped_text_orders_a_blanket_add():
    """`git add -A` two lines above "never commit secrets" is the bug.

    Scope is every path a reader follows, not just the template: README and
    SKILL each carried the same command in a quickstart, and an agent that
    copied the doc rather than installing the template hit the same defect.
    """
    hits = _git_grep(ADD_ALL, "templates", "README.md", "SKILL.md", "reference.md")
    assert hits == [], hits


def test_c3_the_identity_slot_is_filled_by_the_installer(tmp_path):
    """`<NAME> <<EMAIL>>` shipped untouched: no installer code names it.

    An install must carry the identity the repository will actually commit with,
    and must say out loud when it could not work one out.
    """
    repo = make_repo(tmp_path)
    git(repo, "config", "user.name", "Ada Lovelace")
    git(repo, "config", "user.email", "ada@example.com")
    assert scaffold(repo).rc == 0
    agents = (repo / "AGENTS.md").read_text("utf-8")
    assert SLOT_NAME not in agents, "the installer still leaves the identity blank"
    assert "Ada Lovelace <ada@example.com>" in agents, agents


def test_c3_control_an_unidentifiable_repo_is_named_not_guessed(tmp_path):
    """Falling back to a plausible name, or leaving the slot, are both silent.

    `make_repo` always sets a local identity, so this removes it: the install
    must then say out loud that it could not work one out.
    """
    repo = make_repo(tmp_path)
    git(repo, "config", "--unset", "user.name")
    git(repo, "config", "--unset", "user.email")
    res = scaffold(repo)
    assert res.rc == 0, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert SLOT_NAME not in (repo / "AGENTS.md").read_text("utf-8")
    assert "identity" in out.lower(), out
