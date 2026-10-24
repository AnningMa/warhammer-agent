"""Write machine-readable and reviewer-friendly evaluation reports."""

import json
from pathlib import Path
from typing import Any


def _format(value: Any, *, percent: bool = False) -> str:
    if value is None:
        return "n/a"
    if percent:
        return f"{100 * value:.1f}%"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def markdown_report(run: dict[str, Any]) -> str:
    summary = run["summary"]
    thresholds = run["thresholds"]
    metric_rows = [
        ("End-to-end pass rate", "end_to_end_pass_rate"),
        ("Route accuracy", "route_accuracy"),
        ("Status accuracy", "status_accuracy"),
        ("Agent trace accuracy", "trace_accuracy"),
        ("Required-source coverage", "required_source_coverage"),
        (f"PDF Hit Rate@{run['retrieval_k']}", "pdf_hit_rate_at_k"),
        (f"PDF Precision@{run['retrieval_k']}", "pdf_precision_at_k"),
        (f"PDF MAP@{run['retrieval_k']}", "pdf_map_at_k"),
        ("Context recall", "context_recall"),
        ("Context precision", "context_precision"),
        ("SQL execution success", "sql_execution_success_rate"),
        ("SQL result accuracy", "sql_result_accuracy"),
        ("Required-fact coverage", "required_fact_coverage"),
        ("Citation validity", "citation_validity"),
        ("Faithfulness (optional judge)", "faithfulness"),
        ("Answer relevancy (optional judge)", "answer_relevancy"),
        ("Factual correctness (optional judge)", "factual_correctness"),
    ]
    lines = [
        "# Warhammer Agent Evaluation",
        "",
        f"- Run ID: `{run['run_id']}`",
        f"- Dataset: `{run['dataset']}`",
        f"- Model override: `{run.get('model') or 'configured defaults'}`",
        f"- Judge model: `{run.get('judge_model') or 'disabled'}`",
        f"- Cases: {summary['total_cases']}",
        f"- Passed: {summary['passed_cases']}",
        "",
        "## Metrics",
        "",
        "| Metric | Result | Target | Meets target |",
        "|---|---:|---:|:---:|",
    ]
    for label, key in metric_rows:
        value = summary.get(key)
        target = thresholds.get(key)
        meets = (
            "n/a"
            if value is None or target is None
            else ("yes" if value >= target else "no")
        )
        lines.append(
            f"| {label} | {_format(value, percent=True)} | "
            f"{_format(target, percent=True)} | {meets} |"
        )
    lines.extend(
        [
            "",
            "## Runtime",
            "",
            f"- Average latency: {_format(summary['average_latency_seconds'])} seconds",
            f"- Median latency: {_format(summary['median_latency_seconds'])} seconds",
            f"- Total reported agent tokens: {summary['total_tokens']}",
            f"- Total reported judge tokens: {summary['total_judge_tokens']}",
            "",
            "## Results by category",
            "",
            "| Category | Cases | Pass rate | Route accuracy |",
            "|---|---:|---:|---:|",
        ]
    )
    for category, values in summary["by_category"].items():
        lines.append(
            f"| {category} | {values['cases']} | "
            f"{_format(values['pass_rate'], percent=True)} | "
            f"{_format(values['route_accuracy'], percent=True)} |"
        )
    lines.extend(
        [
            "",
            "## Case details",
            "",
            "| Case | Category | Route | Status | Sources | Facts | Result |",
            "|---|---|---|---|---:|---:|:---:|",
        ]
    )
    for result in run["results"]:
        route = "yes" if result["route_correct"] else "no"
        status = "yes" if result["status_correct"] else "no"
        sources = "yes" if result["required_source_coverage"] else "no"
        lines.append(
            f"| `{result['id']}` | {result['category']} | {route} | {status} | "
            f"{sources} | "
            f"{_format(result['required_fact_coverage'], percent=True)} | "
            f"{'pass' if result['passed'] else 'fail'} |"
        )
    failures = [result for result in run["results"] if not result["passed"]]
    lines.extend(["", "## Failed cases", ""])
    if not failures:
        lines.append("None.")
    for result in failures:
        failed = [
            name
            for name, passed in (
                ("route", result["route_correct"]),
                ("status", result["status_correct"]),
                ("trace", result["trace_correct"]),
                ("required sources", result["required_source_coverage"]),
                ("citations", result["citation_valid"]),
                ("required facts", result["required_fact_coverage"] == 1.0),
                ("SQL result", result["sql_result_correct"] is not False),
                ("PDF retrieval", result["pdf_hit_rate_at_k"] in {None, 1.0}),
            )
            if not passed
        ]
        lines.append(f"- `{result['id']}`: {', '.join(failed)}")
    lines.extend(
        [
            "",
            (
                "The deterministic metrics compare the frozen references with "
                "structured run records. They do not replace human review or an "
                "optional independent LLM judge for semantic faithfulness and answer "
                "relevance."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(run: dict[str, Any], directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "evaluation.json"
    markdown_path = directory / "evaluation.md"
    json_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n")
    markdown_path.write_text(markdown_report(run))
    return json_path, markdown_path
