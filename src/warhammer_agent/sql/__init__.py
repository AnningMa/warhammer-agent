"""Safe, read-only access to the Warhammer SQLite database."""

from .database import (
    QueryResult,
    ReadOnlyDatabase,
    SQLExecutionError,
    SQLTimeoutError,
)
from .generator import (
    GeminiSQLGenerator,
    GeneratedQuery,
    SQLGenerationError,
    validate_generated_query,
)
from .planner import QueryFilter, QueryPlan, QueryPlanError, parse_query_plan
from .retriever import SQLRetrievalResult, SQLRetriever
from .safety import SQLValidationError, ValidatedQuery, validate_readonly_sql
from .schema import (
    ColumnSchema,
    Relationship,
    SchemaCatalog,
    SchemaContext,
    TableSchema,
)

__all__ = [
    "ColumnSchema",
    "GeminiSQLGenerator",
    "GeneratedQuery",
    "QueryFilter",
    "QueryPlan",
    "QueryPlanError",
    "QueryResult",
    "ReadOnlyDatabase",
    "Relationship",
    "SQLExecutionError",
    "SQLGenerationError",
    "SQLRetrievalResult",
    "SQLRetriever",
    "SQLTimeoutError",
    "SQLValidationError",
    "SchemaCatalog",
    "SchemaContext",
    "TableSchema",
    "ValidatedQuery",
    "parse_query_plan",
    "validate_generated_query",
    "validate_readonly_sql",
]
