"""D14: the glob the coverage walk uses is case-sensitive and separator-stable.

`ai_common` ships beside `checkpoint.py` and is not an importable package, so it
is loaded by path (see tests/test_ai_common.py for the same idiom). Registration
under a PRIVATE name is required, not stylistic: `@dataclass` on `GitResult`
looks `sys.modules[cls.__module__]` up while the class body runs. Registering it
under the shipped name `ai_common` is the hazard test_ai_common.py exists to
prevent (an in-process load of an INSTALLED script would then resolve
`from ai_common import ...` to this object and never read the shipped file), so
the private entry is popped again as soon as the module has executed.
"""
import importlib.util
import sys

from helpers import SCRIPTS


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "ai_common.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    try:
        spec.loader.exec_module(m)
    finally:
        sys.modules.pop(name, None)
    return m


ai = _load("_b0_glob_ai_common")


def test_d14_glob_is_case_sensitive_and_separator_stable():
    pats = ["docs/superpowers/plans/*.md"]
    assert ai.glob_match("docs/superpowers/plans/2026-09-21-x.md", pats) is True
    assert ai.glob_match("Docs/Superpowers/Plans/2026-09-21-x.md", pats) is False
    assert ai.glob_match("docs\\superpowers\\plans\\a.md", pats) is True
    assert ai.glob_match("DOCS/a.md", ["docs/*.md"], case_sensitive=False) is True


def test_d14_glob_never_applies_normcase():
    assert ai.glob_match("a/B/C.md", ["a/B/*.md"]) is True
    assert ai.glob_match("a/b/c.md", ["a/B/*.md"]) is False
