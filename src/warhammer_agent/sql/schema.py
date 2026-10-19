"""Small, read-only schema catalog for Text-to-SQL prompts."""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

TABLE_TOPICS = {
    "abilities": "ability rules faction",
    "datasheets": "unit datasheet faction source role loadout transport",
    "datasheets_abilities": "ability rules link",
    "datasheets_detachment_abilities": "detachment ability link",
    "datasheets_enhancements": "enhancement upgrade link",
    "datasheets_keywords": "keyword faction keyword",
    "datasheets_leader": "leader attached relationship",
    "datasheets_models": (
        "unit model statistics movement toughness save invulnerable save wounds "
        "leadership objective control base size"
    ),
    "datasheets_models_cost": "points cost",
    "datasheets_options": "wargear equipment option",
    "datasheets_stratagems": "stratagem link",
    "datasheets_unit_composition": "composition squad size",
    "datasheets_wargear": (
        "weapon wargear range attacks skill strength armour penetration damage"
    ),
    "detachment_abilities": "detachment ability rules faction",
    "detachments": "detachment faction force",
    "detachments_chapter_dp": "detachment chapter keyword",
    "enhancements": "enhancement upgrade faction detachment cost rules",
    "factions": "faction army",
    "last_update": "database update freshness date",
    "source": "publication source edition version errata",
    "stratagems": "stratagem faction detachment command points cost turn phase rules",
}

LOOKUP_TABLES = ("factions",)

# The database does not declare foreign keys. These joins are inferred from its IDs.
RELATIONSHIPS = (
    ("factions", "Id", "datasheets", "factionId"),
    ("source", "Id", "datasheets", "sourceId"),
    ("datasheets", "Id", "datasheets_abilities", "DatasheetId"),
    ("abilities", "Id", "datasheets_abilities", "abilityId"),
    ("datasheets", "Id", "datasheets_detachment_abilities", "DatasheetId"),
    (
        "detachment_abilities",
        "Id",
        "datasheets_detachment_abilities",
        "detachmentAbilityId",
    ),
    ("datasheets", "Id", "datasheets_enhancements", "DatasheetId"),
    ("enhancements", "id", "datasheets_enhancements", "enhancementId"),
    ("datasheets", "Id", "datasheets_keywords", "DatasheetId"),
    ("datasheets", "Id", "datasheets_leader", "LeaderId"),
    ("datasheets", "Id", "datasheets_leader", "attachedId"),
    ("datasheets", "Id", "datasheets_models", "DatasheetId"),
    ("datasheets", "Id", "datasheets_models_cost", "DatasheetId"),
    ("datasheets", "Id", "datasheets_options", "DatasheetId"),
    ("datasheets", "Id", "datasheets_stratagems", "DatasheetId"),
    ("stratagems", "id", "datasheets_stratagems", "stratagemId"),
    ("datasheets", "Id", "datasheets_unit_composition", "DatasheetId"),
    ("datasheets", "Id", "datasheets_wargear", "DatasheetId"),
    ("factions", "Id", "abilities", "factionId"),
    ("factions", "Id", "detachments", "factionId"),
    ("factions", "Id", "detachment_abilities", "factionId"),
    ("factions", "Id", "enhancements", "FactionId"),
    ("factions", "Id", "stratagems", "FactionId"),
    ("detachments", "Id", "detachment_abilities", "detachmentId"),
    ("detachments", "Id", "enhancements", "detachmentId"),
    ("detachments", "Id", "stratagems", "detachmentId"),
    ("detachments", "Id", "detachments_chapter_dp", "DetachmentId"),
)


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    sql_type: str


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[ColumnSchema, ...]
    topics: str = ""


@dataclass(frozen=True)
class Relationship:
    left_table: str
    left_column: str
    right_table: str
    right_column: str

    def render(self) -> str:
        return (
            f"{self.left_table}.{self.left_column} = "
            f"{self.right_table}.{self.right_column}"
        )


@dataclass(frozen=True)
class SchemaContext:
    tables: tuple[TableSchema, ...]
    relationships: tuple[Relationship, ...]

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(table.name for table in self.tables)

    def to_prompt(self) -> str:
        """Render compact schema context without reading table rows."""

        sections = []
        for table in self.tables:
            columns = ", ".join(
                f"{column.name} {column.sql_type or 'TEXT'}" for column in table.columns
            )
            sections.append(f"Table {table.name}: {table.topics}\nColumns: {columns}")
        if self.relationships:
            joins = "\n".join(
                f"- {relationship.render()}" for relationship in self.relationships
            )
            sections.append(f"Inferred relationships:\n{joins}")
        return "\n\n".join(sections)


class SchemaCatalog:
    """SQLite table metadata plus deterministic question-based selection."""

    def __init__(
        self,
        tables: tuple[TableSchema, ...],
        relationships: tuple[Relationship, ...],
    ):
        self.tables = tables
        self.relationships = relationships

    @classmethod
    def from_sqlite(cls, path: Path | str) -> "SchemaCatalog":
        database_path = Path(path).expanduser().resolve()
        if not database_path.is_file():
            raise FileNotFoundError(f"SQLite database does not exist: {database_path}")

        connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
        try:
            names = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema "
                    "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                )
            ]
            tables = tuple(
                TableSchema(
                    name=name,
                    columns=tuple(
                        ColumnSchema(column_name, sql_type)
                        for column_name, sql_type in connection.execute(
                            "SELECT name, type FROM pragma_table_info(?) ORDER BY cid",
                            (name,),
                        )
                    ),
                    topics=TABLE_TOPICS.get(name, ""),
                )
                for name in names
            )
        finally:
            connection.close()

        columns_by_table = {
            table.name: {column.name.casefold() for column in table.columns}
            for table in tables
        }
        relationships = tuple(
            Relationship(*relationship)
            for relationship in RELATIONSHIPS
            if relationship[0] in columns_by_table
            and relationship[2] in columns_by_table
            and relationship[1].casefold() in columns_by_table[relationship[0]]
            and relationship[3].casefold() in columns_by_table[relationship[2]]
        )
        return cls(tables, relationships)

    def select(self, question: str, *, max_tables: int = 5) -> SchemaContext:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question cannot be empty")
        if max_tables < 1:
            raise ValueError("max_tables must be positive")

        question_words = _words(question)
        ranked = []
        for table in self.tables:
            topic_words = _words(table.topics)
            column_words = _words(" ".join(column.name for column in table.columns))
            score = 2 * len(question_words & topic_words) + len(
                question_words & column_words
            )
            if score >= 2:
                ranked.append((score, table.name, table))

        selected = [
            item[2]
            for item in sorted(ranked, key=lambda item: (-item[0], item[1]))[
                :max_tables
            ]
        ]
        selected_names = {table.name for table in selected}
        tables_by_name = {table.name: table for table in self.tables}
        for lookup_name in LOOKUP_TABLES:
            if lookup_name in selected_names or len(selected) >= max_tables:
                continue
            is_related = any(
                (
                    relationship.left_table == lookup_name
                    and relationship.right_table in selected_names
                )
                or (
                    relationship.right_table == lookup_name
                    and relationship.left_table in selected_names
                )
                for relationship in self.relationships
            )
            if is_related and lookup_name in tables_by_name:
                selected.append(tables_by_name[lookup_name])
                selected_names.add(lookup_name)
        relationships = tuple(
            relationship
            for relationship in self.relationships
            if relationship.left_table in selected_names
            and relationship.right_table in selected_names
        )
        return SchemaContext(tuple(selected), relationships)


def _words(text: str) -> set[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text).replace("_", " ")
    words = re.findall(r"[a-z0-9]+", expanded.casefold())
    return {_singular(word) for word in words}


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word
