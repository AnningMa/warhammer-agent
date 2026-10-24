"""Run frozen cases through the real agent with resumable per-case storage."""

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from warhammer_agent.agent.services import AgentServices
from warhammer_agent.agent.session import run_turn
from warhammer_agent.rag.generation import GeminiGenerator
from warhammer_agent.rag.refinement import failure_details

from .dataset import EvaluationCase
from .judge import judge_answer
from .metrics import evaluate_case, summarize
from .report import write_reports


def validate_config(config: dict[str, Any]) -> None:
    for key in ("dataset", "agent_config", "output_dir"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} must be a nonempty path")
    if type(config.get("retrieval_k")) is not int or config["retrieval_k"] < 1:
        raise ValueError("retrieval_k must be a positive integer")
    thresholds = config.get("thresholds")
    if not isinstance(thresholds, dict):
        raise TypeError("thresholds must be an object")
    for key, value in thresholds.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 1
        ):
            raise ValueError("Each threshold must be a number between 0 and 1")
    judge = config.get("judge")
    if not isinstance(judge, dict):
        raise TypeError("judge must be an object")
    if not isinstance(judge.get("model"), str) or not judge["model"].strip():
        raise ValueError("judge.model must be a nonempty string")
    if (
        type(judge.get("max_output_tokens")) is not int
        or judge["max_output_tokens"] < 1
    ):
        raise ValueError("judge.max_output_tokens must be a positive integer")


def select_cases(
    cases: list[EvaluationCase],
    identities: set[str] | None = None,
    categories: set[str] | None = None,
    limit: int | None = None,
) -> list[EvaluationCase]:
    selected = [
        case
        for case in cases
        if (not identities or case.id in identities)
        and (not categories or case.category in categories)
    ]
    if identities:
        missing = identities - {case.id for case in selected}
        if missing:
            raise ValueError(f"Unknown case IDs: {sorted(missing)}")
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive")
        selected = selected[:limit]
    if not selected:
        raise ValueError("No evaluation cases matched the selection")
    return selected


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{uuid4().hex[:8]}"


def _read_case_result(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return payload if isinstance(payload.get("record"), dict) else None


def run_evaluation(
    root: Path,
    config: dict[str, Any],
    cases: list[EvaluationCase],
    *,
    model: str | None = None,
    judge_model: str | None = None,
    resume: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    validate_config(config)
    run_id = resume.name if resume else _new_run_id()
    run_dir = resume or root / config["output_dir"] / "runs" / run_id
    case_dir = run_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    selection_path = run_dir / "selection.json"
    selection = {
        "case_ids": [case.id for case in cases],
        "model": model,
        "judge_model": judge_model,
    }
    if selection_path.exists():
        saved_selection = json.loads(selection_path.read_text())
        if saved_selection.get("case_ids") != selection["case_ids"]:
            raise ValueError("The resumed case selection does not match this run")
    else:
        selection_path.write_text(
            json.dumps(selection, ensure_ascii=False, indent=2) + "\n"
        )
    agent_config = json.loads((root / config["agent_config"]).read_text())
    services = AgentServices(root, agent_config)
    if model:
        services.rag["generation"]["model"] = model
        services.sql["generation"]["model"] = model
    judge = None
    if judge_model:
        settings = {
            **services.rag["generation"],
            "model": judge_model,
            "max_output_tokens": config["judge"]["max_output_tokens"],
        }
        judge = GeminiGenerator(root, settings)
    results = []
    try:
        for index, case in enumerate(cases, 1):
            path = case_dir / f"{case.id}.json"
            saved = _read_case_result(path)
            record = saved["record"] if saved else None
            judged = saved.get("judge") if saved else None
            # API/quota failures remain resumable instead of becoming frozen results.
            if record is not None and record.get("status") == "failed":
                record = None
                judged = None
            if isinstance(judged, dict) and "error" in judged:
                judged = None
            if progress:
                action = "Reusing" if record is not None else "Running"
                progress(f"[{index}/{len(cases)}] {action} {case.id}")
            if record is None:
                session_id = f"eval_{run_id}_{case.id}"
                try:
                    record = run_turn(
                        root,
                        agent_config,
                        services,
                        case.question,
                        session_id=session_id,
                    )
                except Exception as error:  # noqa: BLE001 -- save a resumable failure.
                    record = {
                        "question": case.question,
                        "route": {},
                        "pdf": {},
                        "sql": {},
                        "evidence": [],
                        "answer": "",
                        "citations": [],
                        "errors": [{"stage": "runner", **failure_details(error, None)}],
                        "status": "failed",
                    }
            if judge is not None and judged is None:
                try:
                    judged = judge_answer(
                        judge, case, record, config["judge"]["max_output_tokens"]
                    )
                except Exception as error:  # noqa: BLE001 -- retain local results.
                    judged = {"error": failure_details(error, judge)}
            path.write_text(
                json.dumps(
                    {"case_id": case.id, "record": record, "judge": judged},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            results.append(
                evaluate_case(case, record, config["retrieval_k"], judge=judged)
            )
    finally:
        if judge is not None:
            judge.close()
        services.close()
    run = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": config["dataset"],
        "model": model,
        "judge_model": judge_model,
        "retrieval_k": config["retrieval_k"],
        "thresholds": config["thresholds"],
        "summary": summarize(results),
        "results": results,
    }
    json_path, markdown_path = write_reports(run, run_dir)
    return run, json_path, markdown_path
