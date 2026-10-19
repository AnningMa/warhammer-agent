import pytest

from warhammer_agent.sql.safety import (
    SQLValidationError,
    validate_readonly_sql,
)

TABLES = {"datasheets", "datasheets_models"}


def test_select_and_readonly_cte_are_accepted():
    simple = validate_readonly_sql(
        "SELECT name FROM datasheets WHERE lower(name) LIKE ? LIMIT 10",
        allowed_tables=TABLES,
    )
    assert simple.tables == ("datasheets",)
    assert simple.functions == ("LOWER",)

    multiple_filters = validate_readonly_sql(
        "SELECT name FROM datasheets WHERE name = ? AND Id != ?",
        allowed_tables=TABLES,
    )
    assert multiple_filters.functions == ()

    cte = validate_readonly_sql(
        """
        WITH tough AS (
          SELECT DatasheetId, MAX(CAST(t AS INTEGER)) AS maximum
          FROM datasheets_models
          GROUP BY DatasheetId
        )
        SELECT d.name, tough.maximum
        FROM datasheets AS d
        JOIN tough ON tough.DatasheetId = d.Id
        """,
        allowed_tables=TABLES,
    )
    assert cte.tables == ("datasheets", "datasheets_models")
    assert set(cte.functions) == {"CAST", "MAX"}


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO datasheets(name) VALUES ('x')",
        "UPDATE datasheets SET name = 'x'",
        "DELETE FROM datasheets",
        "DROP TABLE datasheets",
        "ALTER TABLE datasheets ADD COLUMN x TEXT",
        "ATTACH DATABASE '/tmp/other.sqlite' AS other",
        "PRAGMA table_info(datasheets)",
    ],
)
def test_writes_and_administrative_statements_are_rejected(sql):
    with pytest.raises(SQLValidationError, match="Only SELECT|write|administrative"):
        validate_readonly_sql(sql, allowed_tables=TABLES)


def test_multiple_statements_unknown_tables_and_functions_are_rejected():
    with pytest.raises(SQLValidationError, match="Exactly one"):
        validate_readonly_sql(
            "SELECT * FROM datasheets; SELECT * FROM datasheets_models",
            allowed_tables=TABLES,
        )
    with pytest.raises(SQLValidationError, match="unknown or disallowed tables"):
        validate_readonly_sql("SELECT * FROM secrets", allowed_tables=TABLES)
    with pytest.raises(SQLValidationError, match="disallowed functions"):
        validate_readonly_sql("SELECT load_extension('unsafe')", allowed_tables=TABLES)


def test_empty_invalid_and_other_database_queries_are_rejected():
    with pytest.raises(SQLValidationError, match="cannot be empty"):
        validate_readonly_sql(" ", allowed_tables=TABLES)
    with pytest.raises(SQLValidationError, match="not valid"):
        validate_readonly_sql("SELECT (", allowed_tables=TABLES)
    with pytest.raises(SQLValidationError, match="main SQLite database"):
        validate_readonly_sql("SELECT * FROM other.datasheets", allowed_tables=TABLES)
