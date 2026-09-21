"""The §6 record-format contract, against the parser that has to enforce it.

Every case below is a shape the format was reviewed for and the fence exists to
end: a duplicate key that would otherwise let the later line overrule the earlier
one in audit data, an unfilled template placeholder that reads as a completed
record, the two sanctioned sentinels, and an unknown key from a newer writer.

The absent-block case is the one that decides a run's outcome: it returns
`(None, None)` so the CALLER can name a WARN. Any default here — `{}`, a
`tier: 1`, an empty string verdict — would turn "this document never declared a
governance tier" into "it declared one the checker liked", which is the fail-open
shape §7 refuses.
"""
import importlib.util
import sys

from helpers import SCRIPTS


def _load(name):
    # Private registration name: `@dataclass` on `GitResult` needs the module in
    # `sys.modules` while its body runs, and binding the repo copy as `ai_common`
    # is the poisoning tests/test_ai_common.py exists to prevent. Popped once the
    # module has executed so no later test sees it either way.
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "ai_common.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    try:
        spec.loader.exec_module(m)
    finally:
        sys.modules.pop(name, None)
    return m


ai = _load("_b0_gov_ai_common")

# Prose around the block carries both things the contract must NOT scan: Chinese
# angle punctuation and an unfilled-looking placeholder in a sentence.
DOC = """# Task — replace the pin checker

Author: 《作者》 and the owner is <未填写> in this paragraph.

## Governance

```governance
tier: 2
executor: harness-A/model-X high
reviewer: n/a
verdict: NOT_REPORTED
red_before_green: true
user_authorized: true
```
"""


def test_absent_block_is_none_none_so_the_caller_can_warn():
    fields, err = ai.parse_governance_block("# Task\n\nno governance section here\n")
    assert fields is None, "an absent block must not be a default dict"
    assert err is None, "an absent block is a degradation, not a parse error"


def test_filled_block_parses_and_sentinels_survive():
    fields, err = ai.parse_governance_block(DOC)
    assert err is None
    assert fields["tier"] == "2"
    assert fields["verdict"] == "NOT_REPORTED"
    assert fields["reviewer"] == "n/a"
    assert fields["red_before_green"] == "true"


def test_chinese_angle_punctuation_and_outside_prose_are_never_scanned():
    fields, err = ai.parse_governance_block(DOC)
    assert err is None
    # The `<未填写>` in the prose line above sits outside the fence: the contract
    # applies the placeholder rule only inside the block, so prose is safe.
    assert "author" not in fields, "prose must not be read as a governance key"


def test_unknown_key_from_a_newer_writer_survives():
    fields, err = ai.parse_governance_block(
        "```governance\ntier: 1\nfuture_key: whatever a later wave adds\n```")
    assert err is None
    assert fields["future_key"] == "whatever a later wave adds"


def test_duplicate_key_is_fatal_not_last_wins():
    fields, err = ai.parse_governance_block(
        "```governance\ntier: 2\nverdict: PASS\ntier: 1\nverdict: FAIL\n```")
    assert fields == {}
    assert err is not None and "repeated" in err, err


def test_unfilled_ascii_placeholder_is_fatal():
    fields, err = ai.parse_governance_block(
        "```governance\ntier: <T1 or T2>\n```")
    assert fields == {}
    assert err is not None and "placeholder" in err, err


def test_chinese_placeholder_value_inside_the_block_survives():
    fields, err = ai.parse_governance_block(
        "```governance\nexecutor: 《作者》\n```")
    assert err is None
    assert fields["executor"] == "《作者》"


def test_line_without_colon_space_separator_is_fatal():
    fields, err = ai.parse_governance_block("```governance\ntier=2\n```")
    assert fields == {}
    assert err is not None and "separator" in err, err


def test_key_must_match_the_documented_grammar():
    for bad in ("Tier", "1tier", "tier-t1", "tier:", "tier tier"):
        fields, err = ai.parse_governance_block(f"```governance\n{bad}: 2\n```")
        assert fields == {}, bad
        assert err and "key is not" in err, (bad, err)


def test_unclosed_block_is_fatal_not_silently_truncated():
    fields, err = ai.parse_governance_block("```governance\ntier: 2\nreviewer: n/a\n")
    assert fields == {}
    assert err is not None and "never closed" in err, err


def test_value_split_happens_on_the_first_separator_only():
    # `executor: harness: model-X` — a value that itself contains ": " must keep it.
    fields, err = ai.parse_governance_block("```governance\nexecutor: a: b\n```")
    assert err is None
    assert fields["executor"] == "a: b"
