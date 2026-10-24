"""Load and validate the frozen agent evaluation dataset."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Category = Literal["rules", "database", "hybrid", "clarification"]
Route = Literal["rules", "database", "hybrid"]


def _strings(value: Any, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{field} must be an array of nonempty strings")
    if not allow_empty and not value:
        raise ValueError(f"{field} cannot be empty")
    return tuple(item.strip() for item in value)


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    category: Category
    question: str
    expected_route: Route
    expected_status: str
    required_sources: tuple[str, ...]
    expected_pdf_sections: tuple[str, ...]
    expected_sql_values: tuple[Any, ...]
    required_facts: tuple[tuple[str, ...], ...]
    reference_answer: str
    reference_contexts: tuple[str, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvaluationCase":
        expected = {
            "id",
            "category",
            "question",
            "expected_route",
            "expected_status",
            "required_sources",
            "expected_pdf_sections",
            "expected_sql_values",
            "required_facts",
            "reference_answer",
            "reference_contexts",
        }
        if set(payload) != expected:
            missing = sorted(expected - set(payload))
            extra = sorted(set(payload) - expected)
            raise ValueError(
                f"Invalid evaluation case keys; missing={missing}, extra={extra}"
            )
        identity = payload["id"]
        question = payload["question"]
        reference = payload["reference_answer"]
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("id must be a nonempty string")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{identity}: question must be a nonempty string")
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError(f"{identity}: reference_answer must be a nonempty string")
        category = payload["category"]
        route = payload["expected_route"]
        if category not in {"rules", "database", "hybrid", "clarification"}:
            raise ValueError(f"{identity}: invalid category")
        if route not in {"rules", "database", "hybrid"}:
            raise ValueError(f"{identity}: invalid expected_route")
        status = payload["expected_status"]
        if status not in {
            "answered",
            "clarification",
            "partial_answer",
            "insufficient_evidence",
        }:
            raise ValueError(f"{identity}: invalid expected_status")
        sources = _strings(payload["required_sources"], "required_sources")
        if not set(sources) <= {"pdf", "sql"} or len(sources) != len(set(sources)):
            raise ValueError(
                f"{identity}: required_sources must contain unique pdf/sql values"
            )
        sections = _strings(payload["expected_pdf_sections"], "expected_pdf_sections")
        sql_values = payload["expected_sql_values"]
        if not isinstance(sql_values, list):
            raise TypeError(f"{identity}: expected_sql_values must be an array")
        facts = payload["required_facts"]
        if not isinstance(facts, list) or not facts:
            raise ValueError(f"{identity}: required_facts must be a nonempty array")
        alternatives = tuple(
            _strings(group, f"{identity}.required_facts", allow_empty=False)
            for group in facts
        )
        contexts = _strings(
            payload["reference_contexts"], "reference_contexts", allow_empty=False
        )
        if "pdf" in sources and not sections:
            raise ValueError(f"{identity}: PDF cases require expected_pdf_sections")
        if "sql" in sources and not sql_values:
            raise ValueError(f"{identity}: SQL cases require expected_sql_values")
        if category == "clarification" and (sources or sections or sql_values):
            raise ValueError(f"{identity}: clarification cases cannot require evidence")
        return cls(
            id=identity.strip(),
            category=category,
            question=question.strip(),
            expected_route=route,
            expected_status=status,
            required_sources=sources,
            expected_pdf_sections=sections,
            expected_sql_values=tuple(sql_values),
            required_facts=alternatives,
            reference_answer=reference.strip(),
            reference_contexts=contexts,
        )


def load_cases(path: Path) -> list[EvaluationCase]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list) or not payload:
        raise ValueError("The evaluation dataset must be a nonempty JSON array")
    cases = [EvaluationCase.from_dict(item) for item in payload]
    identities = [case.id for case in cases]
    if len(identities) != len(set(identities)):
        raise ValueError("Evaluation case IDs must be unique")
    return cases
