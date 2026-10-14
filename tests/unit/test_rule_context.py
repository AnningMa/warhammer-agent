from copy import deepcopy

import numpy as np
import pytest

from warhammer_agent.embeddings.cli import evaluate, expand_evidence, rank
from warhammer_agent.ingestion.context import enrich_blocks


def block(identity, title, page, text, path=None):
    return {
        "block_id": identity,
        "source_block_ids": [identity + ".original"],
        "source_hash": "pdf",
        "document_sha256": "doc",
        "page_number": page,
        "page_numbers": [page],
        "section_title": title,
        "section_path": path or [title],
        "text": text,
        "text_sha256": text,
        "embedding_text": text,
        "source_segments": [{"page_number": page}],
        "corpus_audit": {},
        "review_status": "unreviewed",
    }


def selector(b):
    return {
        "source_block_id": b["source_block_ids"][0],
        "page_number": b["page_number"],
        "section_title": b["section_title"],
        "text_sha256": b["text_sha256"],
    }


def config():
    return {
        "schema_version": 1,
        "source_sha256": "pdf",
        "document_sha256": "doc",
        "terrain_groups": [],
        "example_links": [],
    }


def test_terrain_context_distinguishes_identical_rule_text_without_rewriting_sources():
    woods = block("woods", "WOODS", 47, "Woods heading.")
    ruins = block("ruins", "RUINS", 48, "Ruins heading.")
    a = block("a", "BENEFIT OF COVER", 47, "Within this terrain feature.")
    b = block("b", "BENEFIT OF COVER", 48, "Within this terrain feature.")
    original = [woods, a, ruins, b]
    cfg = config()
    cfg["terrain_groups"] = [
        {
            "terrain": h["section_title"],
            "heading": selector(h),
            "blocks": [selector(h), selector(c)],
        }
        for h, c in [(woods, a), (ruins, b)]
    ]
    result = enrich_blocks(original, cfg, "hash")
    assert result[1]["text"] == result[3]["text"] == a["text"]
    assert result[1]["embedding_text"] != result[3]["embedding_text"]
    assert result[1]["embedding_context"]["terrain"] == "WOODS"
    assert result[3]["section_path"] == ["RUINS", "BENEFIT OF COVER"]
    assert result[1]["context_provenance"]["heading_block_id"] == result[0]["block_id"]
    assert result[1]["source_segments"] == a["source_segments"]
    assert original[1]["embedding_text"] == a["text"]
    assert result == enrich_blocks(original, cfg, "hash")


def test_context_name_and_source_changes_are_rejected():
    h = block("woods", "WOODS", 47, "Heading.")
    cfg = config()
    cfg["terrain_groups"] = [
        {"terrain": "RUINS", "heading": selector(h), "blocks": [selector(h)]}
    ]
    with pytest.raises(ValueError, match="Terrain name"):
        enrich_blocks([h], cfg, "hash")
    cfg["terrain_groups"][0]["terrain"] = "WOODS"
    changed = deepcopy(h)
    changed["text_sha256"] = "changed"
    with pytest.raises(ValueError, match="source changed"):
        enrich_blocks([changed], cfg, "hash")


def linked():
    main = block(
        "main",
        "UNIT COHERENCY",
        6,
        "Within 2 inches horizontally and 5 inches vertically.",
    )
    example = block("example", "Example", 6, "Five models within 2 inches.")
    cfg = config()
    cfg["example_links"] = [
        {
            "example": selector(example),
            "parent": selector(main),
            "reason": "Illustrates main rule.",
        }
    ]
    return enrich_blocks([main, example], cfg, "hash")


def test_example_hit_gets_parent_evidence_without_inflating_rank_metrics():
    blocks = linked()
    vectors = np.array([[0, 1], [1, 0]])
    query = np.array([1, 0])
    hits = rank(blocks, vectors, query, 1)
    evidence = expand_evidence(hits, blocks)
    assert hits[0]["block_id"] == "example"
    assert evidence[0]["related_evidence"][0]["block_id"] == "main"
    assert "5 inches vertically" in evidence[0]["related_evidence"][0]["text"]
    assert "score" not in evidence[0]["related_evidence"][0]
    assert blocks[0]["example_block_ids"] == ["example"]
    cases = [
        {
            "id": "coherency",
            "question": "distance?",
            "section_title": "UNIT COHERENCY",
            "page_number": 6,
        }
    ]
    model = type("Fake", (), {"embed_query": lambda self, text: query})()
    result = evaluate(cases, blocks, vectors, model, 1)
    assert result["hit_rate"] == result["mrr_at_k"] == 0
    assert result["evidence_hit_rate"] == 1


def test_parent_already_in_top_k_is_not_duplicated():
    blocks = linked()
    hits = rank(blocks, np.eye(2), np.array([0, 1]), 2)
    result = expand_evidence(hits, blocks)
    assert result[0]["parent_rule_in_results"] is True
    assert result[0]["related_evidence"] == []


def test_missing_parent_in_partial_index_fails_explicitly():
    example = linked()[1]
    with pytest.raises(ValueError, match="parent is missing"):
        expand_evidence([{"block_id": "example"}], [example])
