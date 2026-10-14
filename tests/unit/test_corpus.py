from warhammer_agent.ingestion.corpus import section_blocks


def metadata():
    return {"source_hash": "abc", "page_number": 6, "warnings": []}


def test_lossless_spans_and_heading_context():
    text = "Introduction\n\n# Movement\n\n## Advance\n\nRoll a die.\n\n### Exception\n\nUnless engaged.\n"
    blocks = section_blocks(text, metadata())
    assert "".join(b["text"] for b in blocks) == text
    for block in blocks:
        span = block["markdown_span"]
        assert text[span["start"] : span["end"]] == block["text"]
    assert blocks[-1]["section_path"] == ["Movement", "Advance", "Exception"]
    assert blocks[-1]["embedding_text"].startswith(
        "# Movement\n## Advance\n\n### Exception"
    )
    assert len({b["block_id"] for b in blocks}) == len(blocks)
    assert blocks == section_blocks(text, metadata())


def test_table_and_figure_captions_remain_together():
    text = "## Example\n\n| Roll | Result |\n|---|---|\n| 1 | Fail |\n\n![Example](../images/a.png)\n\nA: first step.\n\nB: exception.\n"
    blocks = section_blocks(text, metadata())
    assert len(blocks) == 1
    assert blocks[0]["content_type"] == "mixed"
    assert blocks[0]["text"] == text
    assert blocks[0]["assets"] == [{"alt": "Example", "target": "../images/a.png"}]
    assert blocks[0]["warnings"]


def test_fenced_heading_is_not_a_boundary_and_page_context_resets():
    text = "# Rule\n\n```text\n# Not a heading\n```\n\nActual body\n"
    assert len(section_blocks(text, metadata())) == 1
    assert section_blocks("Body without heading", metadata())[0]["section_path"] == []


def test_identical_text_on_different_pages_has_distinct_ids():
    first = section_blocks("# Rule\nBody", metadata())[0]
    other = section_blocks("# Rule\nBody", {**metadata(), "page_number": 7})[0]
    assert first["block_id"] != other["block_id"]


def test_text_only_keeps_captions_and_uses_original_pdf():
    from warhammer_agent.ingestion.corpus import text_only

    text = "![Diagram](../images/a.png)\n\nA: caption\n<!-- image -->"
    result = text_only(text, 54)
    assert "A: caption" in result
    assert "source PDF page 54" in result
    assert ".png" not in result and "<!-- image -->" not in result


def test_txt_and_jsonl_share_exact_content_and_offsets(tmp_path):
    import json

    from warhammer_agent.ingestion.corpus import write_outputs

    blocks = section_blocks(
        "# Rule\nBody",
        {**metadata(), "source": "Rules.pdf", "review_status": "unreviewed"},
    )
    write_outputs(blocks, tmp_path)
    text = (tmp_path / "core_rules.txt").read_text()
    saved = json.loads((tmp_path / "index_blocks.jsonl").read_text())
    span = saved["txt_span"]
    assert text[span["start"] : span["end"]] == saved["embedding_text"]
    assert {p.name for p in tmp_path.iterdir()} == {
        "core_rules.txt",
        "index_blocks.jsonl",
    }
