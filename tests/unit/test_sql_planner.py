import pytest

from warhammer_agent.sql import (
    ColumnSchema,
    QueryPlanError,
    Relationship,
    SchemaContext,
    TableSchema,
    parse_query_plan,
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


def valid_payload():
    return {
        "metric": "matching unit list",
        "dimensions": [
            "datasheets.name",
            "datasheets_models.name",
            "datasheets_models.t",
        ],
        "filters": [
            {"column": "datasheets.factionId", "operator": "=", "value": "SM"},
            {"column": "datasheets_models.t", "operator": "=", "value": 6},
        ],
        "candidate_tables": ["datasheets", "datasheets_models"],
        "joins": ["datasheets.Id = datasheets_models.DatasheetId"],
        "aggregation_grain": "one row per unit model",
        "time_range": None,
        "assumptions": ["SM is the approved Space Marines faction identifier"],
        "ambiguities": [],
    }


def test_valid_plan_is_parsed_and_serializable(schema):
    plan = parse_query_plan(valid_payload(), schema)

    assert plan.candidate_tables == ("datasheets", "datasheets_models")
    assert plan.filters[1].value == 6
    assert plan.joins[0].render() == ("datasheets.Id = datasheets_models.DatasheetId")
    assert plan.to_dict() == valid_payload()


def test_reversed_equivalent_join_is_normalized(schema):
    payload = valid_payload()
    payload["joins"] = ["datasheets_models.DatasheetId = datasheets.Id"]

    plan = parse_query_plan(payload, schema)

    assert plan.joins == schema.relationships
    assert plan.to_dict()["joins"] == ["datasheets.Id = datasheets_models.DatasheetId"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("candidate_tables", ["missing"], "unknown candidate tables"),
        ("dimensions", ["datasheets.missing"], "unknown column"),
        ("dimensions", ["name"], "table.column"),
        ("joins", ["datasheets.Id = missing.Id"], "unknown joins"),
    ],
)
def test_unknown_schema_references_are_rejected(schema, field, value, message):
    payload = valid_payload()
    payload[field] = value
    with pytest.raises(QueryPlanError, match=message):
        parse_query_plan(payload, schema)


def test_unsupported_and_malformed_filters_are_rejected(schema):
    payload = valid_payload()
    payload["filters"] = [
        {"column": "datasheets.name", "operator": "DELETE", "value": "x"}
    ]
    with pytest.raises(QueryPlanError, match="unsupported filter operator"):
        parse_query_plan(payload, schema)

    payload["filters"] = [{"column": "datasheets.name", "operator": "IN", "value": []}]
    with pytest.raises(QueryPlanError, match="non-empty value list"):
        parse_query_plan(payload, schema)

    payload["filters"] = [
        {"column": "datasheets.name", "operator": "=", "value": ["x"]}
    ]
    with pytest.raises(QueryPlanError, match="must be scalars"):
        parse_query_plan(payload, schema)


def test_multiple_tables_must_be_connected(schema):
    payload = valid_payload()
    payload["joins"] = []
    with pytest.raises(QueryPlanError, match="not connected"):
        parse_query_plan(payload, schema)


def test_ambiguity_can_defer_schema_selection(schema):
    plan = parse_query_plan(
        {
            "metric": "unknown",
            "dimensions": [],
            "filters": [],
            "candidate_tables": [],
            "joins": [],
            "ambiguities": ["Which faction should be used?"],
        },
        schema,
    )
    assert plan.candidate_tables == ()
    assert plan.ambiguities == ("Which faction should be used?",)


def test_empty_executable_plan_is_rejected(schema):
    payload = valid_payload()
    payload["candidate_tables"] = []
    payload["dimensions"] = []
    payload["filters"] = []
    payload["joins"] = []
    with pytest.raises(QueryPlanError, match="cannot be empty"):
        parse_query_plan(payload, schema)
