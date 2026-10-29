"""Structured and validated query plans for the SQL generation step."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from .schema import Relationship, SchemaContext


class QueryPlanError(ValueError):
    """Raised when a query plan is incomplete or references unknown schema."""


ALLOWED_OPERATORS = frozenset(
    {"=", "!=", "<", "<=", ">", ">=", "LIKE", "IN", "IS NULL", "IS NOT NULL"}
)


@dataclass(frozen=True)
class QueryFilter:
    column: str
    operator: str
    value: Any = None


@dataclass(frozen=True)
class QueryPlan:
    metric: str
    dimensions: tuple[str, ...]
    filters: tuple[QueryFilter, ...]
    candidate_tables: tuple[str, ...]
    joins: tuple[Relationship, ...]
    aggregation_grain: str | None = None
    time_range: str | None = None
    assumptions: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "dimensions": list(self.dimensions),
            "filters": [
                {
                    "column": item.column,
                    "operator": item.operator,
                    "value": item.value,
                }
                for item in self.filters
            ],
            "candidate_tables": list(self.candidate_tables),
            "joins": [join.render() for join in self.joins],
            "aggregation_grain": self.aggregation_grain,
            "time_range": self.time_range,
            "assumptions": list(self.assumptions),
            "ambiguities": list(self.ambiguities),
        }


def parse_query_plan(payload: Mapping[str, Any], schema: SchemaContext) -> QueryPlan:
    """Parse model JSON and require every schema reference to be approved."""

    if not isinstance(payload, Mapping):
        raise QueryPlanError("query plan must be an object")

    metric = _required_string(payload, "metric")
    dimensions = _string_tuple(payload.get("dimensions", ()), "dimensions")
    candidate_tables = _string_tuple(
        payload.get("candidate_tables", ()), "candidate_tables"
    )
    assumptions = _string_tuple(payload.get("assumptions", ()), "assumptions")
    ambiguities = _string_tuple(payload.get("ambiguities", ()), "ambiguities")
    aggregation_grain = _optional_string(payload.get("aggregation_grain"))
    time_range = _optional_string(payload.get("time_range"))

    allowed_tables = {table.name: table for table in schema.tables}
    unknown_tables = sorted(set(candidate_tables) - allowed_tables.keys())
    if unknown_tables:
        raise QueryPlanError("unknown candidate tables: " + ", ".join(unknown_tables))
    if not candidate_tables and not ambiguities:
        raise QueryPlanError("candidate_tables cannot be empty without an ambiguity")

    filters = _parse_filters(payload.get("filters", ()))
    for reference in (*dimensions, *(item.column for item in filters)):
        _validate_column(reference, candidate_tables, allowed_tables)

    relationships: dict[str, Relationship] = {}
    for item in schema.relationships:
        relationships[item.render()] = item
        relationships[
            f"{item.right_table}.{item.right_column} = "
            f"{item.left_table}.{item.left_column}"
        ] = item
    join_names = _string_tuple(payload.get("joins", ()), "joins")
    unknown_joins = sorted(set(join_names) - relationships.keys())
    if unknown_joins:
        raise QueryPlanError("unknown joins: " + ", ".join(unknown_joins))
    joins = tuple(relationships[name] for name in join_names)
    for join in joins:
        if (
            join.left_table not in candidate_tables
            or join.right_table not in candidate_tables
        ):
            raise QueryPlanError("every join table must appear in candidate_tables")
    _validate_join_graph(candidate_tables, joins)

    return QueryPlan(
        metric=metric,
        dimensions=dimensions,
        filters=filters,
        candidate_tables=candidate_tables,
        joins=joins,
        aggregation_grain=aggregation_grain,
        time_range=time_range,
        assumptions=assumptions,
        ambiguities=ambiguities,
    )


def _parse_filters(value: Any) -> tuple[QueryFilter, ...]:
    if not _is_sequence(value):
        raise QueryPlanError("filters must be a list")

    filters = []
    for item in value:
        if not isinstance(item, Mapping):
            raise QueryPlanError("each filter must be an object")
        column = _required_string(item, "column")
        operator = _required_string(item, "operator").upper()
        if operator not in ALLOWED_OPERATORS:
            raise QueryPlanError(f"unsupported filter operator: {operator}")
        filter_value = item.get("value")
        if operator in {"IS NULL", "IS NOT NULL"} and filter_value is not None:
            raise QueryPlanError(f"{operator} filters must use a null value")
        if operator == "IN" and (not _is_sequence(filter_value) or not filter_value):
            raise QueryPlanError("IN filters require a non-empty value list")
        if operator == "IN":
            values = cast(Sequence[Any], filter_value)
            if any(not _is_scalar(item) for item in values):
                raise QueryPlanError("IN filter values must be scalars")
        if operator not in {"IN", "IS NULL", "IS NOT NULL"} and not _is_scalar(
            filter_value
        ):
            raise QueryPlanError("filter values must be scalars")
        if operator not in {"IS NULL", "IS NOT NULL"} and filter_value is None:
            raise QueryPlanError("null values require IS NULL or IS NOT NULL")
        filters.append(QueryFilter(column, operator, filter_value))
    return tuple(filters)


def _validate_join_graph(
    candidate_tables: tuple[str, ...], joins: tuple[Relationship, ...]
) -> None:
    if len(candidate_tables) < 2:
        return
    connected = {candidate_tables[0]}
    while True:
        expanded = connected | {
            table
            for join in joins
            for table in (join.left_table, join.right_table)
            if join.left_table in connected or join.right_table in connected
        }
        if expanded == connected:
            break
        connected = expanded
    if set(candidate_tables) - connected:
        raise QueryPlanError("candidate tables are not connected by joins")


def _validate_column(
    reference: str,
    candidate_tables: tuple[str, ...],
    allowed_tables: Mapping[str, Any],
) -> None:
    if reference.count(".") != 1:
        raise QueryPlanError(f"column must use table.column form: {reference}")
    table_name, column_name = reference.split(".")
    if table_name not in candidate_tables:
        raise QueryPlanError(f"column table is not a candidate table: {table_name}")
    columns = {column.name.casefold() for column in allowed_tables[table_name].columns}
    if column_name.casefold() not in columns:
        raise QueryPlanError(f"unknown column: {reference}")


def _required_string(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise QueryPlanError(f"{key} must be a non-empty string")
    return item.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise QueryPlanError("optional text fields must be non-empty strings or null")
    return value.strip()


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not _is_sequence(value) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise QueryPlanError(f"{field} must be a list of non-empty strings")
    items = tuple(item.strip() for item in value)
    if len(set(items)) != len(items):
        raise QueryPlanError(f"{field} cannot contain duplicates")
    return items


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))
