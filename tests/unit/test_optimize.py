from copy import deepcopy

import pytest

from warhammer_agent.ingestion.corpus import digest, section_blocks, text_only
from warhammer_agent.ingestion.optimize import optimize_blocks


def block(page, title, body, status="unreviewed"):
    raw = (f"## {title}\n\n" if title else "") + body
    metadata = {
        "source_hash": "pdf",
        "document_sha256": "doc",
        "selected_markdown_sha256": digest(raw.encode()),
        "page_number": page,
        "page_numbers": [page],
        "review_status": status,
        "origin": "original_docling" if status == "unreviewed" else "reviewed_cleaned",
        "warnings": [],
        "source": "Rules.pdf",
    }
    result = section_blocks(raw, metadata)[0]
    result["_markdown"] = raw
    result["text"] = text_only(raw, page)
    result["embedding_text"] = result["text"]
    result["text_sha256"] = digest(result["text"].encode())
    for asset in result["assets"]:
        asset.pop("target")
        asset.update(source_pdf_page=page, stored=False)
    return result


def selector(b):
    return {
        k: b[k] for k in ["block_id", "page_number", "section_title", "text_sha256"]
    }


def config():
    return {
        "schema_version": 1,
        "source_sha256": "pdf",
        "document_sha256": "doc",
        "merge_rules": [],
        "move_suffix_rules": [],
        "noise_lines": [],
        "drop_preambles": [],
    }


def test_noise_is_removed_but_unapproved_numeric_values_are_preserved():
    rule = block(12, "Rule", "Keep this rule.\n\n<!-- image -->\n\n12\n\n1000\n")
    cfg = config()
    cfg["noise_lines"] = [
        {"selector": selector(rule), "lines": ["12"], "reason": "Page footer"}
    ]
    result = optimize_blocks([rule], cfg, "config")
    assert "1000" in result[0]["text"]
    assert "<!-- image -->" not in result[0]["text"]
    assert "\n12\n" not in result[0]["text"]
    assert len(result[0]["source_segments"]) == 2
    assert len(result[0]["corpus_audit"]["exclusions"]) == 2


def test_header_and_image_only_blocks_are_audited_not_embedded():
    heading = block(1, "ROOT", "")
    image = block(1, "Diagram", "![Diagram](../image.png)\n")
    rule = block(1, "Rule", "Substantive rule.")
    rule["embedding_text"] = "# ROOT\n\n" + rule["text"]
    result = optimize_blocks([heading, image, rule], config(), "config")
    assert len(result) == 1
    assert result[0]["embedding_text"].startswith("# ROOT")
    assert result[0]["corpus_audit"]["dropped_blocks"] == [
        heading["block_id"],
        image["block_id"],
    ]


def test_cross_page_merge_preserves_fragment_ranges_and_review_states():
    a = block(
        34, "MAKE ATTACKS", "Even if no models in that unit", "reviewed_correction"
    )
    b = block(35, None, "remain within Engagement Range.\n")
    cfg = config()
    cfg["merge_rules"] = [
        {
            "id": "continue",
            "target": selector(a),
            "sources": [selector(b)],
            "reason": "Verified split sentence",
        }
    ]
    result = optimize_blocks([a, b], cfg, "config")
    merged = result[0]
    assert len(result) == 1
    assert "that unit remain within Engagement Range." in merged["text"]
    assert merged["page_numbers"] == [34, 35]
    assert merged["review_status"] == "partially_reviewed"
    assert [s["review_status"] for s in merged["source_segments"]] == [
        "reviewed_correction",
        "unreviewed",
    ]
    assert merged["source_block_ids"] == [a["block_id"], b["block_id"]]
    assert "markdown_span" not in merged and "selected_markdown_sha256" not in merged
    assert result == optimize_blocks([a, b], cfg, "config")


def test_only_figure_suffix_moves_and_keeps_its_source_page():
    movement = block(53, "MOVEMENT", "Aircraft movement rules.\n")
    charge = block(
        54,
        "CHARGE",
        "Aircraft charge rules.\n\n![Movement](../a.png)\n\nA: Pivot after moving.\n",
    )
    cfg = config()
    cfg["move_suffix_rules"] = [
        {
            "id": "figure",
            "source": selector(charge),
            "target": selector(movement),
            "anchor": "![Movement](../a.png)",
            "reason": "Verified movement caption",
        }
    ]
    a, b = optimize_blocks([movement, charge], cfg, "config")
    assert a["page_numbers"] == [53, 54]
    assert "Pivot after moving" in a["text"]
    assert "Aircraft charge rules" not in a["text"]
    assert "Pivot after moving" not in b["text"]
    assert a["assets"][0]["source_pdf_page"] == 54
    assert not b["assets"]
    moved = a["source_segments"][-1]
    kept = b["source_segments"][0]
    assert moved["markdown_span"]["start"] == kept["markdown_span"]["end"]


def test_changed_source_or_missing_anchor_fails_closed():
    a = block(1, "Rule", "Actual rule.")
    b = block(2, None, "Actual continuation.")
    cfg = config()
    cfg["merge_rules"] = [
        {
            "id": "merge",
            "target": selector(a),
            "sources": [selector(b)],
            "reason": "Verified",
        }
    ]
    changed = deepcopy(b)
    changed["text_sha256"] = "changed"
    with pytest.raises(ValueError, match="source changed"):
        optimize_blocks([a, changed], cfg, "config")
    cfg = config()
    cfg["move_suffix_rules"] = [
        {
            "id": "move",
            "source": selector(b),
            "target": selector(a),
            "anchor": "missing image",
            "reason": "Verified",
        }
    ]
    with pytest.raises(ValueError, match="anchor"):
        optimize_blocks([a, b], cfg, "config")


def test_table_values_are_not_filtered_as_numeric_furniture():
    rule = block(9, "DICE", "| D6 | D3 |\n|---|---|\n| 1 or 2 | 1 |\n")
    result = optimize_blocks([rule], config(), "config")[0]
    assert "| 1 or 2 | 1 |" in result["text"]
    assert result["content_type"] == "table"
