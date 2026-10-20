import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import types

from warhammer_agent.rag.cli import validate_config
from warhammer_agent.rag.generation import GeminiGenerator, make_prompt, validate_answer
from warhammer_agent.rag.pipeline import answer_question, select_evidence


def rule(identity, text="Rule text.", parent_id=None):
    block = {
        "block_id": identity,
        "section_title": identity.upper(),
        "text": text,
        "source": "Core Rules.pdf",
        "source_path": "data/Core Rules.pdf",
        "page_numbers": [21, 22],
        "review_status": "partially_reviewed",
        "source_segments": [{"page_number": 21}],
    }
    if parent_id:
        block["parent_rule_id"] = parent_id
    return block


def hit(identity):
    return {"block_id": identity, "score": 0.8}


def settings():
    return json.loads(Path("config/rag.json").read_text())


def evidence():
    return select_evidence([hit("rule")], [rule("rule")], 10000)[0]


def test_example_main_rule_bundle_and_deduplication():
    parents = [rule("example", parent_id="main"), rule("main")]
    selected, omitted = select_evidence([hit("example"), hit("main")], parents, 10000)
    assert [s["block_id"] for s in selected] == ["example", "main"]
    assert selected[1]["relationship"] == "example_main_rule"
    assert selected[1]["citation_id"] == "S2"
    assert omitted == []
    one, _ = select_evidence([hit("main")], parents, 10000)
    budget = len(make_prompt("", one).encode())
    selected, omitted = select_evidence([hit("example")], parents, budget)
    assert selected == []  # Never retain an example while dropping its main rule.
    assert omitted == ["example"]


def test_budget_skips_whole_rule_and_preserves_small_rule():
    parents = [rule("large", "€" * 1000), rule("small")]
    selected, omitted = select_evidence([hit("large"), hit("small")], parents, 400)
    assert [s["block_id"] for s in selected] == ["small"]
    assert selected[0]["text"] == "Rule text."
    assert selected[0]["citation_id"] == "S1"
    assert omitted == ["large"]
    assert len(make_prompt("", selected).encode()) <= 400


@pytest.mark.parametrize(
    "payload",
    [
        {"answer": "Rule [S2]", "citations": ["S2"], "insufficient_evidence": False},
        {"answer": "Rule [S1]", "citations": [], "insufficient_evidence": False},
        {
            "answer": "Rule [S1]",
            "citations": ["S1", "S1"],
            "insufficient_evidence": False,
        },
        {"answer": "No citations", "citations": [], "insufficient_evidence": False},
        {"answer": "  ", "citations": [], "insufficient_evidence": True},
        {
            "answer": "Rule [S1]",
            "citations": ["S1"],
            "insufficient_evidence": False,
            "page_numbers": [999],
        },
    ],
)
def test_invalid_answers_rejected(payload):
    with pytest.raises(ValueError):
        validate_answer(payload, evidence())


def test_citations_are_resolved_from_metadata():
    result = validate_answer(
        {
            "answer": "Conclusion [S1]",
            "citations": ["S1"],
            "insufficient_evidence": False,
        },
        evidence(),
    )
    assert result["citations"][0]["page_numbers"] == [21, 22]
    assert result["citations"][0]["page_number_basis"] == "physical_pdf_1_based"
    result = validate_answer(
        {
            "answer": "The supplied evidence cannot answer this question.",
            "citations": [],
            "insufficient_evidence": True,
        },
        evidence(),
    )
    assert result["insufficient_evidence"]


class Retriever:
    def __init__(self):
        self.parents = [rule("rule")]
        self.store = SimpleNamespace(name="test_collection")
        self.model = "Qwen/Qwen3-Embedding-0.6B"

    def retrieve(self, question, top_k):
        return [hit("rule")]


class Generator:
    def generate(self, question, selected):
        return validate_answer(
            {
                "answer": "Conclusion [S1]",
                "citations": ["S1"],
                "insufficient_evidence": False,
            },
            selected,
        )


def test_pipeline_closes_retrieval_generation_and_source_mapping():
    result = answer_question("Question?", Retriever(), Generator(), settings())
    assert result["status"] == "answered"
    assert result["collection"] == "test_collection"
    assert result["citations"][0]["block_id"] == "rule"
    assert result["evidence"][0]["source_segments"] == [{"page_number": 21}]


def test_retrieval_only_and_empty_evidence_never_call_generator():
    assert (
        answer_question("Question?", Retriever(), None, settings(), True)["status"]
        == "retrieved"
    )
    cfg = {**settings(), "max_context_bytes": 1}
    result = answer_question("Question?", Retriever(), None, cfg)
    assert result["insufficient_evidence"]
    assert result["citations"] == []


def test_generation_failure_retains_retrieval_diagnostics():
    class Broken:
        def generate(self, *args):
            raise ValueError("Bad response")

    with pytest.raises(ValueError) as caught:
        answer_question("Question?", Retriever(), Broken(), settings())
    assert caught.value.rag_record["status"] == "generation_failed"
    assert caught.value.rag_record["evidence"][0]["citation_id"] == "S1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("top_k", 0),
        ("max_context_bytes", -1),
        ("cpu_threads", True),
        ("qwen_local_files_only", "true"),
    ],
)
def test_invalid_configuration_rejected(field, value):
    cfg = settings()
    cfg[field] = value
    with pytest.raises(ValueError):
        validate_config(cfg)


def test_actual_sdk_schema_and_request_with_mock_transport(monkeypatch, tmp_path):
    from google import genai

    calls = []
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason="STOP",
                content=types.Content(
                    parts=[
                        types.Part(
                            text=json.dumps(
                                {
                                    "answer": "Conclusion [S1]",
                                    "citations": ["S1"],
                                    "insufficient_evidence": False,
                                }
                            )
                        )
                    ]
                ),
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=20
        ),
        model_version="test-version",
    )

    class Client:
        def __init__(self, **kwargs):
            self.models = self
            self.closed = False

        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return response

        def close(self):
            self.closed = True

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(genai, "Client", Client)
    generator = GeminiGenerator(tmp_path, settings()["generation"])
    result = generator.generate("Question?", evidence())
    assert result["usage"]["prompt_token_count"] == 100
    assert calls[0]["model"] == settings()["generation"]["model"]
    assert json.loads(calls[0]["contents"])["question"] == "Question?"
    assert calls[0]["config"].response_mime_type == "application/json"
    response.candidates[0].finish_reason = types.FinishReason.MAX_TOKENS
    with pytest.raises(ValueError, match="did not finish normally"):
        generator.generate("Question?", evidence())
    generator.close()
    assert generator.client.closed


def test_cli_api_error_redacts_credentials_and_saves_failure(
    monkeypatch, tmp_path, capsys
):
    from warhammer_agent.rag import cli

    cfg = settings()
    cfg["output_dir"] = str(tmp_path / "runs")
    path = tmp_path / "rag.json"
    path.write_text(json.dumps(cfg))
    secret = "sensitive-test-credential"
    monkeypatch.setenv("GEMINI_API_KEY", secret)

    class APIError(Exception):
        code = 403
        message = "Access denied for " + secret

    def broken(*args):
        raise APIError()

    monkeypatch.setattr(cli, "GeminiGenerator", broken)
    monkeypatch.setattr(
        "sys.argv", ["ask_rules.py", "--config", str(path), "--question", "Question?"]
    )
    assert cli.main() == 1
    output = capsys.readouterr()
    report = next((tmp_path / "runs").glob("*.json")).read_text()
    assert secret not in output.err + report
    assert "[REDACTED]" in output.err
    assert json.loads(report)["api_error"]["code"] == 403


def test_grouped_inline_citations_normalize_to_single_source_brackets():
    selected = evidence()
    selected.append({**selected[0], "citation_id": "S2", "block_id": "second"})
    result = validate_answer(
        {
            "answer": "Conclusion [S1, S2]",
            "citations": ["S1", "S2"],
            "insufficient_evidence": False,
        },
        selected,
    )
    assert result["answer"] == "Conclusion [S1] [S2]"
    assert len(result["citations"]) == 2


def test_grouped_citations_still_reject_unknown_sources():
    with pytest.raises(ValueError):
        validate_answer(
            {
                "answer": "Conclusion [S1, S99]",
                "citations": ["S1", "S99"],
                "insufficient_evidence": False,
            },
            evidence(),
        )
