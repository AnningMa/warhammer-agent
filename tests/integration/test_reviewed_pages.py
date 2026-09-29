import json
from pathlib import Path

import pytest

from warhammer_agent.ingestion.handlers.blocks import validate_coverage

ROOT = Path(__file__).resolve().parents[2]
PAGES = [24, 27, 29, 30, 33, 36, 37, 41, 42, 43, 45, 46, *range(49, 61)]


@pytest.fixture(scope="module")
def document():
    return json.loads((ROOT / "reports/docling/document.json").read_text())


@pytest.mark.parametrize("page", PAGES)
def test_every_source_text_has_an_explicit_destination(document, page):
    rules = json.loads(
        (ROOT / f"config/corrections/core_rules/page_{page:03d}.json").read_text()
    )
    validate_coverage(document, rules)


def test_missing_or_conflicting_classification_fails():
    doc = {"texts": [{"self_ref": "t", "prov": [{"page_no": 1}]}]}
    rules = {"page": 1, "blocks": [{"type": "text", "refs": []}], "excluded_text": {}}
    with pytest.raises(ValueError, match="classification"):
        validate_coverage(doc, rules)
    rules["blocks"][0]["refs"] = ["t"]
    rules["excluded_text"]["t"] = "duplicate"
    with pytest.raises(ValueError, match="classification"):
        validate_coverage(doc, rules)


def test_cp_cards_match_reviewed_costs_and_geometry(document):
    nodes = {n["self_ref"]: n for n in document["texts"]}
    expected = {
        "COMMAND RE-ROLL": 1,
        "COUNTER-OFFENSIVE": 2,
        "EPIC CHALLENGE": 1,
        "INSANE BRAVERY": 1,
        "GRENADE": 1,
        "TANK SHOCK": 1,
        "RAPID INGRESS": 1,
        "FIRE OVERWATCH": 1,
        "GO TO GROUND": 1,
        "SMOKESCREEN": 1,
        "HEROIC INTERVENTION": 2,
    }
    found = {}
    for page in [41, 42]:
        rules = json.loads(
            (ROOT / f"config/corrections/core_rules/page_{page:03d}.json").read_text()
        )
        for card in rules["blocks"]:
            if card["type"] != "card":
                continue
            title = nodes[card["title_ref"]]
            cp = nodes[card["cp_ref"]]
            found[title["text"]] = card["expected_cp"]
            assert cp["text"] == f"{card['expected_cp']}CP"
            a = title["prov"][0]["bbox"]
            b = cp["prov"][0]["bbox"]
            assert 20 < a["l"] - b["l"] < 35
            assert 30 < a["t"] - b["t"] < 80
    assert found == expected


def test_reserves_records_are_unambiguous():
    rules = json.loads(
        (ROOT / "config/corrections/core_rules/page_043.json").read_text()
    )
    table = next(b for b in rules["blocks"] if b["type"] == "table")
    assert {
        r["battle_size"]: r["max_strategic_reserves_points"]
        for r in table["retrieval_records"]
    } == {"Incursion": 250, "Strike Force": 500, "Onslaught": 750}
    assert all(
        r["timing"] == "before the battle" and r["page"] == 43
        for r in table["retrieval_records"]
    )


def test_example_datasheet_text_is_not_promoted_to_rule_prose():
    rules = json.loads(
        (ROOT / "config/corrections/core_rules/page_037.json").read_text()
    )
    indexed = {
        r for b in rules["blocks"] if b["type"] == "text" for r in b.get("refs", [])
    }
    assert indexed == {"#/texts/869", "#/texts/870", "#/texts/871", "#/texts/937"}
    assert len([b for b in rules["blocks"] if b["type"] == "image"]) == 2


def test_terrain_titles_have_requested_hierarchy():
    rules = json.loads(
        (ROOT / "config/corrections/core_rules/page_046.json").read_text()
    )
    assert [b["refs"][0] for b in rules["blocks"] if b.get("style") == "h1"] == [
        "#/texts/1166",
        "#/texts/1175",
    ]
    assert {
        b["style"]
        for b in rules["blocks"]
        if b.get("refs") in [["#/texts/1168"], ["#/texts/1177"]]
    } == {"h2"}


def test_muster_steps_keep_rules_and_footnote_under_select_units():
    rules = json.loads(
        (ROOT / "config/corrections/core_rules/page_056.json").read_text()
    )
    blocks = rules["blocks"]
    headings = [b["text"] for b in blocks if b.get("style") == "h2"]
    assert headings == [
        "4. SELECT DETACHMENT RULES",
        "5. SELECT UNITS",
        "6. SELECT WARLORD",
    ]
    joined = next(
        b for b in blocks if b.get("refs") == ["#/texts/1306", "#/texts/1307"]
    )
    footnote = next(b for b in blocks if b.get("refs") == ["#/texts/1308"])
    warlord = next(b for b in blocks if b.get("text") == "6. SELECT WARLORD")
    assert blocks.index(joined) < blocks.index(footnote) < blocks.index(warlord)


def test_deployment_measurements_remain_attached_to_map():
    rules = json.loads(
        (ROOT / "config/corrections/core_rules/page_060.json").read_text()
    )
    diagram = next(b for b in rules["blocks"] if b["type"] == "image")
    assert {"#/texts/1403", "#/texts/1404"} <= set(diagram["source_refs"])
    assert not {"#/texts/1403", "#/texts/1404"} & set(rules["excluded_text"])
    assert [
        b["text"].split(".")[0] for b in rules["blocks"] if b.get("style") == "h2"
    ] == ["6", "7", "8", "9", "10", "11"]


def test_reviewed_figures_have_valid_crops_and_existing_outputs():
    for page in range(49, 61):
        rules = json.loads(
            (ROOT / f"config/corrections/core_rules/page_{page:03d}.json").read_text()
        )
        for b in rules["blocks"]:
            if b["type"] == "image":
                x0, y0, x1, y1 = b["bbox"]
                assert 0 <= x0 < x1 <= 610
                assert 0 <= y0 < y1 <= 794
                assert (
                    ROOT / f"reports/cleaned/images/page_{page:03d}_{b['id']}.png"
                ).is_file()
