import json

import pytest

from warhammer_agent.evaluation.cli import _resume_settings
from warhammer_agent.evaluation.dataset import EvaluationCase, load_cases
from warhammer_agent.evaluation.metrics import evaluate_case, summarize
from warhammer_agent.evaluation.runner import _record_needs_retry


def case(**updates):
    payload = {
        "id": "hybrid",
        "category": "hybrid",
        "question": "Question?",
        "expected_route": "hybrid",
        "expected_status": "answered",
        "required_sources": ["sql", "pdf"],
        "expected_pdf_sections": ["RULE"],
        "expected_sql_values": [6],
        "required_facts": [["six", "6"], ["rule"]],
        "reference_answer": "Six and a rule.",
        "reference_contexts": ["reference"],
    }
    payload.update(updates)
    return EvaluationCase.from_dict(payload)


def record():
    pdf = {
        "block_id": "rule",
        "section_title": "RULE",
        "citation_id": "S2",
        "kind": "pdf",
    }
    sql = {
        "status": "executed",
        "rows": [{"value": 6}],
        "citation_id": "S1",
        "kind": "sql",
    }
    return {
        "route": {"intent": "hybrid"},
        "status": "answered",
        "pdf": {
            "reranked_candidates": [
                {"block_id": "rule", "section_title": "RULE"},
                {"block_id": "noise", "section_title": "NOISE"},
            ]
        },
        "sql": sql,
        "evidence": [sql, pdf],
        "answer": "Six is supported by the rule [S1] [S2]",
        "citations": [sql, pdf],
        "errors": [],
        "usage": {"route": {"total_token_count": 10}},
        "elapsed_seconds": 2.0,
    }


def test_frozen_dataset_loads_and_covers_all_categories():
    cases = load_cases(__import__("pathlib").Path("tests/eval_cases/agent.json"))
    assert len(cases) == 12
    assert {item.category for item in cases} == {
        "rules",
        "database",
        "hybrid",
        "clarification",
    }


def test_case_evaluation_scores_retrieval_trace_answer_and_system_metrics():
    result = evaluate_case(case(), record(), k=2)
    assert result["passed"]
    assert result["trace_correct"]
    assert result["pdf_hit_rate_at_k"] == 1
    assert result["pdf_precision_at_k"] == 0.5
    assert result["pdf_average_precision_at_k"] == 1
    assert result["context_recall"] == result["context_precision"] == 1
    assert result["sql_result_correct"]
    assert result["citation_valid"]
    assert result["token_count"] == 10


def test_retrieval_metrics_count_each_gold_section_once():
    output = record()
    output["pdf"]["reranked_candidates"] = [
        {"block_id": "rule-1", "section_title": "RULE"},
        {"block_id": "rule-2", "section_title": "RULE"},
        {"block_id": "noise", "section_title": "NOISE"},
    ]

    result = evaluate_case(case(), output, k=3)

    assert result["pdf_precision_at_k"] == pytest.approx(1 / 3)
    assert result["pdf_average_precision_at_k"] == 1


@pytest.mark.parametrize(
    ("case_id", "answer"),
    [
        (
            "database_intercessor_toughness",
            "The Toughness of an Intercessor Squad model is 4 [S1].",
        ),
        (
            "database_heavy_intercessor_profile",
            (
                "A Heavy Intercessor Squad model has a Toughness of 6, "
                "3 Wounds, and a Save of 3+ [S1]."
            ),
        ),
    ],
)
def test_reviewed_natural_fact_phrasings_are_accepted(case_id, answer):
    cases = load_cases(__import__("pathlib").Path("tests/eval_cases/agent.json"))
    item = next(case for case in cases if case.id == case_id)
    output = record()
    output["answer"] = answer

    result = evaluate_case(item, output)

    assert result["required_fact_coverage"] == 1


def test_reviewed_scoring_case_separates_points_from_victory_conditions():
    cases = load_cases(__import__("pathlib").Path("tests/eval_cases/agent.json"))
    item = next(case for case in cases if case.id == "rules_scoring")

    assert item.expected_status == "insufficient_evidence"
    assert item.expected_pdf_sections == ("CAPTURE AND CONTROL",)
    assert len(item.required_facts) == 3


def test_reviewed_cover_wording_accepts_ap_of_zero():
    cases = load_cases(__import__("pathlib").Path("tests/eval_cases/agent.json"))
    item = next(case for case in cases if case.id == "hybrid_intercessor_cover")
    output = record()
    output["answer"] = (
        "An Intercessor Squad model has a Save characteristic of 3+ [S1]. "
        "Cover cannot improve it against an AP of 0 attack [S2]."
    )

    assert evaluate_case(item, output)["required_fact_coverage"] == 1


def test_resume_retries_partial_answers_with_api_errors():
    output = record()
    output["status"] = "partial_answer"
    output["errors"] = [
        {"stage": "sql", "api_error": {"code": 403, "message": "forbidden"}}
    ]

    assert _record_needs_retry(output)
    assert not _record_needs_retry({**output, "errors": []})
    assert not _record_needs_retry(record())


def test_wrong_route_missing_source_and_value_fail_end_to_end():
    output = record()
    output["route"] = {"intent": "rules"}
    output["sql"] = {}
    output["evidence"] = output["evidence"][1:]
    output["citations"] = output["citations"][1:]
    output["answer"] = "Rule [S2]"
    result = evaluate_case(case(), output)
    assert not result["passed"]
    assert not result["route_correct"]
    assert not result["trace_correct"]
    assert result["sql_result_correct"] is False


def test_clarification_requires_no_tools_or_citations():
    item = case(
        id="clarify",
        category="clarification",
        expected_route="database",
        expected_status="clarification",
        required_sources=[],
        expected_pdf_sections=[],
        expected_sql_values=[],
        required_facts=[["which unit"]],
    )
    output = {
        "route": {"intent": "database"},
        "status": "clarification",
        "pdf": {},
        "sql": {},
        "evidence": [],
        "answer": "Which unit do you mean?",
        "citations": [],
        "errors": [],
    }
    assert evaluate_case(item, output)["passed"]


def test_dataset_rejects_duplicate_ids(tmp_path):
    payload = [
        {
            "id": "same",
            "category": "rules",
            "question": "Question?",
            "expected_route": "rules",
            "expected_status": "answered",
            "required_sources": ["pdf"],
            "expected_pdf_sections": ["RULE"],
            "expected_sql_values": [],
            "required_facts": [["fact"]],
            "reference_answer": "Answer.",
            "reference_contexts": ["Context."],
        }
    ] * 2
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="unique"):
        load_cases(path)


def test_summary_ignores_non_applicable_metrics():
    result = evaluate_case(case(), record())
    summary = summarize([result])
    assert summary["total_cases"] == summary["passed_cases"] == 1
    assert summary["route_accuracy"] == 1
    assert summary["total_tokens"] == 10
    assert summary["total_judge_tokens"] == 0
    assert summary["faithfulness"] is None


def test_optional_judge_scores_are_aggregated():
    judged = {
        "faithfulness_normalized": 1.0,
        "answer_relevancy_normalized": 0.8,
        "factual_correctness_normalized": 0.6,
    }
    result = evaluate_case(case(), record(), judge=judged)
    summary = summarize([result])
    assert summary["faithfulness"] == 1.0
    assert summary["answer_relevancy"] == 0.8
    assert summary["factual_correctness"] == 0.6


def test_resume_settings_fall_back_to_completed_report(tmp_path):
    (tmp_path / "evaluation.json").write_text(
        json.dumps(
            {
                "model": "answer-model",
                "judge_model": None,
                "results": [{"id": "rules_deep_strike"}],
            }
        )
    )
    assert _resume_settings(tmp_path) == {
        "case_ids": ["rules_deep_strike"],
        "model": "answer-model",
        "judge_model": None,
    }
