"""Ask a local PDF question through Qwen/Chroma and Gemini."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .generation import GeminiGenerator
from .pipeline import RuleRetriever, answer_question
from .refinement import validate_history


def validate_config(config):
    for name in ["top_k", "max_context_bytes", "max_question_chars", "cpu_threads"]:
        if type(config[name]) is not int or config[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    if type(config["qwen_local_files_only"]) is not bool:
        raise ValueError("qwen_local_files_only must be boolean")
    generation = config["generation"]
    for name in ["timeout_ms", "attempts", "max_output_tokens"]:
        if type(generation[name]) is not int or generation[name] < 1:
            raise ValueError(f"generation.{name} must be a positive integer")
    if not generation["model"].strip() or not generation["api_key_env"].strip():
        raise ValueError("generation model and api_key_env cannot be blank")
    value = generation["temperature"]
    if type(value) not in (float, int) or not 0 <= value <= 2:
        raise ValueError("temperature must be between 0 and 2")
    for section, fields in [
        (
            "rewrite",
            [
                "max_subquestions",
                "max_query_chars",
                "max_history_messages",
                "max_history_chars",
                "max_output_tokens",
            ],
        ),
        (
            "rerank",
            [
                "candidate_k",
                "per_query_k",
                "rrf_constant",
                "max_input_bytes",
                "max_output_tokens",
            ],
        ),
    ]:
        if section not in config:
            continue
        if type(config[section]["enabled"]) is not bool:
            raise ValueError(f"{section}.enabled must be boolean")
        for field in fields:
            if type(config[section][field]) is not int or config[section][field] < 1:
                raise ValueError(f"{section}.{field} must be a positive integer")
    if config.get("rewrite", {}).get("max_subquestions", 3) > 3:
        raise ValueError("max_subquestions cannot exceed 3")


def save_report(root, config, record):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / config["output_dir"] / f"{stamp}_{uuid4().hex[:8]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"created_at": stamp, **record}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--config", type=Path, default=Path("config/rag.json"))
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--model", help="Override Gemini generation model")
    parser.add_argument(
        "--history", type=Path, help="JSON array of prior role/content messages"
    )
    parser.add_argument("--no-rewrite", action="store_true")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument(
        "--retrieve-only",
        action="store_true",
        help="Real local retrieval, no Gemini API call",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the complete run record as JSON"
    )
    args = parser.parse_args()
    retriever = generator = None
    config = None
    root = Path.cwd()
    try:
        config = json.loads(args.config.read_text())
        if args.top_k is not None:
            config["top_k"] = args.top_k
        if args.model is not None:
            config["generation"]["model"] = args.model
        if args.no_rewrite and "rewrite" in config:
            config["rewrite"]["enabled"] = False
        if args.no_rerank and "rerank" in config:
            config["rerank"]["enabled"] = False
        validate_config(config)
        history = json.loads(args.history.read_text()) if args.history else []
        history = validate_history(
            history,
            config.get(
                "rewrite", {"max_history_messages": 6, "max_history_chars": 12000}
            ),
        )
        if (
            not args.question.strip()
            or len(args.question) > config["max_question_chars"]
        ):
            raise ValueError(
                "The question must be nonempty and within max_question_chars"
            )
        if not args.retrieve_only:
            generator = GeminiGenerator(root, config["generation"])
        retriever = RuleRetriever(root, config)
        record = answer_question(
            args.question,
            retriever,
            generator,
            config,
            args.retrieve_only,
            history=history,
        )
        report = save_report(root, config, record)
        for step, label in [("rewrite", "Query rewriting"), ("rerank", "Reranking")]:
            if record[step]["status"].startswith("fallback_"):
                print(
                    f"{label} failed; using fallback results. See the run report for details.",
                    file=sys.stderr,
                )
        if args.json:
            print(
                json.dumps(
                    {**record, "report_path": str(report)}, ensure_ascii=False, indent=2
                )
            )
        elif args.retrieve_only:
            for item in record["evidence"]:
                print(
                    f"[{item['citation_id']}] {item['section_title']} — PDF physical pages {item['page_numbers']}"
                )
            print(f"Retrieved evidence saved: {report}")
        else:
            print(record["answer"])
            for item in record["citations"]:
                print(
                    f"[{item['citation_id']}] {item['source']} · {item['section_title']} · PDF physical pages {item['page_numbers']}"
                )
            print(f"Run report: {report}")
        return 0
    except Exception as error:  # noqa: BLE001 -- CLI boundary: persist diagnostics without leaking SDK URLs/keys.
        record = getattr(
            error,
            "rag_record",
            {
                "question": args.question,
                "status": "failed",
                "error_type": type(error).__name__,
            },
        )
        if hasattr(error, "code") and hasattr(error, "message"):
            message = str(error.message)
            key = (
                os.environ.get(config["generation"]["api_key_env"], "")
                if config
                else ""
            )
            if key:
                message = message.replace(key, "[REDACTED]")
            record["api_error"] = {"code": error.code, "message": message[:1200]}
        if config is not None and "output_dir" in config:
            report = save_report(root, config, record)
            print(f"Failure report: {report}", file=sys.stderr)
        if isinstance(error, (ValueError, TypeError, FileNotFoundError)):
            print(f"RAG failed: {error}", file=sys.stderr)
        else:
            print(
                f"RAG failed: {type(error).__name__}; check connectivity, model access, quota, and configuration.",
                file=sys.stderr,
            )
            if "api_error" in record:
                print(
                    f"API {record['api_error']['code']}: {record['api_error']['message']}",
                    file=sys.stderr,
                )
        return 1
    finally:
        if retriever is not None:
            retriever.close()
        if generator is not None:
            generator.close()
