import json
from pathlib import Path

import pytest

from warhammer_agent.ingestion.handlers.table import replace_table

RULES = (
    Path(__file__).resolve().parents[2] / "config/corrections/core_rules/page_009.json"
)


def test_verified_mapping_and_surrounding_text_preserved():
    rules = json.loads(RULES.read_text())
    result, before, after = replace_table(
        "Before\n\n" + rules["original_fragment"] + "\n\nAfter", rules
    )
    assert before == "Before\n\n" and after == "\n\nAfter"
    assert result.startswith(before) and result.endswith(after)
    assert "| or " not in result
    assert result.count("![Rolling a D3") == 1
    assert {d6: row["d3"] for row in rules["rows"] for d6 in row["d6"]} == {
        1: 1,
        2: 1,
        3: 2,
        4: 2,
        5: 3,
        6: 3,
    }
    for row in ["| 1 or 2 | 1 |", "| 3 or 4 | 2 |", "| 5 or 6 | 3 |"]:
        assert row in result


def test_missing_or_ambiguous_table_requires_review():
    rules = json.loads(RULES.read_text())
    for text in ["changed", rules["original_fragment"] * 2]:
        with pytest.raises(ValueError, match="exactly one"):
            replace_table(text, rules)
