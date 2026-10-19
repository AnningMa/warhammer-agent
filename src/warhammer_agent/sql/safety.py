"""AST-based validation for model-generated SQLite queries."""

from collections.abc import Collection
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class SQLValidationError(ValueError):
    """Raised when a query is not an approved, read-only SQLite query."""


@dataclass(frozen=True)
class ValidatedQuery:
    """A query that passed syntax, operation, table, and function checks."""

    sql: str
    tables: tuple[str, ...]
    functions: tuple[str, ...]


DEFAULT_ALLOWED_FUNCTIONS = frozenset(
    {
        "ABS",
        "AVG",
        "CAST",
        "COALESCE",
        "COUNT",
        "DATE",
        "DATETIME",
        "GROUP_CONCAT",
        "IFNULL",
        "INSTR",
        "JULIANDAY",
        "LENGTH",
        "LOWER",
        "LTRIM",
        "MAX",
        "MIN",
        "NULLIF",
        "REPLACE",
        "ROUND",
        "RTRIM",
        "STRFTIME",
        "SUBSTR",
        "SUM",
        "TIME",
        "TOTAL",
        "TRIM",
        "TYPEOF",
        "UPPER",
    }
)


def _normalized(values: Collection[str]) -> set[str]:
    return {value.casefold() for value in values}


def validate_readonly_sql(
    sql: str,
    *,
    allowed_tables: Collection[str] | None = None,
    allowed_functions: Collection[str] = DEFAULT_ALLOWED_FUNCTIONS,
) -> ValidatedQuery:
    """Require one SQLite SELECT query over approved tables and functions."""

    if not isinstance(sql, str) or not sql.strip():
        raise SQLValidationError("SQL query cannot be empty")
    try:
        statements = [statement for statement in parse(sql, read="sqlite") if statement]
    except ParseError as error:
        raise SQLValidationError("SQL query is not valid SQLite syntax") from error
    if len(statements) != 1:
        raise SQLValidationError("Exactly one SQL statement is allowed")

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise SQLValidationError("Only SELECT or WITH ... SELECT queries are allowed")

    # A query root should not contain write/admin nodes, including inside a CTE.
    forbidden = (
        exp.Alter,
        exp.Attach,
        exp.Command,
        exp.Create,
        exp.Delete,
        exp.Detach,
        exp.Drop,
        exp.Insert,
        exp.Merge,
        exp.Transaction,
        exp.Update,
    )
    if any(statement.find(kind) is not None for kind in forbidden):
        raise SQLValidationError("SQL contains a write or administrative operation")

    cte_names = {
        cte.alias_or_name.casefold()
        for cte in statement.find_all(exp.CTE)
        if cte.alias_or_name
    }
    tables = set()
    for table in statement.find_all(exp.Table):
        if table.db and table.db.casefold() != "main":
            raise SQLValidationError("Only the main SQLite database is allowed")
        name = table.name
        if name and name.casefold() not in cte_names:
            tables.add(name)

    if allowed_tables is not None:
        approved = _normalized(allowed_tables)
        unknown = sorted(name for name in tables if name.casefold() not in approved)
        if unknown:
            raise SQLValidationError(
                "SQL references unknown or disallowed tables: " + ", ".join(unknown)
            )

    approved_functions = {name.upper() for name in allowed_functions}
    syntax_nodes = (exp.Connector, exp.Case, exp.If)
    functions = {
        function.sql_name().upper()
        for function in statement.find_all(exp.Func)
        if not isinstance(function, syntax_nodes)
    }
    unknown_functions = sorted(functions - approved_functions)
    if unknown_functions:
        raise SQLValidationError(
            "SQL uses disallowed functions: " + ", ".join(unknown_functions)
        )

    return ValidatedQuery(
        sql=sql.strip(),
        tables=tuple(sorted(tables, key=str.casefold)),
        functions=tuple(sorted(functions)),
    )
