"""Lazily initialize tool resources only on the selected route."""

import json
from pathlib import Path

from warhammer_agent.rag.pipeline import RuleRetriever, retrieve_evidence
from warhammer_agent.sql.database import ReadOnlyDatabase
from warhammer_agent.sql.generator import GeminiSQLGenerator
from warhammer_agent.sql.retriever import SQLRetriever
from warhammer_agent.sql.schema import SchemaCatalog

from .model import AgentModel


class AgentServices:
    def __init__(self, root: Path, config: dict):
        self.root, self.config = root, config
        self.rag = json.loads((root / config["rag_config"]).read_text())
        self.sql = json.loads((root / config["sql_config"]).read_text())
        self._model = self._pdf = self._sql_model = self._sql = None

    @property
    def model(self):
        if self._model is None:
            self._model = AgentModel(self.root, self.rag["generation"])
        return self._model

    def retrieve_pdf(self, original, plan, history, rewrite):
        if self._pdf is None:
            self._pdf = RuleRetriever(self.root, self.rag)
        # Planning was performed once before routing, never inside this tool.
        return retrieve_evidence(
            original,
            self._pdf,
            self.model,
            self.rag,
            history=history,
            query_plan=plan,
            rewrite_info=rewrite,
        )

    def retrieve_sql(self, question):
        if self._sql is None:
            path = self.root / self.sql["database_path"]
            catalog = SchemaCatalog.from_sqlite(path)
            database = ReadOnlyDatabase(
                path, max_rows=self.sql["max_rows"], timeout=self.sql["timeout_seconds"]
            )
            self._sql_model = GeminiSQLGenerator(self.root, self.sql["generation"])
            self._sql = SQLRetriever(
                database, catalog, self._sql_model, max_tables=self.sql["max_tables"]
            )
        return {
            **self._sql.retrieve(question).to_dict(),
            "database_path": self.sql["database_path"],
            "planning_usage": getattr(self._sql_model, "planning_usage", None),
        }

    def close(self):
        for resource in (self._pdf, self._sql_model, self._model):
            if resource is not None:
                resource.close()
