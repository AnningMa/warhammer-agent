"""Bounded, read-only SQLite query execution."""

import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .safety import ValidatedQuery, validate_readonly_sql


class SQLExecutionError(RuntimeError):
    """Raised when SQLite cannot execute an otherwise validated query."""


class SQLTimeoutError(SQLExecutionError):
    """Raised when a query exceeds its execution deadline."""


@dataclass(frozen=True)
class QueryResult:
    """Serializable rows plus the validated query and truncation metadata."""

    query: ValidatedQuery
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool
    elapsed_seconds: float


_DENIED_ACTIONS = {
    sqlite3.SQLITE_ALTER_TABLE,
    sqlite3.SQLITE_ANALYZE,
    sqlite3.SQLITE_ATTACH,
    sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TEMP_VIEW,
    sqlite3.SQLITE_CREATE_TRIGGER,
    sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_DROP_INDEX,
    sqlite3.SQLITE_DROP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE,
    sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TEMP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER,
    sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_PRAGMA,
    sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_SAVEPOINT,
    sqlite3.SQLITE_TRANSACTION,
    sqlite3.SQLITE_UPDATE,
}


class ReadOnlyDatabase:
    """Validate and execute bounded queries against one SQLite file."""

    def __init__(self, path: Path | str, *, max_rows: int = 100, timeout: float = 2):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"SQLite database does not exist: {self.path}")
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.max_rows = max_rows
        self.timeout = timeout
        self._tables = self._load_tables()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"{self.path.as_uri()}?mode=ro",
            uri=True,
            timeout=self.timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def _load_tables(self) -> tuple[str, ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT name FROM sqlite_schema "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
        finally:
            connection.close()
        return tuple(row[0] for row in rows)

    @property
    def tables(self) -> tuple[str, ...]:
        return self._tables

    @staticmethod
    def _authorizer(
        action: int,
        argument1: str | None,
        argument2: str | None,
        database: str | None,
        trigger: str | None,
    ) -> int:
        del argument1, database, trigger
        if action in _DENIED_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (argument2 or "").casefold() in {
            "load_extension",
            "readfile",
            "writefile",
        }:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def execute(
        self,
        sql: str,
        parameters: Sequence[Any] | Mapping[str, Any] = (),
    ) -> QueryResult:
        query = validate_readonly_sql(sql, allowed_tables=self.tables)
        started = time.perf_counter()
        deadline = started + self.timeout
        connection = self._connect()
        try:
            connection.set_authorizer(self._authorizer)
            connection.set_progress_handler(
                lambda: 1 if time.perf_counter() > deadline else 0, 1000
            )
            cursor = connection.execute(query.sql, parameters)
            columns = tuple(item[0] for item in (cursor.description or ()))
            if len({column.casefold() for column in columns}) != len(columns):
                raise SQLExecutionError(
                    "SQL result columns must have unique names; alias duplicate columns"
                )
            fetched = cursor.fetchmany(self.max_rows + 1)
        except sqlite3.OperationalError as error:
            if "interrupted" in str(error).casefold():
                raise SQLTimeoutError(
                    f"SQL query exceeded the {self.timeout:g}-second timeout"
                ) from error
            raise SQLExecutionError(
                f"SQLite could not execute the query: {error}"
            ) from error
        except sqlite3.DatabaseError as error:
            raise SQLExecutionError(f"SQLite rejected the query: {error}") from error
        finally:
            connection.close()

        truncated = len(fetched) > self.max_rows
        rows = tuple(dict(row) for row in fetched[: self.max_rows])
        return QueryResult(
            query=query,
            columns=columns,
            rows=rows,
            truncated=truncated,
            elapsed_seconds=time.perf_counter() - started,
        )
