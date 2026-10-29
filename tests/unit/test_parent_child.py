import copy

import numpy as np

from warhammer_agent.embeddings.parent_child import build_records, parent_hits


class Tokenizer:
    def encode(self, text, **kwargs):
        return text.split()


def parent(text, identity="rule"):
    return {
        "block_id": identity,
        "text": text,
        "embedding_text": text,
        "section_path": ["RULE"],
        "section_title": "RULE",
        "page_numbers": [1, 2],
        "page_number": 1,
        "source_segments": [
            {"page_number": 1, "text_span": {"start": 0, "end": len(text) // 2}},
            {
                "page_number": 2,
                "text_span": {"start": len(text) // 2, "end": len(text)},
            },
        ],
    }


def test_short_rule_unchanged_and_parent_preserved():
    source = parent("A short complete rule.")
    original = copy.deepcopy(source)
    records, children = build_records([source], Tokenizer(), 20, 10)
    assert source == original
    assert records[0]["text"] == source["text"]
    assert children[0]["embedding_text"] == source["embedding_text"]
    assert children[0]["parent_block_id"] == source["block_id"]


def test_long_rule_spans_cover_content_and_table_is_atomic():
    text = "# RULE\n\nFirst sentence contains many words here. Second sentence contains many words too.\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\nFinal exception applies only in this situation."
    source = parent(text)
    records, children = build_records([source], Tokenizer(), 20, 13)
    assert len(children) > 1
    assert records[0]["text"] == text
    covered = set()
    for child in children:
        span = child["parent_text_span"]
        assert child["text"] == text[span["start"] : span["end"]]
        covered.update(range(span["start"], span["end"]))
        assert child["page_numbers"] == sorted(
            {s["page_number"] for s in child["source_segments"]}
        )
    assert all(
        i in covered for i, character in enumerate(text) if not character.isspace()
    )
    table_children = [c for c in children if "| a | b |" in c["text"]]
    assert len(table_children) == 1
    assert "| 1 | 2 |" in table_children[0]["text"]


def test_unique_parent_ranking_uses_best_child():
    parents = [parent("a", "a"), parent("b", "b")]
    children = [
        {"block_id": "a1", "parent_block_id": "a"},
        {"block_id": "a2", "parent_block_id": "a"},
        {"block_id": "b1", "parent_block_id": "b"},
    ]

    class Store:
        def query(self, vector, k):
            return [
                {"block_id": c["block_id"], "score": 1 - i / 10}
                for i, c in enumerate(children)
            ][:k]

    hits = parent_hits(Store(), children, parents, np.ones(3), 2)
    assert [h["block_id"] for h in hits] == ["a", "b"]
    assert hits[0]["retrieval_child_id"] == "a1"
