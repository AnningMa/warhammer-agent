"""Query the local Warhammer SQLite database through the safe SQL pipeline."""

import argparse
import json
import sys
from pathlib import Path

from .database import ReadOnlyDatabase, SQLExecutionError
from .generator import GeminiSQLGenerator
from .retriever import SQLRetriever
from .schema import SchemaCatalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--config", type=Path, default=Path("config/sql.json"))
    parser.add_argument("--database", type=Path)
    parser.add_argument("--timeout-ms", type=int, help="Override Gemini timeout")
    parser.add_argument("--attempts", type=int, help="Override Gemini attempts")
    parser.add_argument(
        "--schema-only", action="store_true", help="Select schema without Gemini"
    )
    args = parser.parse_args()

    generator = None
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if args.timeout_ms is not None:
            config["generation"]["timeout_ms"] = args.timeout_ms
        if args.attempts is not None:
            config["generation"]["attempts"] = args.attempts
        _validate_config(config)
        database_path = args.database or Path(config["database_path"])
        catalog = SchemaCatalog.from_sqlite(database_path)

        if args.schema_only:
            schema = catalog.select(args.question, max_tables=config["max_tables"])
            print(
                json.dumps(
                    {
                        "question": args.question,
                        "schema_tables": list(schema.table_names),
                        "schema": schema.to_prompt(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        database = ReadOnlyDatabase(
            database_path,
            max_rows=config["max_rows"],
            timeout=config["timeout_seconds"],
        )
        generator = GeminiSQLGenerator(Path.cwd(), config["generation"])
        retriever = SQLRetriever(
            database,
            catalog,
            generator,
            max_tables=config["max_tables"],
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        output = retriever.retrieve(args.question)
        print(json.dumps(output.to_dict(), ensure_ascii=False, indent=2))
        return 0
    except (
        KeyError,
        TypeError,
        ValueError,
        OSError,
        SQLExecutionError,
        json.JSONDecodeError,
    ) as error:
        print(f"SQL Retriever failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 -- report safe API details at CLI edge.
        print(
            f"SQL Retriever failed: {_unexpected_error_message(error)}",
            file=sys.stderr,
        )
        return 1
    finally:
        if generator is not None:
            generator.close()


def _validate_config(config: dict) -> None:
    for name in ["max_tables", "max_rows"]:
        if type(config.get(name)) is not int or config[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    timeout = config.get("timeout_seconds")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        raise ValueError("timeout_seconds must be positive")
    if not isinstance(config.get("database_path"), str):
        raise TypeError("database_path must be a string")
    generation = config.get("generation", {})
    for name in [
        "timeout_ms",
        "attempts",
        "planning_max_output_tokens",
        "max_output_tokens",
    ]:
        if type(generation.get(name)) is not int or generation[name] < 1:
            raise ValueError(f"generation.{name} must be a positive integer")
    for name in ["model", "api_key_env"]:
        if not isinstance(generation.get(name), str) or not generation[name].strip():
            raise ValueError(f"generation.{name} cannot be empty")
    temperature = generation.get("temperature")
    if (
        not isinstance(temperature, (int, float))
        or isinstance(temperature, bool)
        or not 0 <= temperature <= 2
    ):
        raise ValueError("generation.temperature must be between 0 and 2")


def _unexpected_error_message(error: Exception) -> str:
    error_type = type(error).__name__
    code = getattr(error, "code", None)
    message = getattr(error, "message", None)
    if code is not None and message:
        return f"{error_type} ({code}): {str(message)[:800]}"
    return f"{error_type}; check the network, model access, and API quota."
