"""Unified English CLI for persistent PDF/SQL conversations."""

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from warhammer_agent.rag.cli import save_report
from warhammer_agent.rag.cli import validate_config as validate_rag
from warhammer_agent.rag.refinement import failure_details
from warhammer_agent.sql.cli import _validate_config as validate_sql

from .services import AgentServices
from .session import run_turn


def validate_config(config):
    for key in (
        "max_context_bytes",
        "sql_context_bytes",
        "max_history_messages",
        "max_history_chars",
        "routing_max_output_tokens",
    ):
        if type(config.get(key)) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    for key in ("rag_config", "sql_config", "checkpoints", "output_dir"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} must be a nonempty path")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--session-id",
        help="Continue a saved conversation, or omit to create a new session",
    )
    parser.add_argument("--config", type=Path, default=Path("config/agent.json"))
    parser.add_argument(
        "--json", action="store_true", help="Print the complete run record"
    )
    parser.add_argument(
        "--model",
        help="Override routing, rewriting, reranking and synthesis model; SQL keeps its own configuration",
    )
    args = parser.parse_args()
    root = Path.cwd()
    services = None
    config = None
    session_id = args.session_id or uuid4().hex
    try:
        config = json.loads(args.config.read_text())
        validate_config(config)
        services = AgentServices(root, config)
        if args.model is not None:
            services.rag["generation"]["model"] = args.model
        validate_rag(services.rag)
        validate_sql(services.sql)
        print(f"Session: {session_id}", file=sys.stderr, flush=True)
        record = run_turn(
            root,
            config,
            services,
            args.question,
            session_id,
            progress=lambda stage: print(
                f"Completed stage: {stage}", file=sys.stderr, flush=True
            ),
        )
        report = save_report(root, config, record)
        for error in record["errors"]:
            code = error.get("api_error", {}).get("code")
            label = f"; API {code}" if code is not None else ""
            print(
                f"Stage {error['stage']} failed ({error['error_type']}{label}); see the run report.",
                file=sys.stderr,
            )
        if args.json:
            print(
                json.dumps(
                    {**record, "report_path": str(report)}, ensure_ascii=False, indent=2
                )
            )
        else:
            print(record["answer"])
            for citation in record["citations"]:
                if citation["kind"] == "pdf":
                    label = f"{citation['source']} · {citation['section_title']} · PDF physical pages {citation['page_numbers']}"
                else:
                    label = f"{citation['database_path']} · tables {', '.join(citation['schema_tables'])}"
                print(f"[{citation['citation_id']}] {label}")
            print(
                f"Session: {session_id}\nStatus: {record['status']}\nRun report: {report}"
            )
        return 1 if record["status"] == "failed" else 0
    except Exception as error:  # noqa: BLE001 -- CLI boundary: safe diagnostics, never raw credentials.
        detail = failure_details(error, getattr(services, "_model", None))
        if config and isinstance(config.get("output_dir"), str):
            report = save_report(
                root,
                config,
                {
                    "question": args.question,
                    "session_id": session_id,
                    "status": "failed",
                    **detail,
                },
            )
            print(f"Failure report: {report}", file=sys.stderr)
        message = (
            str(error)
            if isinstance(error, (ValueError, TypeError, OSError, RuntimeError))
            and not hasattr(error, "code")
            else type(error).__name__
        )
        print(f"Agent failed: {message}", file=sys.stderr)
        return 1
    finally:
        if services is not None:
            services.close()
