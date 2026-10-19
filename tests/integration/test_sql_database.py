import sqlite3

import pytest

from warhammer_agent.sql.database import ReadOnlyDatabase, SQLExecutionError
from warhammer_agent.sql.safety import (
    SQLValidationError,
    ValidatedQuery,
)


def database(tmp_path, *, max_rows=100):
    path = tmp_path / "rules.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE datasheets (Id TEXT, name TEXT);
        CREATE TABLE datasheets_models (
            DatasheetId TEXT, name TEXT, t TEXT, w TEXT
        );
        INSERT INTO datasheets VALUES
            ('1', 'Intercessor Squad'),
            ('2', 'Terminator Squad');
        INSERT INTO datasheets_models VALUES
            ('1', 'Intercessor', '4', '2'),
            ('2', 'Terminator', '5', '3'),
            ('2', 'Terminator Sergeant', '5', '3');
        """
    )
    connection.close()
    return ReadOnlyDatabase(path, max_rows=max_rows)


def test_readonly_join_returns_structured_rows(tmp_path):
    db = database(tmp_path)
    result = db.execute(
        """
        SELECT d.name AS unit, m.name AS model, m.t AS toughness
        FROM datasheets AS d
        JOIN datasheets_models AS m ON d.Id = m.DatasheetId
        WHERE lower(d.name) LIKE ?
        ORDER BY m.name
        """,
        ("%terminator%",),
    )
    assert result.columns == ("unit", "model", "toughness")
    assert result.rows == (
        {
            "unit": "Terminator Squad",
            "model": "Terminator",
            "toughness": "5",
        },
        {
            "unit": "Terminator Squad",
            "model": "Terminator Sergeant",
            "toughness": "5",
        },
    )
    assert result.query.tables == ("datasheets", "datasheets_models")
    assert result.truncated is False
    assert result.elapsed_seconds >= 0


def test_result_limit_is_reported_without_returning_extra_rows(tmp_path):
    db = database(tmp_path, max_rows=2)
    result = db.execute("SELECT name FROM datasheets_models ORDER BY name")
    assert len(result.rows) == 2
    assert result.truncated is True


def test_unknown_table_and_write_are_rejected_before_execution(tmp_path):
    db = database(tmp_path)
    with pytest.raises(SQLValidationError, match="unknown or disallowed"):
        db.execute("SELECT * FROM missing")
    with pytest.raises(SQLValidationError, match="Only SELECT"):
        db.execute("UPDATE datasheets SET name = 'changed'")

    # A second connection confirms no write reached the database.
    connection = sqlite3.connect(tmp_path / "rules.sqlite")
    names = [row[0] for row in connection.execute("SELECT name FROM datasheets")]
    connection.close()
    assert names == ["Intercessor Squad", "Terminator Squad"]


def test_sqlite_authorizer_blocks_write_if_validation_is_bypassed(
    tmp_path, monkeypatch
):
    db = database(tmp_path)
    unsafe = ValidatedQuery(
        "UPDATE datasheets SET name = 'changed'", ("datasheets",), ()
    )
    monkeypatch.setattr(
        "warhammer_agent.sql.database.validate_readonly_sql",
        lambda *args, **kwargs: unsafe,
    )
    with pytest.raises(SQLExecutionError, match="not authorized"):
        db.execute(unsafe.sql)

    connection = sqlite3.connect(tmp_path / "rules.sqlite")
    names = [row[0] for row in connection.execute("SELECT name FROM datasheets")]
    connection.close()
    assert names == ["Intercessor Squad", "Terminator Squad"]


def test_duplicate_result_column_names_are_rejected(tmp_path):
    db = database(tmp_path)
    with pytest.raises(SQLExecutionError, match="unique names"):
        db.execute(
            "SELECT d.name, m.name FROM datasheets AS d "
            "JOIN datasheets_models AS m ON d.Id = m.DatasheetId"
        )


def test_missing_database_and_invalid_limits_fail_early(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReadOnlyDatabase(tmp_path / "missing.sqlite")
    path = tmp_path / "empty.sqlite"
    sqlite3.connect(path).close()
    with pytest.raises(ValueError, match="max_rows"):
        ReadOnlyDatabase(path, max_rows=0)
    with pytest.raises(ValueError, match="timeout"):
        ReadOnlyDatabase(path, timeout=0)
