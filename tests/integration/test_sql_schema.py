import sqlite3

import pytest

from warhammer_agent.sql import SchemaCatalog


def catalog(tmp_path):
    path = tmp_path / "rules.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE datasheets (Id TEXT, name TEXT, factionId TEXT);
        CREATE TABLE datasheets_models (
            DatasheetId TEXT, name TEXT, m TEXT, t TEXT, w TEXT
        );
        CREATE TABLE datasheets_unit_composition (
            DatasheetId TEXT, description TEXT
        );
        CREATE TABLE factions (Id TEXT, name TEXT);
        INSERT INTO datasheets VALUES ('1', 'Secret unit row', 'SM');
        """
    )
    connection.close()
    return SchemaCatalog.from_sqlite(path)


def test_catalog_loads_columns_without_row_values(tmp_path):
    schema = catalog(tmp_path)
    datasheets = next(table for table in schema.tables if table.name == "datasheets")

    assert [column.name for column in datasheets.columns] == [
        "Id",
        "name",
        "factionId",
    ]
    assert (
        "Secret unit row"
        not in SchemaCatalog.from_sqlite(tmp_path / "rules.sqlite")
        .select("unit")
        .to_prompt()
    )


def test_question_selects_relevant_tables_and_joins(tmp_path):
    context = catalog(tmp_path).select(
        "Which unit models have toughness 5?", max_tables=5
    )

    assert set(context.table_names) == {
        "datasheets",
        "datasheets_models",
        "factions",
    }
    assert any(
        relationship.render() == "datasheets.Id = datasheets_models.DatasheetId"
        for relationship in context.relationships
    )
    assert any(
        relationship.render() == "factions.Id = datasheets.factionId"
        for relationship in context.relationships
    )
    assert "Columns: DatasheetId TEXT" in context.to_prompt()


def test_unknown_question_returns_no_schema(tmp_path):
    context = catalog(tmp_path).select("Who painted this miniature?")
    assert context.tables == ()
    assert context.to_prompt() == ""


def test_invalid_input_and_missing_database_fail_early(tmp_path):
    schema = catalog(tmp_path)
    with pytest.raises(ValueError, match="question"):
        schema.select(" ")
    with pytest.raises(ValueError, match="max_tables"):
        schema.select("unit", max_tables=0)
    with pytest.raises(FileNotFoundError):
        SchemaCatalog.from_sqlite(tmp_path / "missing.sqlite")
