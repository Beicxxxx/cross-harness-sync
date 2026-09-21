"""Task 12's wording sweep: the claims the shipped docs may not make.

Three rules shape this file.

* It greps TRACKED files with ``git grep`` — never ``rglob``. The repo's scratch
  briefs under ``.superpowers/`` are text no user ever sees, and a sweep that
  reads them tests nothing; ``rglob`` would also read them while they are being
  written. Files must be ``git add``-ed to be swept, which is the point.
* Every needle is built by concatenation so THIS file stays clean under the
  greps it runs; a wording test whose own source needs an exclusion is a wording
  test that can be bypassed.
* Two residuals are named instead of pretended away: ``templates/*`` still
  carries D26's wrong unit (finding T12-F1, another lane's file) and
  ``scripts/init_sync.py`` still quotes the removed green promise while
  explaining its removal (finding T12-F2). Both pins allow the residual to
  SHRINK only.

D25's ``MILE`` + ``STONES`` sweep already lives in
``test_version_and_naming.py``; it is not repeated here.
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# D26's banned unit claim, spelled so this file is not a hit on its own grep.
D26_NEEDLE = "token " + "budget"
# Coherence finding 1.1's banned promise: a fresh install registers no project
# checks, so a run can never be "green"; the gate is "no FAILED line".
GREEN_NEEDLE_EN = "all " + "green"
GREEN_NEEDLE_ZH = "必须全" + "绿"

# Text a reader meets. CHANGELOG is included on purpose: release copy is where an
# over-claim does the most damage, so it holds to the same rule as the quickstart.
SHIPPED_DOCS = ("SKILL.md", "README.md", "reference.md", "CHANGELOG.md")
# templates/* is owned by another lane; the residual there is finding T12-F1.
TEMPLATE_RESIDUAL = {"templates/AGENTS.md", "templates/SYNC_PROMPT.md"}

CJK_PROXY = ("A line is a weak proxy for tokens in CJK state files, which this "
             "protocol permits; real token accounting is a wave-2 measurement, "
             "not a wave-1 claim.")


def _git_grep(*args: str) -> list[str]:
    """``git grep -l`` paths, relative to the repo root, forward slashes."""
    res = subprocess.run(["git", "grep", "-l", *args], cwd=str(REPO),
                         capture_output=True, text=True)
    assert res.returncode in (0, 1), res.stderr  # 1 = no match, which is legal
    return sorted(res.stdout.split())


def _flat(*names: str) -> str:
    """File text with wrapping collapsed, so a claim pinned here cannot be
    dodged by a line break at column 79."""
    joined = "\n".join((REPO / n).read_text("utf-8") for n in names)
    return re.sub(r"\s+", " ", joined)


def test_d26_unit_claim_is_clean_outside_templates():
    """Nothing a buyer reads may claim the caps count tokens; the code counts lines."""
    hits = _git_grep(D26_NEEDLE, "--", ":!docs/superpowers")
    assert set(hits) <= TEMPLATE_RESIDUAL, hits
    assert "SKILL.md" not in hits and "README.md" not in hits


def test_no_shipped_text_promises_all_green():
    """A default install prints a named SKIP forever; 'green' is unsatisfiable.

    scripts/ is out of scope on purpose: three comment sites there quote the
    removed line to explain why it went (finding T12-F2). Everything a user reads
    is in scope, templates included — they install into the target repo."""
    assert _git_grep(GREEN_NEEDLE_EN, "--", *SHIPPED_DOCS, "templates") == []
    assert _git_grep(GREEN_NEEDLE_ZH, "--", *SHIPPED_DOCS, "templates") == []


def test_frontmatter_names_the_unit_it_ships():
    """The listing description is the most-read sentence in the package."""
    assert "layered line budgets" in (REPO / "SKILL.md").read_text("utf-8")


def test_omission_vs_fabrication_ships_in_both_entry_docs():
    """Spec section 2's mandatory framing; before wave 1a the words appeared in
    neither file that ships, only in the spec and the non-shipping positioning draft."""
    for name in SHIPPED_DOCS[:2]:
        text = _flat(name).lower()
        assert "omission" in text, name
        assert "fabrication" in text, name


def test_cjk_proxy_sentence_ships_with_the_rename():
    """"Line budgets" is honest only with the weakness attached, verbatim."""
    for name in ("SKILL.md", "reference.md"):
        assert CJK_PROXY in _flat(name), name


def test_advisory_lock_boundary_named_in_both_entry_docs():
    """No copy may claim the skill rejects concurrent writers: the state-writing
    commands WARN by name and continue at exit 0. Both docs must say so."""
    for name in SHIPPED_DOCS[:2]:
        text = _flat(name)
        assert "WARN" in text, name
        assert "exit 0" in text, name
