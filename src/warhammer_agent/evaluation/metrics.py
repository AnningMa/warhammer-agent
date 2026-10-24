"""Deterministic retriever, trace, answer, and system metrics."""

import re
from collections.abc import Iterable
from statistics import mean, median
from typing import Any

from .dataset import EvaluationCase


def normalize(value: Any) -> str:
    return " ".join(str(value).casefold().split())


def _flatten(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        for nested in value.values():
            yield from _flatten(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _flatten(nested)
    else:
        yield value


def _pdf_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
    pdf = record.get("pdf") or {}
    candidates = pdf.get("reranked_candidates") or pdf.get("retrieval_candidates") or []
    seen, unique = set(), []
    for item in candidates:
        identity = item.get("block_id")
        if identity not in seen:
            unique.append(item)
            seen.add(identity)
    return unique


def _retrieval_metrics(case: EvaluationCase, record: dict[str, Any], k: int) -> dict:
    if "pdf" not in case.required_sources:
        return {
            "pdf_hit_rate_at_k": None,
            "pdf_precision_at_k": None,
            "pdf_average_precision_at_k": None,
            "context_recall": None,
            "context_precision": None,
        }
    gold = {normalize(title) for title in case.expected_pdf_sections}
    ranked = _pdf_candidates(record)[:k]
    relevance = [normalize(item.get("section_title", "")) in gold for item in ranked]
    hit = float(any(relevance))
    precision = sum(relevance) / k
    running, precision_sum = 0, 0.0
    for rank, relevant in enumerate(relevance, 1):
        if relevant:
            running += 1
            precision_sum += running / rank
    average_precision = precision_sum / min(len(gold), k)
    pdf_evidence = [
        item for item in record.get("evidence", []) if item.get("kind") == "pdf"
    ]
    evidence_titles = [
        normalize(item.get("section_title", "")) for item in pdf_evidence
    ]
    recall = len(gold & set(evidence_titles)) / len(gold)
    context_precision = (
        sum(title in gold for title in evidence_titles) / len(evidence_titles)
        if evidence_titles
        else 0.0
    )
    return {
        "pdf_hit_rate_at_k": hit,
        "pdf_precision_at_k": precision,
        "pdf_average_precision_at_k": average_precision,
        "context_recall": recall,
        "context_precision": context_precision,
    }


def _citation_valid(record: dict[str, Any]) -> bool:
    answer = record.get("answer", "")
    inline = set(re.findall(r"\[(S\d+)\]", answer))
    citations = record.get("citations", [])
    citation_ids = [item.get("citation_id") for item in citations]
    evidence_ids = {
        item.get("citation_id") for item in record.get("evidence", [])
    }
    if record.get("status") == "clarification":
        return not inline and not citations
    return (
        bool(inline)
        and len(citation_ids) == len(set(citation_ids))
        and inline == set(citation_ids)
        and inline <= evidence_ids
    )


def _actual_tool_sources(record: dict[str, Any]) -> set[str]:
    sources = set()
    if record.get("pdf"):
        sources.add("pdf")
    if record.get("sql"):
        sources.add("sql")
    return sources


def _fact_coverage(case: EvaluationCase, answer: str) -> float:
    if not case.required_facts:
        return 1.0
    normalized = normalize(answer)
    matched = sum(
        any(normalize(alternative) in normalized for alternative in group)
        for group in case.required_facts
    )
    return matched / len(case.required_facts)


def _sql_values_correct(case: EvaluationCase, record: dict[str, Any]) -> bool | None:
    if "sql" not in case.required_sources:
        return None
    rows = (record.get("sql") or {}).get("rows", [])
    actual = {normalize(value) for value in _flatten(rows)}
    return all(normalize(value) in actual for value in case.expected_sql_values)


def _token_count(record: dict[str, Any]) -> int:
    total = 0
    for usage in (record.get("usage") or {}).values():
        if isinstance(usage, dict) and isinstance(usage.get("total_token_count"), int):
            total += usage["total_token_count"]
    return total


def evaluate_case(
    case: EvaluationCase,
    record: dict[str, Any],
    k: int = 5,
    judge: dict[str, Any] | None = None,
) -> dict:
    if k < 1:
        raise ValueError("k must be positive")
    route = (record.get("route") or {}).get("intent")
    route_correct = route == case.expected_route
    expected_sources = set(case.required_sources)
    actual_tools = _actual_tool_sources(record)
    cited_sources = {item.get("kind") for item in record.get("citations", [])}
    status_correct = record.get("status") == case.expected_status
    trace_correct = route_correct and actual_tools == expected_sources
    source_coverage = expected_sources <= cited_sources
    sql_executed = (
        (record.get("sql") or {}).get("status") == "executed"
        if "sql" in expected_sources
        else None
    )
    sql_result = _sql_values_correct(case, record)
    fact_coverage = _fact_coverage(case, record.get("answer", ""))
    citation_validity = _citation_valid(record)
    retrieval = _retrieval_metrics(case, record, k)
    checks = [
        route_correct,
        status_correct,
        trace_correct,
        citation_validity,
        fact_coverage == 1.0,
    ]
    if expected_sources:
        checks.append(source_coverage)
    if "pdf" in expected_sources:
        checks.extend(
            [retrieval["pdf_hit_rate_at_k"] == 1.0, retrieval["context_recall"] == 1.0]
        )
    if "sql" in expected_sources:
        checks.extend([sql_executed is True, sql_result is True])
    return {
        "id": case.id,
        "category": case.category,
        "question": case.question,
        "expected_route": case.expected_route,
        "actual_route": route,
        "expected_status": case.expected_status,
        "actual_status": record.get("status"),
        "route_correct": route_correct,
        "status_correct": status_correct,
        "trace_correct": trace_correct,
        "required_sources": list(case.required_sources),
        "actual_tool_sources": sorted(actual_tools),
        "cited_sources": sorted(source for source in cited_sources if source),
        "required_source_coverage": source_coverage,
        "sql_executed": sql_executed,
        "sql_result_correct": sql_result,
        "required_fact_coverage": fact_coverage,
        "citation_valid": citation_validity,
        "faithfulness": (judge or {}).get("faithfulness_normalized"),
        "answer_relevancy": (judge or {}).get("answer_relevancy_normalized"),
        "factual_correctness": (judge or {}).get("factual_correctness_normalized"),
        "judge": judge,
        "judge_token_count": (
            ((judge or {}).get("usage") or {}).get("total_token_count", 0)
        ),
        **retrieval,
        "elapsed_seconds": record.get("elapsed_seconds"),
        "token_count": _token_count(record),
        "errors": record.get("errors", []),
        "passed": all(checks),
    }


def _average(results: list[dict], key: str) -> float | None:
    values = [result[key] for result in results if result.get(key) is not None]
    return mean(values) if values else None


def summarize(results: list[dict]) -> dict:
    if not results:
        raise ValueError("Cannot summarize an empty evaluation")
    latencies = [
        result["elapsed_seconds"]
        for result in results
        if isinstance(result.get("elapsed_seconds"), (int, float))
    ]
    return {
        "total_cases": len(results),
        "passed_cases": sum(result["passed"] for result in results),
        "end_to_end_pass_rate": _average(results, "passed"),
        "route_accuracy": _average(results, "route_correct"),
        "status_accuracy": _average(results, "status_correct"),
        "trace_accuracy": _average(results, "trace_correct"),
        "required_source_coverage": _average(results, "required_source_coverage"),
        "pdf_hit_rate_at_k": _average(results, "pdf_hit_rate_at_k"),
        "pdf_precision_at_k": _average(results, "pdf_precision_at_k"),
        "pdf_map_at_k": _average(results, "pdf_average_precision_at_k"),
        "context_recall": _average(results, "context_recall"),
        "context_precision": _average(results, "context_precision"),
        "sql_execution_success_rate": _average(results, "sql_executed"),
        "sql_result_accuracy": _average(results, "sql_result_correct"),
        "required_fact_coverage": _average(results, "required_fact_coverage"),
        "citation_validity": _average(results, "citation_valid"),
        "faithfulness": _average(results, "faithfulness"),
        "answer_relevancy": _average(results, "answer_relevancy"),
        "factual_correctness": _average(results, "factual_correctness"),
        "average_latency_seconds": mean(latencies) if latencies else None,
        "median_latency_seconds": median(latencies) if latencies else None,
        "total_tokens": sum(result.get("token_count", 0) for result in results),
        "total_judge_tokens": sum(
            result.get("judge_token_count", 0) for result in results
        ),
        "by_category": {
            category: {
                "cases": len(subset),
                "pass_rate": _average(subset, "passed"),
                "route_accuracy": _average(subset, "route_correct"),
            }
            for category in sorted({result["category"] for result in results})
            if (subset := [r for r in results if r["category"] == category])
        },
    }
