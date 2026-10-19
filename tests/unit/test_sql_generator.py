import json

import pytest
from google.genai import types

from warhammer_agent.sql import (
    ColumnSchema,
    GeminiSQLGenerator,
    QueryPlan,
    Relationship,
    SchemaContext,
    SQLGenerationError,
    TableSchema,
    parse_query_plan,
    validate_generated_query,
)


@pytest.fixture
def schema():
    return SchemaContext(
        tables=(
            TableSchema(
                "datasheets",
                (
                    ColumnSchema("Id", "TEXT"),
                    ColumnSchema("name", "TEXT"),
                    ColumnSchema("factionId", "TEXT"),
                ),
            ),
            TableSchema(
                "datasheets_models",
                (
                    ColumnSchema("DatasheetId", "TEXT"),
                    ColumnSchema("name", "TEXT"),
                    ColumnSchema("t", "TEXT"),
                ),
            ),
        ),
        relationships=(
            Relationship("datasheets", "Id", "datasheets_models", "DatasheetId"),
        ),
    )


@pytest.fixture
def plan(schema):
    return parse_query_plan(
        {
            "metric": "matching unit list",
            "dimensions": ["datasheets.name", "datasheets_models.t"],
            "filters": [
                {
                    "column": "datasheets.factionId",
                    "operator": "=",
                    "value": "SM",
                },
                {"column": "datasheets_models.t", "operator": "=", "value": 6},
            ],
            "candidate_tables": ["datasheets", "datasheets_models"],
            "joins": ["datasheets.Id = datasheets_models.DatasheetId"],
            "ambiguities": [],
        },
        schema,
    )


def sql_payload():
    return {
        "sql": (
            "SELECT d.name AS unit, CAST(m.t AS INTEGER) AS toughness "
            "FROM datasheets AS d "
            "JOIN datasheets_models AS m ON d.Id = m.DatasheetId "
            "WHERE d.factionId = ? AND CAST(m.t AS INTEGER) = ?"
        ),
        "parameters": ["SM", 6],
    }


def test_valid_generated_query_matches_plan(schema, plan):
    generated = validate_generated_query(sql_payload(), plan, schema)

    assert generated.parameters == ("SM", 6)
    assert generated.query.tables == ("datasheets", "datasheets_models")


def test_equivalent_numeric_parameter_types_use_the_plan_value(schema, plan):
    payload = sql_payload()
    payload["parameters"] = ["SM", "6"]

    generated = validate_generated_query(payload, plan, schema)

    assert generated.parameters == ("SM", 6)


@pytest.mark.parametrize(
    ("sql", "parameters", "message"),
    [
        (
            (
                "SELECT d.missing FROM datasheets AS d "
                "JOIN datasheets_models AS m ON d.Id = m.DatasheetId "
                "WHERE d.factionId = ? AND m.t = ?"
            ),
            ["SM", 6],
            "unknown column",
        ),
        (
            (
                "SELECT d.name FROM datasheets AS d "
                "JOIN datasheets_models AS m ON d.Id = m.DatasheetId "
                "WHERE d.factionId = :faction AND m.t = :toughness"
            ),
            ["SM", 6],
            "anonymous",
        ),
        (
            (
                "SELECT d.name FROM datasheets AS d "
                "JOIN datasheets_models AS m ON d.Id = m.DatasheetId "
                "WHERE d.factionId = 'SM' AND m.t = '6'"
            ),
            [],
            "query plan",
        ),
    ],
)
def test_columns_and_parameters_are_locally_validated(
    schema, plan, sql, parameters, message
):
    with pytest.raises(SQLGenerationError, match=message):
        validate_generated_query({"sql": sql, "parameters": parameters}, plan, schema)


def test_missing_or_unknown_tables_are_rejected(schema, plan):
    with pytest.raises(SQLGenerationError, match="all candidate tables"):
        validate_generated_query(
            {
                "sql": "SELECT d.name FROM datasheets AS d WHERE d.factionId = ?",
                "parameters": ["SM", 6],
            },
            plan,
            schema,
        )


def test_duplicate_output_names_are_rejected(schema, plan):
    payload = sql_payload()
    payload["sql"] = (
        "SELECT d.name, m.name FROM datasheets AS d "
        "JOIN datasheets_models AS m ON d.Id = m.DatasheetId "
        "WHERE d.factionId = ? AND CAST(m.t AS INTEGER) = ?"
    )
    with pytest.raises(SQLGenerationError, match="unique aliases"):
        validate_generated_query(payload, plan, schema)
    with pytest.raises(SQLGenerationError, match="read-only validation"):
        validate_generated_query(
            {"sql": "SELECT x.name FROM unknown AS x", "parameters": ["SM", 6]},
            plan,
            schema,
        )


def test_generator_rejects_ambiguous_plan_before_api_call(schema):
    ambiguous = QueryPlan(
        metric="unknown",
        dimensions=(),
        filters=(),
        candidate_tables=(),
        joins=(),
        ambiguities=("Which faction?",),
    )
    generator = object.__new__(GeminiSQLGenerator)
    with pytest.raises(SQLGenerationError, match="unresolved ambiguities"):
        generator.generate("Which units?", ambiguous, schema)


def test_gemini_structured_query_plan(monkeypatch, tmp_path, schema):
    from google import genai

    calls = []
    payload = {
        "metric": "matching unit list",
        "dimensions": ["datasheets.name", "datasheets_models.t"],
        "filters": [{"column": "datasheets_models.t", "operator": "=", "value": 6}],
        "candidate_tables": ["datasheets", "datasheets_models"],
        "joins": ["datasheets.Id = datasheets_models.DatasheetId"],
        "aggregation_grain": "one row per model",
        "time_range": None,
        "assumptions": [],
        "ambiguities": [],
    }
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason="STOP",
                content=types.Content(parts=[types.Part(text=json.dumps(payload))]),
            )
        ]
    )

    class Client:
        def __init__(self, **kwargs):
            self.models = self

        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return response

        def close(self):
            pass

    settings = {
        "model": "test-model",
        "api_key_env": "GEMINI_API_KEY",
        "timeout_ms": 1000,
        "attempts": 1,
        "planning_max_output_tokens": 1000,
        "max_output_tokens": 1000,
        "temperature": 0.2,
    }
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(genai, "Client", Client)
    generator = GeminiSQLGenerator(tmp_path, settings)

    plan = generator.plan("Which unit models have toughness 6?", schema)

    assert plan.candidate_tables == ("datasheets", "datasheets_models")
    assert plan.filters[0].value == 6
    assert calls[0]["config"].response_mime_type == "application/json"
    assert calls[0]["config"].response_schema["title"] == "PlanResponse"


def test_gemini_structured_request_uses_local_validation(
    monkeypatch, tmp_path, schema, plan
):
    from google import genai

    calls = []
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason="STOP",
                content=types.Content(
                    parts=[types.Part(text=json.dumps(sql_payload()))]
                ),
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=30
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

    settings = {
        "model": "test-model",
        "api_key_env": "GEMINI_API_KEY",
        "timeout_ms": 1000,
        "attempts": 1,
        "max_output_tokens": 1000,
        "temperature": 0.2,
    }
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(genai, "Client", Client)
    generator = GeminiSQLGenerator(tmp_path, settings)
    generated = generator.generate("Question?", plan, schema)

    assert generated.model_version == "test-version"
    assert generated.usage["prompt_token_count"] == 100
    assert calls[0]["model"] == "test-model"
    prompt = json.loads(calls[0]["contents"])
    assert prompt["query_plan"] == plan.to_dict()
    assert len(prompt["few_shot_examples"]) == 3
    assert {example["parameters"][0] for example in prompt["few_shot_examples"]} == {
        "5",
        "Orks",
        "2",
    }
    assert calls[0]["config"].response_mime_type == "application/json"
    generator.close()
    assert generator.client.closed
