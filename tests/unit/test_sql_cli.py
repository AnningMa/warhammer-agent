import json
import sqlite3

from warhammer_agent.sql import cli


def test_schema_only_cli_does_not_require_gemini(monkeypatch, tmp_path, capsys):
    database = tmp_path / "rules.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE datasheets (Id TEXT, name TEXT)")
    connection.close()

    config = {
        "database_path": str(database),
        "max_tables": 5,
        "max_rows": 100,
        "timeout_seconds": 2,
        "generation": {
            "model": "test-model",
            "api_key_env": "GEMINI_API_KEY",
            "timeout_ms": 1000,
            "attempts": 1,
            "planning_max_output_tokens": 1000,
            "max_output_tokens": 1000,
            "temperature": 0.2,
        },
    }
    config_path = tmp_path / "sql.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "ask_database.py",
            "--config",
            str(config_path),
            "--question",
            "Which unit datasheets exist?",
            "--schema-only",
        ],
    )

    assert cli.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["schema_tables"] == ["datasheets"]


def test_unexpected_api_error_includes_status_and_message():
    class ClientError(Exception):
        code = 429
        message = "Quota exceeded"

    assert cli._unexpected_error_message(ClientError()) == (
        "ClientError (429): Quota exceeded"
    )
