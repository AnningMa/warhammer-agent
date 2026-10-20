import copy
import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from warhammer_agent.agent.evidence import encoded_size, pack_evidence
from warhammer_agent.agent.graph import bounded_history, build_graph


def config():
    return json.loads(Path("config/agent.json").read_text())


def pdf_record():
    return {
        "block_id": "pdf-rule",
        "source": "Core Rules.pdf",
        "source_path": "data/Core Rules.pdf",
        "section_title": "UNIT COHERENCY",
        "page_numbers": [6],
        "review_status": "reviewed_correction",
        "text": "A complete rule with its conditions and exceptions.",
        "source_segments": [],
        "retrieved_by": "pdf-rule",
    }


def sql_record(rows=None, truncated=False):
    return {
        "status": "executed",
        "database_path": "data/wahadb.sqlite",
        "schema_tables": ["datasheets_models"],
        "sql": "SELECT name FROM datasheets_models WHERE t = ?",
        "parameters": [6],
        "columns": ["name"],
        "rows": [{"name": "Model A"}] if rows is None else rows,
        "truncated": truncated,
    }


class FakeModel:
    def __init__(self, services):
        self.services = services
        self.calls = 0
        self.settings = {"api_key_env": "GEMINI_API_KEY"}

    def route(self, question, plan, history, max_tokens):
        self.services.route_history = history
        if self.services.fail_route:
            raise ValueError("Routing failed")
        intent = self.services.intent
        return {
            "intent": intent,
            "pdf_question": plan["standalone_question"] if intent != "database" else "",
            "sql_question": plan["standalone_question"] if intent != "rules" else "",
            "clarification": self.services.clarification,
        }, {"usage": {"total_token_count": 10}}

    def synthesize(self, question, plan, evidence, limitations):
        self.calls += 1
        self.services.synthesis_evidence = evidence
        self.services.limitations = limitations
        ids = (
            ["S999"]
            if self.services.bad_citations
            else [e["citation_id"] for e in evidence]
        )
        return {
            "answer": "Supported conclusions " + " ".join("[" + s + "]" for s in ids),
            "citations": ids,
            "insufficient_evidence": False,
            "usage": {"total_token_count": 20},
        }


class FakeServices:
    def __init__(self, intent="rules"):
        self.intent = intent
        self.rag = json.loads(Path("config/rag.json").read_text())
        self.rag["rewrite"]["enabled"] = False
        self.sql = {"database_path": "data/wahadb.sqlite"}
        self.model = FakeModel(self)
        self._model = self.model
        self.fail_pdf = self.fail_sql = self.fail_route = self.bad_citations = False
        self.clarification = ""
        self.pdf_calls = self.sql_calls = 0
        self.sql_output = sql_record()

    def retrieve_pdf(self, original, plan, history, rewrite):
        self.pdf_calls += 1
        self.pdf_plan = plan
        if self.fail_pdf:
            raise ValueError("PDF failed")
        return {"evidence": [pdf_record()], "rerank": {"usage": None}}

    def retrieve_sql(self, question):
        self.sql_calls += 1
        if self.fail_sql:
            raise ValueError("SQL failed")
        return self.sql_output


def invoke(services, question="Question?"):
    graph = build_graph(services, config(), InMemorySaver())
    return graph.invoke({"question": question}, {"configurable": {"thread_id": "unit"}})


@pytest.mark.parametrize(
    "intent,pdf_calls,sql_calls",
    [("rules", 1, 0), ("database", 0, 1), ("hybrid", 1, 1)],
)
def test_routes_use_only_selected_tools_and_synthesize_once(
    intent, pdf_calls, sql_calls
):
    services = FakeServices(intent)
    result = invoke(services)
    assert result["status"] == "answered"
    assert services.pdf_calls == pdf_calls and services.sql_calls == sql_calls
    assert services.model.calls == 1
    kinds = {c["kind"] for c in result["citations"]}
    assert kinds == (
        {"pdf"}
        if intent == "rules"
        else {"sql"}
        if intent == "database"
        else {"pdf", "sql"}
    )
    for citation in result["citations"]:
        if citation["kind"] == "sql":
            assert "page_numbers" not in citation
            assert citation["parameters"] == [6]


def test_router_clarification_skips_tools_and_generation():
    services = FakeServices()
    services.clarification = "Which unit do you mean?"
    result = invoke(services)
    assert result["status"] == "clarification"
    assert services.pdf_calls == services.sql_calls == services.model.calls == 0


@pytest.mark.parametrize("failed", ["pdf", "sql"])
def test_hybrid_returns_only_supported_part_when_one_tool_fails(failed):
    services = FakeServices("hybrid")
    setattr(services, "fail_" + failed, True)
    result = invoke(services)
    assert result["status"] == "partial_answer"
    assert result["insufficient_evidence"]
    assert failed.upper() in result["answer"]
    assert all(c["kind"] != failed for c in result["citations"])


def test_double_failure_and_routing_failure_do_not_generate():
    services = FakeServices("hybrid")
    services.fail_pdf = services.fail_sql = True
    result = invoke(services)
    assert result["status"] == "failed"
    assert services.model.calls == 0
    assert len(result["errors"]) == 2
    services = FakeServices()
    services.fail_route = True
    result = invoke(services)
    assert result["status"] == "failed"
    assert services.pdf_calls == services.sql_calls == services.model.calls == 0


def test_sql_clarification_and_empty_results_are_distinct():
    services = FakeServices("database")
    services.sql_output = {"status": "clarification", "clarification": "Which faction?"}
    result = invoke(services)
    assert result["status"] == "clarification"
    assert result["answer"] == "Which faction?"
    assert services.model.calls == 0
    services.sql_output = sql_record(rows=[])
    result = invoke(services)
    assert result["status"] == "answered"
    assert result["citations"][0]["returned_rows"] == 0
    assert result["citations"][0]["truncated"] is False


def test_hybrid_sql_clarification_can_return_supported_pdf_part():
    services = FakeServices("hybrid")
    services.sql_output = {"status": "clarification", "clarification": "Which faction?"}
    result = invoke(services)
    assert result["status"] == "partial_answer"
    assert "Which faction?" in result["answer"]
    assert services.synthesis_evidence[0]["kind"] == "pdf"


def test_unknown_citations_are_not_published():
    services = FakeServices()
    services.bad_citations = True
    result = invoke(services)
    assert result["status"] == "failed"
    assert result["citations"] == []
    assert "S999" not in result["answer"]
    assert result["errors"][0]["stage"] == "synthesize"


def test_sql_context_omissions_keep_whole_rows_and_are_not_empty_matches():
    rows = [{"name": str(i), "description": "x" * 200} for i in range(20)]
    cfg = {**config(), "sql_context_bytes": 1100}
    evidence, omitted = pack_evidence([], sql_record(rows=rows), cfg)
    item = evidence[0]
    assert 0 < item["included_rows"] < len(rows)
    assert item["rows"] == rows[: item["included_rows"]]
    assert item["omitted_rows"] == len(rows) - item["included_rows"]
    assert item["truncated"]
    assert encoded_size(evidence) <= cfg["sql_context_bytes"]
    assert not omitted
    # A single large row is omitted intact, not truncated or counted as no matches.
    evidence, _ = pack_evidence([], sql_record(rows=[{"name": "x" * 2000}]), cfg)
    assert evidence[0]["rows"] == []
    assert evidence[0]["returned_rows"] == 1
    assert evidence[0]["omitted_rows"] == 1


def test_pdf_example_bundle_never_partially_fits():
    example = pdf_record()
    main = {**pdf_record(), "block_id": "main", "text": "x" * 2000}
    cfg = {**config(), "max_context_bytes": 1000}
    evidence, omitted = pack_evidence([example, main], None, cfg)
    assert evidence == []
    assert omitted == ["pdf-rule"]


def test_truncated_sql_results_always_show_incomplete_notice():
    services = FakeServices("database")
    services.sql_output = sql_record(truncated=True)
    result = invoke(services)
    assert "Database results are incomplete" in result["answer"]
    assert result["citations"][0]["tool_truncated"]


def test_history_budget_drops_oldest_whole_messages():
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
    ]
    assert (
        bounded_history(messages, {"max_history_messages": 6, "max_history_chars": 6})
        == messages[1:]
    )


def test_supplied_pdf_plan_never_calls_rewriting_again(monkeypatch):
    from warhammer_agent.rag import pipeline

    def fail(*args):
        raise AssertionError("Repeated rewriting")

    monkeypatch.setattr(pipeline, "prepare_question", fail)

    class Retriever:
        def __init__(self):
            self.parents = [pdf_record()]
            self.store = type("Store", (), {"name": "test"})()
            self.model = "Qwen"

        def retrieve(self, q, k):
            return [{"block_id": "pdf-rule", "score": 1}]

    cfg = copy.deepcopy(FakeServices().rag)
    cfg["rerank"]["enabled"] = False
    plan = {
        "standalone_question": "Resolved?",
        "subquestions": [],
        "queries": ["Original?", "Resolved?"],
    }
    result = pipeline.retrieve_evidence(
        "Original?", Retriever(), None, cfg, query_plan=plan
    )
    assert result["query_plan"] == plan
    assert result["evidence"]


def test_question_planning_happens_once_before_routing(monkeypatch):
    from warhammer_agent.agent import graph as module

    calls = []

    def prepare(question, model, settings, history):
        calls.append(question)
        return (
            {
                "standalone_question": "How does Deep Strike work?",
                "subquestions": [],
                "queries": [question, "How does Deep Strike work?"],
            },
            history,
            {"status": "rewritten"},
        )

    monkeypatch.setattr(module, "prepare_question", prepare)
    services = FakeServices()
    result = invoke(services, "What about that rule?")
    assert calls == ["What about that rule?"]
    assert result["query_plan"]["standalone_question"] == "How does Deep Strike work?"
    assert "What about that rule?" in services.pdf_plan["queries"]
    assert "How does Deep Strike work?" in services.pdf_plan["queries"]


def test_cli_stdout_is_json_and_progress_is_stderr(monkeypatch, tmp_path, capsys):
    from warhammer_agent.agent import cli

    cfg = {
        **config(),
        "checkpoints": str(tmp_path / "session.sqlite"),
        "output_dir": str(tmp_path / "runs"),
    }
    path = tmp_path / "agent.json"
    path.write_text(json.dumps(cfg))
    services = FakeServices("database")
    services.sql = json.loads(Path("config/sql.json").read_text())
    services.close = lambda: None
    monkeypatch.setattr(cli, "AgentServices", lambda *args: services)
    monkeypatch.setattr(
        "sys.argv",
        [
            "ask_agent.py",
            "--question",
            "Count models?",
            "--config",
            str(path),
            "--json",
        ],
    )
    assert cli.main() == 0
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record["session_id"]
    assert record["status"] == "answered"
    assert Path(record["report_path"]).exists()
    assert "Completed stage: sql" in output.err
    assert "Completed stage: pdf" not in output.err


def test_invalid_route_never_selects_any_tool():
    services = FakeServices("invalid")
    result = invoke(services)
    assert result["status"] == "failed"
    assert services.pdf_calls == services.sql_calls == 0
