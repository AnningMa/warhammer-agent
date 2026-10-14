import json
from pathlib import Path

import pytest

from warhammer_agent.ingestion.corpus import build_corpus, digest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    not (ROOT / "data/Core Rules.pdf").exists(), reason="Local source PDF required"
)
def test_rebuild_without_persistent_intermediates(tmp_path, monkeypatch):
    from warhammer_agent.ingestion.corpus import text_only
    from warhammer_agent.ingestion.optimize import optimize_blocks

    original = {}

    def capture(blocks, config, config_hash):
        original.update({b["block_id"]: b for b in blocks})
        return optimize_blocks(blocks, config, config_hash)

    monkeypatch.setattr("warhammer_agent.ingestion.optimize.optimize_blocks", capture)
    output = tmp_path / "corpus"
    manifest = build_corpus(ROOT, output)
    pages = manifest["pages"]
    assert [p["page_number"] for p in pages] == list(range(1, 61))
    assert sum(p["origin"] == "reviewed_cleaned" for p in pages) == 36
    assert {p["page_number"] for p in pages if not p["index_eligible"]} == {
        1,
        2,
        3,
        4,
        31,
        40,
    }
    assert {p.name for p in output.iterdir()} == {
        "core_rules.txt",
        "index_blocks.jsonl",
    }
    text = (output / "core_rules.txt").read_text()
    blocks = [
        json.loads(line)
        for line in (output / "index_blocks.jsonl").read_text().splitlines()
    ]
    assert len(blocks) == manifest["index_block_count"] == 228
    assert len({b["block_id"] for b in blocks}) == len(blocks)
    assert not {b["page_number"] for b in blocks} & {1, 2, 3, 4, 31, 40}
    for b in blocks:
        span = b["txt_span"]
        assert text[span["start"] : span["end"]] == b["embedding_text"]
        assert digest(text.encode()) == b["txt_sha256"]
        assert digest(b["text"].encode()) == b["text_sha256"]
        assert b["page_number"] == min(b["page_numbers"])
        assert b["page_numbers"] == sorted(
            {s["page_number"] for s in b["source_segments"]}
        )
        for segment in b["source_segments"]:
            source = original[segment["source_block_id"]]
            span = segment["markdown_span"]
            start = span["start"] - source["markdown_span"]["start"]
            end = span["end"] - source["markdown_span"]["start"]
            raw = source["_markdown"][start:end]
            assert digest(raw.encode()) == segment["source_fragment_sha256"]
            assert (
                segment["selected_markdown_sha256"]
                == source["selected_markdown_sha256"]
            )
            rendered = text_only(raw, segment["page_number"]).strip("\n")
            span = segment["text_span"]
            assert b["text"][span["start"] : span["end"]] == rendered
            assert digest(rendered.encode()) == segment["rendered_text_sha256"]
        assert not any(
            k in b
            for k in [
                "canonical_page",
                "canonical_audit",
                "audit_path",
                "selected_source",
            ]
        )
        assert "![" not in b["text"] and "<!-- image -->" not in b["text"]
        if b["section_title"]:
            assert b["section_title"] in b["embedding_text"]
        for asset in b["assets"]:
            assert asset["stored"] is False
            assert asset["source_pdf_page"] in b["page_numbers"]
            assert "path" not in asset and "target" not in asset
    grenade = [b for b in blocks if b["section_title"] == "GRENADE"]
    assert len(grenade) == 1
    assert "CP cost:" in grenade[0]["text"]
    assert "WHEN:" in grenade[0]["text"] and "EFFECT:" in grenade[0]["text"]

    wound = next(b for b in blocks if b["section_title"] == "2. WOUND ROLL")
    assert wound["page_numbers"] == [21, 22]
    assert wound["review_status"] == "partially_reviewed"
    assert "| 2+ |" in wound["text"] and "Critical Wound" in wound["text"]
    dice = next(
        b for b in blocks if b["section_title"] == "DICE" and b["page_number"] == 9
    )
    assert "halve the result" in dice["text"] and "| 5 or 6 | 3 |" in dice["text"]
    movement = next(
        b for b in blocks if b["section_title"] == "AIRCRAFT IN THE MOVEMENT PHASE"
    )
    assert movement["page_numbers"] == [53, 54]
    assert 'minimum of 20"' in movement["text"] and "90º" in movement["text"]
    charge = next(
        b
        for b in blocks
        if b["section_title"] == "AIRCRAFT IN THE CHARGE AND FIGHT PHASES"
    )
    assert "Aircraft movement: A, B and C" not in charge["text"]
    assert charge["assets"] == []
    weapon = next(
        b
        for b in blocks
        if b["section_title"] == "SELECT WEAPON" and b["page_number"] == 33
    )
    assert (
        weapon["page_numbers"] == [33, 34] and "more than one profile" in weapon["text"]
    )
    melee = next(
        b
        for b in blocks
        if b["section_title"] == "MAKE ATTACKS" and b["page_number"] == 34
    )
    assert melee["page_numbers"] == [34, 35]
    assert (
        "no models in the target unit of that attack remain within Engagement Range"
        in melee["text"]
    )
    main = next(b for b in blocks if b["section_title"] == "UNIT COHERENCY")
    example = next(
        b
        for b in blocks
        if b["section_title"] == "Unit Coherency — illustrated examples"
    )
    assert example["parent_rule_id"] == main["block_id"]
    assert main["example_block_ids"] == [example["block_id"]]
    for page, terrain in [(47, "WOODS"), (48, "RUINS")]:
        terrain_blocks = [b for b in blocks if b["page_number"] == page]
        assert all(b["embedding_context"]["terrain"] == terrain for b in terrain_blocks)
        assert all(b["section_path"][0] == terrain for b in terrain_blocks)
        assert all(
            b["context_provenance"]["page_numbers"] == [page] for b in terrain_blocks
        )
    woods = next(
        b
        for b in blocks
        if b["page_number"] == 47 and b["section_title"] == "BENEFIT OF COVER"
    )
    ruins = next(
        b
        for b in blocks
        if b["page_number"] == 48 and b["section_title"] == "BENEFIT OF COVER"
    )
    assert woods["text"] == ruins["text"]
    assert woods["embedding_text"] != ruins["embedding_text"]
    # Every original non-whitespace character has either retained provenance or
    # an explicit exclusion. Merges never duplicate the same source range.
    exclusions = blocks[0]["corpus_audit"]["exclusions"]
    for identity, source in original.items():
        coverage = bytearray(len(source["_markdown"]))
        retained = bytearray(len(source["_markdown"]))
        records = [
            s
            for b in blocks
            for s in b["source_segments"]
            if s["source_block_id"] == identity
        ]
        base = source["markdown_span"]["start"]
        for segment in records:
            start, end = (
                segment["markdown_span"]["start"] - base,
                segment["markdown_span"]["end"] - base,
            )
            assert not any(retained[start:end]), identity
            retained[start:end] = b"\x01" * (end - start)
            coverage[start:end] = b"\x01" * (end - start)
        for segment in exclusions:
            if segment["source_block_id"] == identity:
                start, end = (
                    segment["markdown_span"]["start"] - base,
                    segment["markdown_span"]["end"] - base,
                )
                coverage[start:end] = b"\x01" * (end - start)
        assert all(
            char.isspace() or covered
            for char, covered in zip(source["_markdown"], coverage)
        ), identity


def test_changed_pdf_fails_before_writing_output(tmp_path):
    root = tmp_path / "root"
    manifest_path = root / "config/corrections/core_rules/manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(
        (ROOT / "config/corrections/core_rules/manifest.json").read_bytes()
    )
    (root / "data").mkdir()
    (root / "data/Core Rules.pdf").write_bytes(b"changed source")
    output = root / "reports"
    with pytest.raises(ValueError, match="Source changed"):
        build_corpus(root, output)
    assert not output.exists()
