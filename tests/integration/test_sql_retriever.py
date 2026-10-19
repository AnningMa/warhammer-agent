import sqlite3

from warhammer_agent.sql import (
    QueryPlan,
    ReadOnlyDatabase,
    SchemaCatalog,
    SQLRetriever,
    parse_query_plan,
    validate_generated_query,
)


def database_path(tmp_path):
    path = tmp_path / "rules.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE datasheets (Id TEXT, name TEXT);
        CREATE TABLE datasheets_models (DatasheetId TEXT, name TEXT, t TEXT);
        INSERT INTO datasheets VALUES ('1', 'Intercessors'), ('2', 'Terminators');
        INSERT INTO datasheets_models VALUES
            ('1', 'Intercessor', '4'),
            ('2', 'Terminator', '5');
        """
    )
    connection.close()
    return path


class FakeModel:
    def __init__(self, *, ambiguous=False):
        self.ambiguous = ambiguous
        self.generated = False

    def plan(self, question, schema):
        if self.ambiguous:
            return QueryPlan(
                metric="unit list",
                dimensions=(),
                filters=(),
                candidate_tables=(),
                joins=(),
                ambiguities=("Which toughness value should be used?",),
            )
        return parse_query_plan(
            {
                "metric": "matching unit list",
                "dimensions": ["datasheets.name", "datasheets_models.t"],
                "filters": [
                    {"column": "datasheets_models.t", "operator": "=", "value": 5}
                ],
                "candidate_tables": ["datasheets", "datasheets_models"],
                "joins": ["datasheets.Id = datasheets_models.DatasheetId"],
                "ambiguities": [],
            },
            schema,
        )

    def generate(self, question, plan, schema):
        self.generated = True
        return validate_generated_query(
            {
                "sql": (
                    "SELECT d.name AS unit, m.t AS toughness "
                    "FROM datasheets AS d JOIN datasheets_models AS m "
                    "ON d.Id = m.DatasheetId "
                    "WHERE CAST(m.t AS INTEGER) = ?"
                ),
                "parameters": [5],
            },
            plan,
            schema,
        )


def test_retriever_plans_generates_and_executes(tmp_path):
    path = database_path(tmp_path)
    model = FakeModel()
    retriever = SQLRetriever(
        ReadOnlyDatabase(path), SchemaCatalog.from_sqlite(path), model
    )

    output = retriever.retrieve("Which unit models have toughness 5?")

    assert output.status == "executed"
    assert output.result.rows == ({"unit": "Terminators", "toughness": "5"},)
    assert output.to_dict()["parameters"] == [5]
    assert model.generated is True


def test_ambiguity_stops_before_generation_and_execution(tmp_path):
    path = database_path(tmp_path)
    model = FakeModel(ambiguous=True)
    retriever = SQLRetriever(
        ReadOnlyDatabase(path), SchemaCatalog.from_sqlite(path), model
    )

    output = retriever.retrieve("Which units have that toughness?")

    assert output.status == "clarification"
    assert output.generated is None
    assert output.result is None
    assert model.generated is False


def test_unrelated_question_stops_before_model_call(tmp_path):
    path = database_path(tmp_path)

    class UnusedModel:
        def plan(self, question, schema):
            raise AssertionError("model should not be called")

        def generate(self, question, plan, schema):
            raise AssertionError("model should not be called")

    retriever = SQLRetriever(
        ReadOnlyDatabase(path), SchemaCatalog.from_sqlite(path), UnusedModel()
    )
    output = retriever.retrieve("Will it rain tomorrow?")

    assert output.status == "clarification"
    assert output.schema.tables == ()
