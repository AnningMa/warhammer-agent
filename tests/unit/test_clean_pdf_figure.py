import pytest

from warhammer_agent.ingestion.handlers.figure import group_page, render_markdown


def fixture():
    texts = [
        "UNIT COHERENCY",
        "Models remain within 2 inches.",
        "A First example.",
        "B Second example.",
        '1½"',
        "6",
    ]
    nodes = [
        {
            "self_ref": f"#/texts/{i}",
            "text": text,
            "label": "section_header" if i == 0 else "text",
            "prov": [{"page_no": 6}],
        }
        for i, text in enumerate(texts)
    ]
    rules = {
        "page": 6,
        "body_refs": ["#/texts/0", "#/texts/1"],
        "summary_refs": [],
        "caption_refs": ["#/texts/2", "#/texts/3"],
        "annotation_refs": ["#/texts/4"],
        "furniture_refs": ["#/texts/5"],
        "figure_id": "figure",
        "figure_bbox": [0, 0, 10, 10],
    }
    return {"texts": nodes}, rules


def test_annotations_remain_in_figure_not_prose():
    doc, rules = fixture()
    report = group_page(doc, rules)
    md = render_markdown(report)
    assert "within 2 inches" in md
    assert '1½"' not in md
    assert "**A** First example." in md and "**B** Second example." in md
    assert "../images/page_006_coherency.png" in md
    assert report["figure"]["annotations"][0]["text"] == '1½"'
    assert report["figure"]["captions"][0]["prov"][0]["page_no"] == 6


def test_unassigned_nodes_require_review():
    doc, rules = fixture()
    rules["annotation_refs"] = []
    with pytest.raises(ValueError, match="Page nodes changed"):
        group_page(doc, rules)


def test_duplicate_assignment_requires_review():
    doc, rules = fixture()
    rules["body_refs"].append("#/texts/4")
    with pytest.raises(ValueError, match="assigned twice"):
        group_page(doc, rules)


def test_caption_fragments_merge_with_provenance():
    doc, rules = fixture()
    doc["texts"].append(
        {
            "self_ref": "#/texts/6",
            "text": "Continued sentence.",
            "label": "text",
            "prov": [{"page_no": 6}],
        }
    )
    rules["caption_refs"] = ["#/texts/2", "#/texts/6", "#/texts/3"]
    rules["caption_groups"] = [["#/texts/2", "#/texts/6"], ["#/texts/3"]]
    rules["image"] = "images/custom.png"
    rules["figure_title"] = "Custom example"
    report = group_page(doc, rules)
    assert (
        report["figure"]["captions"][0]["text"]
        == "A First example. Continued sentence."
    )
    assert len(report["figure"]["captions"][0]["source_nodes"]) == 2
    md = render_markdown(report)
    assert "Custom example" in md and "../images/custom.png" in md
    rules["caption_groups"] = [["#/texts/2"], ["#/texts/3"]]
    with pytest.raises(ValueError, match="cover caption refs"):
        group_page(doc, rules)


def test_unlettered_caption_keeps_first_characters():
    doc, rules = fixture()
    doc["texts"][2]["text"] = "In this example the model moves 12 inches."
    report = group_page(doc, rules)
    assert "In this example the model moves 12 inches." in render_markdown(report)
