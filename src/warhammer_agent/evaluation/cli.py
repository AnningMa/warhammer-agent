"""Command-line entry point for resumable end-to-end agent evaluation."""

import argparse
import json
import sys
from pathlib import Path

from .dataset import load_cases
from .runner import run_evaluation, select_cases, validate_config


def _resume_settings(path: Path) -> dict:
    selection = path / "selection.json"
    if selection.exists():
        return json.loads(selection.read_text())
    report = path / "evaluation.json"
    if report.exists():
        payload = json.loads(report.read_text())
        return {
            "case_ids": [item["id"] for item in payload.get("results", [])],
            "model": payload.get("model"),
            "judge_model": payload.get("judge_model"),
        }
    raise ValueError("The resume directory has no selection or evaluation report")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/evaluation.json"))
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument(
        "--category",
        action="append",
        choices=["rules", "database", "hybrid", "clarification"],
        default=[],
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--model",
        help="Override the Gemini model for routing, PDF refinement, SQL and synthesis",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        help="Existing storage/evaluation/runs/<run-id> directory to continue",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Run the optional independent Gemini semantic judge",
    )
    parser.add_argument(
        "--judge-model",
        help="Override config/evaluation.json judge.model; requires --judge",
    )
    args = parser.parse_args()
    root = Path.cwd()
    try:
        config = json.loads(args.config.read_text())
        validate_config(config)
        resume = args.resume.resolve() if args.resume else None
        if resume is not None and not resume.is_dir():
            raise ValueError("--resume must name an existing evaluation run directory")
        if args.judge_model and not args.judge:
            raise ValueError("--judge-model requires --judge")
        saved = _resume_settings(resume) if resume else {}
        identities = set(args.case_id)
        if resume and not identities and not args.category and args.limit is None:
            identities = set(saved.get("case_ids", []))
        cases = load_cases(root / config["dataset"])
        cases = select_cases(
            cases,
            identities=identities,
            categories=set(args.category),
            limit=args.limit,
        )
        model = args.model or saved.get("model")
        judge_model = None
        if args.judge or saved.get("judge_model"):
            judge_model = (
                args.judge_model or saved.get("judge_model") or config["judge"]["model"]
            )
        run, json_path, markdown_path = run_evaluation(
            root,
            config,
            cases,
            model=model,
            judge_model=judge_model,
            resume=resume,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        summary = run["summary"]
        print(f"Cases: {summary['passed_cases']}/{summary['total_cases']} passed")
        print(f"Route accuracy: {summary['route_accuracy']:.1%}")
        print(f"Trace accuracy: {summary['trace_accuracy']:.1%}")
        print(f"JSON report: {json_path}")
        print(f"Markdown report: {markdown_path}")
        return 0
    except Exception as error:  # noqa: BLE001 -- concise local diagnostics.
        print(f"Evaluation failed: {error}", file=sys.stderr)
        return 1
