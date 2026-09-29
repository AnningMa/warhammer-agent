import pytest

from warhammer_agent.ingestion.handlers.text import clean_page, render_page


def test_navigation_removed_but_rule_numbers_preserved():
    nodes = [
        {
            "self_ref": "title",
            "label": "section_header",
            "text": "COMMAND",
            "prov": [{"page_no": 10}],
        },
        {
            "self_ref": "rule",
            "label": "text",
            "text": "Both players gain 1CP; roll 2D6.",
            "prov": [{"page_no": 10}],
        },
        {"self_ref": "nav", "label": "text", "text": "2", "prov": [{"page_no": 10}]},
    ]
    rules = {
        "page": 10,
        "keep_refs": ["title", "rule"],
        "omit_reasons": {"nav": "navigation"},
        "heading_overrides": {"title": "1. COMMAND"},
    }
    report = clean_page({"texts": nodes, "pictures": []}, rules)
    md, _ = render_page(report)
    assert "## 1. COMMAND" in md
    assert "1CP" in md and "2D6" in md
    assert "\n\n2\n" not in md
    assert report["omitted_nodes"][0]["node"]["text"] == "2"
    rules["keep_refs"].append("nav")
    with pytest.raises(ValueError, match="duplicated"):
        clean_page({"texts": nodes, "pictures": []}, rules)


def test_heading_levels_and_numbered_overview():
    nodes = [
        {"self_ref": "main", "label": "section_header", "text": "SHOOTING PHASE"},
        {"self_ref": "step", "label": "section_header", "text": "SELECT ELIGIBLE UNIT"},
        {"self_ref": "body", "label": "text", "text": "Eligibility rules."},
    ]
    rules = {
        "heading_levels": {"main": 1},
        "ordered_items": {"step": 1},
        "headings_before": {"body": {"level": 2, "text": "1. SELECT ELIGIBLE UNIT"}},
    }
    md, html = render_page({"kept_nodes": nodes, "rules": rules})
    assert md.startswith("# SHOOTING PHASE\n")
    assert "\n\n1. SELECT ELIGIBLE UNIT\n" in md
    assert "## 1. SELECT ELIGIBLE UNIT\n\nEligibility rules." in md
    assert "<h1>SHOOTING PHASE</h1>" in html
    assert '<ol start="1"><li>SELECT ELIGIBLE UNIT</li></ol>' in html
