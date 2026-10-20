"""Bounded typed evidence and application-owned PDF/SQL citations."""

import json
import re

from warhammer_agent.rag.generation import Answer


def encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def pack_evidence(pdf, sql, settings):
    """Reserve SQL context first, then pack complete PDF/example bundles."""
    evidence, omitted = [], []
    if sql and sql.get("status") == "executed":
        rows = sql["rows"]
        item = {
            "kind": "sql",
            "database_path": sql["database_path"],
            "schema_tables": sql["schema_tables"],
            "sql": sql["sql"],
            "parameters": sql["parameters"],
            "columns": sql["columns"],
            "rows": [],
            "returned_rows": len(rows),
            "included_rows": 0,
            "omitted_rows": len(rows),
            "tool_truncated": sql["truncated"],
            "truncated": bool(rows) or sql["truncated"],
            "citation_id": "S1",
        }
        budget = min(settings["sql_context_bytes"], settings["max_context_bytes"])
        # Measure each candidate including all omission metadata and delimiters.
        if encoded_size([item]) <= budget:
            for row in rows:
                candidate = {
                    **item,
                    "rows": item["rows"] + [row],
                    "included_rows": item["included_rows"] + 1,
                    "omitted_rows": len(rows) - item["included_rows"] - 1,
                }
                candidate["truncated"] = (
                    sql["truncated"] or candidate["omitted_rows"] > 0
                )
                if encoded_size([candidate]) > budget:
                    break
                item = candidate
            evidence.append(item)
        else:
            omitted.append("sql_result")
    bundles = {}
    for original in pdf:
        bundles.setdefault(
            original.get("retrieved_by", original["block_id"]), []
        ).append(original)
    for identity, bundle in bundles.items():
        additions = [
            {**item, "kind": "pdf", "citation_id": f"S{len(evidence) + i + 1}"}
            for i, item in enumerate(bundle)
        ]
        if encoded_size(evidence + additions) > settings["max_context_bytes"]:
            omitted.append(identity)
        else:
            evidence.extend(additions)
    return evidence, omitted


def validate_answer(payload, evidence):
    answer = Answer.model_validate(payload)
    pattern = r"\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]"
    inline = {
        identity.strip()
        for group in re.findall(pattern, answer.answer)
        for identity in group.split(",")
    }
    by_id = {e["citation_id"]: e for e in evidence}
    ids = answer.citations
    if len(ids) != len(set(ids)) or set(ids) != inline or not inline <= by_id.keys():
        raise ValueError(
            "Answer citations must match inline references and supplied evidence"
        )
    if not answer.answer.strip() or (not answer.insufficient_evidence and not ids):
        raise ValueError("A supported answer must be nonempty and cite its evidence")
    citations = []
    for identity in ids:
        item = by_id[identity]
        if item["kind"] == "pdf":
            citation = {
                key: item[key]
                for key in (
                    "block_id",
                    "source",
                    "source_path",
                    "section_title",
                    "page_numbers",
                    "review_status",
                )
            }
            citation["page_number_basis"] = "physical_pdf_1_based"
        else:
            citation = {
                key: item[key]
                for key in (
                    "database_path",
                    "schema_tables",
                    "sql",
                    "parameters",
                    "columns",
                    "rows",
                    "returned_rows",
                    "included_rows",
                    "omitted_rows",
                    "truncated",
                    "tool_truncated",
                )
            }
        citations.append({"citation_id": identity, "kind": item["kind"], **citation})
    return {
        "answer": re.sub(
            pattern,
            lambda match: " ".join(f"[{s.strip()}]" for s in match[1].split(",")),
            answer.answer,
        ),
        "citations": citations,
        "insufficient_evidence": answer.insufficient_evidence,
    }
