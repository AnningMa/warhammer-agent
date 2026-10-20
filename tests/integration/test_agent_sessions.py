import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from warhammer_agent.agent.services import AgentServices
from warhammer_agent.agent.session import run_turn, session_graph
from warhammer_agent.sql.generator import validate_generated_query
from warhammer_agent.sql.planner import QueryFilter, QueryPlan

# Shared deterministic model/tool doubles; no API traffic in these tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from test_agent import FakeServices, config


def test_sessions_persist_across_actual_process_restart_and_isolate_evidence(tmp_path):
    first = run_turn(
        tmp_path, config(), FakeServices("rules"), "First rules question?", "saved"
    )
    assert first["citations"][0]["kind"] == "pdf"
    script = """
import json,sys
from pathlib import Path
from test_agent import FakeServices,config
from warhammer_agent.agent.session import run_turn
result=run_turn(Path(sys.argv[1]),config(),FakeServices('database'),'Next data question?','saved')
print(json.dumps(result))
"""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(Path("src").resolve()), str(Path("tests/unit").resolve())]
        ),
    }
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    second = json.loads(completed.stdout)
    assert second["history"][0]["content"] == "First rules question?"
    assert len(second["messages"]) == 4
    assert second["pdf"] == {}
    assert {c["kind"] for c in second["citations"]} == {"sql"}
    assert second["errors"] == []
    other = run_turn(
        tmp_path, config(), FakeServices(), "Independent question?", "other"
    )
    assert other["history"] == []


def test_concurrent_same_session_is_rejected_and_business_db_is_protected(tmp_path):
    services = FakeServices()
    with (
        session_graph(tmp_path, config(), services, "locked"),
        pytest.raises(RuntimeError, match="already running"),
    ):
        run_turn(tmp_path, config(), services, "Question?", "locked")
    bad = {**config(), "checkpoints": "data/wahadb.sqlite"}
    with pytest.raises(ValueError, match="business database"):
        run_turn(tmp_path, bad, services, "Question?", "safe")
    with pytest.raises(ValueError, match="session-id"):
        run_turn(tmp_path, config(), services, "Question?", "../unsafe")


def test_database_route_uses_real_readonly_sql_without_loading_qwen(
    tmp_path, monkeypatch
):
    from test_agent import FakeModel

    from warhammer_agent.agent import services as module

    path = tmp_path / "units.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE datasheets_models (name TEXT, t TEXT)")
        db.execute("INSERT INTO datasheets_models VALUES ('Model A', '6')")

    class SQLModel:
        def __init__(self, *args):
            pass

        def plan(self, question, schema):
            return QueryPlan(
                metric="models",
                dimensions=("datasheets_models.name",),
                filters=(QueryFilter("datasheets_models.t", "=", "6"),),
                candidate_tables=("datasheets_models",),
                joins=(),
            )

        def generate(self, question, plan, schema):
            return validate_generated_query(
                {
                    "sql": "SELECT m.name AS name FROM datasheets_models AS m WHERE m.t = ?",
                    "parameters": ["6"],
                },
                plan,
                schema,
            )

        def close(self):
            pass

    def forbidden(*args):
        raise AssertionError("Database route must not initialize Qwen")

    monkeypatch.setattr(module, "RuleRetriever", forbidden)
    monkeypatch.setattr(module, "GeminiSQLGenerator", SQLModel)
    actual = AgentServices(Path.cwd(), config())
    actual.rag["rewrite"]["enabled"] = False
    actual.sql["database_path"] = str(path)
    actual.intent = "database"
    actual.fail_route = actual.bad_citations = False
    actual.clarification = ""
    actual._model = FakeModel(actual)
    try:
        result = run_turn(
            tmp_path, config(), actual, "Which models have toughness 6?", "sql"
        )
        assert result["status"] == "answered"
        assert result["sql"]["rows"] == [{"name": "Model A"}]
        assert actual._pdf is None
        with sqlite3.connect(path) as db:
            assert (
                db.execute("SELECT COUNT(*) FROM datasheets_models").fetchone()[0] == 1
            )
    finally:
        # Test model has no external resources to close.
        actual._model = None
        actual.close()
