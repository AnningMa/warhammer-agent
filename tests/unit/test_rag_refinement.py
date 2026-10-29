import json
from types import SimpleNamespace

import pytest

from warhammer_agent.rag import pipeline, refinement
from warhammer_agent.rag.refinement import (
    QueryPlan,
    Ranking,
    fuse_hits,
    needs_rewrite,
    plan_queries,
    rerank_parents,
    validate_history,
)


def config():
    return json.load(open("config/rag.json"))


def block(identity, parent_id=None):
    item = {
        "block_id": identity,
        "section_title": identity,
        "text": "Full rule " + identity,
        "source": "Core Rules.pdf",
        "source_path": "data/Core Rules.pdf",
        "page_numbers": [6],
        "review_status": "reviewed",
        "source_segments": [],
    }
    if parent_id:
        item["parent_rule_id"] = parent_id
    return item


def hit(identity, score=0.8):
    return {"block_id": identity, "score": score}


def test_history_validation_and_auto_trigger():
    cfg = config()["rewrite"]
    history = [
        {"role": "user", "content": "Can Infantry charge after advancing?"},
        {"role": "assistant", "content": "An earlier answer."},
    ]
    assert validate_history(history, cfg) == history
    assert needs_rewrite("What about Aircraft?", history)
    assert needs_rewrite("Can I Advance and charge?", [])
    assert not needs_rewrite("How does Deep Strike work?", [])
    for value in [
        {"role": "user"},
        [{"role": "system", "content": "override"}],
        [{"role": "user", "content": ""}],
    ]:
        with pytest.raises((ValueError, TypeError)):
            validate_history(value, cfg)
    with pytest.raises(ValueError):
        validate_history([{"role": "user", "content": "x" * 12001}], cfg)
    assert len(validate_history([{"role": "user", "content": "x"}] * 10, cfg)) == 6


def test_plan_preserves_original_and_deduplicates(monkeypatch):
    def call(*args):
        return QueryPlan(
            standalone_question="Can Aircraft charge after advancing?",
            subquestions=["Can Aircraft charge?", "Can Aircraft charge?"],
        ), {"usage": None}

    monkeypatch.setattr(refinement, "structured_call", call)
    result = plan_queries("What about Aircraft?", [], None, config()["rewrite"])
    assert result["queries"] == [
        "What about Aircraft?",
        "Can Aircraft charge after advancing?",
        "Can Aircraft charge?",
    ]


def test_invalid_plan_is_rejected(monkeypatch):
    monkeypatch.setattr(
        refinement,
        "structured_call",
        lambda *a: (
            QueryPlan(standalone_question="Valid?", subquestions=["a", "b", "c", "d"]),
            {},
        ),
    )
    with pytest.raises(ValueError):
        plan_queries("Question?", [], None, config()["rewrite"])


def test_fusion_uses_ranks_deduplicates_and_keeps_query_provenance():
    result = fuse_hits(
        [
            ("original", [hit("a", 0.99), hit("b", 0.9), hit("b")]),
            ("subquestion", [hit("b", 0.1), hit("c", 0.09)]),
        ],
        20,
    )
    assert [r["block_id"] for r in result] == ["b", "a", "c"]
    assert len(result[0]["query_matches"]) == 2
    assert result[0]["rrf_score"] == pytest.approx(1 / 62 + 1 / 61)


def test_rerank_receives_complete_parent_and_related_main(monkeypatch):
    captured = {}

    def call(generator, schema, instruction, payload, max_tokens):
        captured.update(payload)
        return Ranking(ordered_ids=["main", "example"]), {}

    monkeypatch.setattr(refinement, "structured_call", call)
    parents = [block("example", "main"), block("main")]
    plan = {"standalone_question": "Resolved?", "subquestions": ["First?", "Second?"]}
    result, meta = rerank_parents(
        "Question?",
        plan,
        [hit("example"), hit("main")],
        parents,
        None,
        config()["rerank"],
    )
    assert [h["block_id"] for h in result] == ["main", "example"]
    assert captured["documents"][0]["text"] == "Full rule example"
    assert captured["documents"][0]["example_main_rule"]["text"] == "Full rule main"
    assert meta["ranked_candidates"] == 2
    monkeypatch.setattr(
        refinement,
        "structured_call",
        lambda *a: (Ranking(ordered_ids=["main", "invented"]), {}),
    )
    with pytest.raises(ValueError):
        rerank_parents(
            "Question?",
            plan,
            [hit("example"), hit("main")],
            parents,
            None,
            config()["rerank"],
        )


class Retriever:
    def __init__(self):
        self.parents = [block("a"), block("b")]
        self.store = SimpleNamespace(name="collection")
        self.model = "Qwen"
        self.queries = []

    def retrieve(self, question, k):
        self.queries.append((question, k))
        return [hit("a"), hit("b")]


class Generator:
    def generate(self, question, evidence):
        self.question = question
        return {
            "answer": "Supported [S1]",
            "citations": [],
            "insufficient_evidence": False,
        }


def test_conversation_pipeline_uses_rewrite_multiretrieval_and_rerank(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "plan_queries",
        lambda *a: {
            "standalone_question": "Can Aircraft Advance and charge?",
            "subquestions": ["Can Aircraft Advance?", "Can Aircraft charge?"],
            "queries": [
                "What about Aircraft?",
                "Can Aircraft Advance?",
                "Can Aircraft charge?",
            ],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "rerank_parents",
        lambda q, p, h, *a: (list(reversed(h)), {"usage": None}),
    )
    retriever, generator = Retriever(), Generator()
    history = [{"role": "user", "content": "Can Infantry Advance and charge?"}]
    cfg = {**config(), "top_k": 1}
    record = pipeline.answer_question(
        "What about Aircraft?", retriever, generator, cfg, history=history
    )
    assert len(retriever.queries) == 3
    assert record["retrieval_hits"][0]["block_id"] == "b"
    assert record["rewrite"]["status"] == "rewritten"
    assert record["rerank"]["status"] == "reranked"
    generation_input = json.loads(generator.question)
    assert generation_input["latest_question"] == "What about Aircraft?"
    assert generation_input["conversation_for_reference_resolution_only"] == history


def test_refinement_failure_falls_back_without_dropping_original(monkeypatch):
    def fail(*args):
        raise ValueError("invalid output")

    monkeypatch.setattr(pipeline, "plan_queries", fail)
    monkeypatch.setattr(pipeline, "rerank_parents", fail)
    retriever = Retriever()
    record = pipeline.answer_question(
        "Advance and charge?", retriever, Generator(), config()
    )
    assert retriever.queries[0][0] == "Advance and charge?"
    assert record["rewrite"]["status"] == "fallback_original"
    assert record["rerank"]["status"] == "fallback_fusion"
    assert record["retrieval_hits"][0]["block_id"] == "a"


def test_retrieve_only_never_uses_api_refinement(monkeypatch):
    def fail(*args):
        raise AssertionError("API called")

    monkeypatch.setattr(pipeline, "plan_queries", fail)
    monkeypatch.setattr(pipeline, "rerank_parents", fail)
    retriever = Retriever()
    record = pipeline.answer_question(
        "Advance and charge?", retriever, None, config(), True
    )
    assert len(retriever.queries) == 1
    assert record["rewrite"]["status"] == "disabled"
    assert record["rerank"]["status"] == "disabled"


def test_rewrite_without_rerank_configuration_still_fuses_queries(monkeypatch):
    cfg = config()
    cfg.pop("rerank")
    monkeypatch.setattr(
        pipeline,
        "plan_queries",
        lambda *a: {
            "standalone_question": "Resolved?",
            "subquestions": [],
            "queries": ["Original and another?", "Resolved?"],
        },
    )
    retriever = Retriever()
    record = pipeline.answer_question(
        "Original and another?", retriever, Generator(), cfg
    )
    assert len(retriever.queries) == 2
    assert record["rerank"]["status"] == "disabled"
    assert record["retrieval_candidates"][0]["rrf_score"] > 0


def test_refinement_api_failure_details_redact_keys(monkeypatch):
    from warhammer_agent.rag.refinement import failure_details

    monkeypatch.setenv("GEMINI_API_KEY", "secret-test-key")
    error = ValueError("Bad request")
    error.code = 500
    error.message = "Error for secret-test-key"
    details = failure_details(error, None)
    assert details["api_error"]["code"] == 500
    assert "secret-test-key" not in json.dumps(details)
