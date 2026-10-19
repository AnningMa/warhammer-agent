"""End-to-end orchestration for safe natural-language SQLite queries."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .database import QueryResult, ReadOnlyDatabase
from .generator import GeneratedQuery
from .planner import QueryPlan
from .schema import SchemaCatalog, SchemaContext


class SQLModel(Protocol):
    def plan(self, question: str, schema: SchemaContext) -> QueryPlan: ...

    def generate(
        self, question: str, plan: QueryPlan, schema: SchemaContext
    ) -> GeneratedQuery: ...


@dataclass(frozen=True)
class SQLRetrievalResult:
    question: str
    schema: SchemaContext
    plan: QueryPlan
    generated: GeneratedQuery | None = None
    result: QueryResult | None = None

    @property
    def status(self) -> str:
        return "clarification" if self.plan.ambiguities else "executed"

    def to_dict(self) -> dict[str, Any]:
        output: dict[str, Any] = {
            "status": self.status,
            "question": self.question,
            "schema_tables": list(self.schema.table_names),
            "query_plan": self.plan.to_dict(),
        }
        if self.plan.ambiguities:
            output["clarification"] = self.plan.ambiguities[0]
        if self.generated is not None:
            output.update(
                {
                    "sql": self.generated.sql,
                    "parameters": list(self.generated.parameters),
                    "model_version": self.generated.model_version,
                    "usage": self.generated.usage,
                }
            )
        if self.result is not None:
            output.update(
                {
                    "columns": list(self.result.columns),
                    "rows": list(self.result.rows),
                    "truncated": self.result.truncated,
                    "elapsed_seconds": self.result.elapsed_seconds,
                }
            )
        return output


class SQLRetriever:
    def __init__(
        self,
        database: ReadOnlyDatabase,
        catalog: SchemaCatalog,
        model: SQLModel,
        *,
        max_tables: int = 6,
        progress: Callable[[str], None] | None = None,
    ):
        if max_tables < 1:
            raise ValueError("max_tables must be positive")
        self.database = database
        self.catalog = catalog
        self.model = model
        self.max_tables = max_tables
        self.progress = progress or (lambda message: None)

    def retrieve(self, question: str) -> SQLRetrievalResult:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question cannot be empty")
        question = question.strip()
        schema = self.catalog.select(question, max_tables=self.max_tables)
        if not schema.tables:
            plan = QueryPlan(
                metric="unknown",
                dimensions=(),
                filters=(),
                candidate_tables=(),
                joins=(),
                ambiguities=(
                    "No relevant database schema was found for this question.",
                ),
            )
            return SQLRetrievalResult(question, schema, plan)

        self.progress("正在调用 Gemini 生成查询计划……")
        plan = self.model.plan(question, schema)
        if plan.ambiguities:
            return SQLRetrievalResult(question, schema, plan)

        self.progress("查询计划已通过，正在调用 Gemini 生成 SQL……")
        generated = self.model.generate(question, plan, schema)
        self.progress("SQL 已通过本地验证，正在只读查询数据库……")
        result = self.database.execute(generated.sql, generated.parameters)
        return SQLRetrievalResult(question, schema, plan, generated, result)
