"""Retrieve complete rules, pack evidence without truncation, then generate."""

import json
import time
from pathlib import Path

from warhammer_agent.embeddings.chroma_store import ChromaStore
from warhammer_agent.embeddings.cli import fingerprint, sha256
from warhammer_agent.embeddings.parent_child import parent_hits
from warhammer_agent.embeddings.providers import create_embedder

from .generation import make_prompt
from .refinement import (
    failure_details,
    fuse_hits,
    needs_rewrite,
    plan_queries,
    rerank_parents,
    validate_history,
)


def select_evidence(hits: list[dict], parents: list[dict], max_bytes: int):
    """Keep each rule + its example's main rule as an indivisible bundle."""
    by_id = {b["block_id"]: b for b in parents}
    chosen, included, omitted = [], set(), []
    for hit in hits:
        block = by_id[hit["block_id"]]
        bundle = [block]
        related = block.get("parent_rule_id")
        if related:
            if related not in by_id:
                raise ValueError("示例关联的完整主规则缺失")
            bundle.append(by_id[related])
        additions = []
        for parent in bundle:
            if parent["block_id"] in included:
                continue
            additions.append(
                {
                    "citation_id": f"S{len(chosen) + len(additions) + 1}",
                    "block_id": parent["block_id"],
                    "section_title": parent["section_title"],
                    "embedding_context": parent.get("embedding_context"),
                    "text": parent["text"],
                    "source": parent["source"],
                    "source_path": parent["source_path"],
                    "page_numbers": parent["page_numbers"],
                    "review_status": parent["review_status"],
                    "source_segments": parent["source_segments"],
                    "retrieved_by": hit["block_id"],
                    "relationship": "retrieved_rule"
                    if parent is block
                    else "example_main_rule",
                }
            )
        # Budget the exact serialized evidence payload sent to Gemini. This
        # is a UTF-8 byte guard, explicitly not a Gemini token estimate.
        size = len(make_prompt("", chosen + additions).encode("utf-8"))
        if size > max_bytes:
            omitted.append(hit["block_id"])
            continue
        chosen.extend(additions)
        included.update(item["block_id"] for item in additions)
    return chosen, omitted


class RuleRetriever:
    def __init__(self, root: Path, settings: dict):
        self.root, self.settings = root, settings
        experiment = json.loads((root / settings["parent_child_config"]).read_text())
        config = json.loads((root / experiment["embedding_config"]).read_text())
        path = root / experiment["output"]
        records = [json.loads(line) for line in path.read_text().splitlines() if line]
        self.parents = [b for b in records if b["record_type"] == "parent"]
        self.children = [b for b in records if b["record_type"] == "child"]
        if not self.parents or not self.children:
            raise ValueError("父子块文件为空，请先构建父子块索引")
        chroma = {**config["chroma"], "collections": {"qwen": experiment["collection"]}}
        self.store = ChromaStore(
            root,
            chroma,
            "qwen",
            fingerprint("qwen", config["qwen"]),
            sha256(path.read_bytes()),
            config["qwen"]["dimensions"],
        )
        self.store.open()  # Fail before loading weights if index is missing/stale.
        import torch

        torch.set_num_threads(settings["cpu_threads"])
        self.embedder = create_embedder(
            "qwen",
            {**config["qwen"], "local_files_only": settings["qwen_local_files_only"]},
            root,
        )
        self.model = config["qwen"]["model"]

    def retrieve(self, question: str, top_k: int):
        vector = self.embedder.embed_query(question)
        return parent_hits(self.store, self.children, self.parents, vector, top_k)

    def close(self):
        self.embedder.close()


def answer_question(
    question: str,
    retriever,
    generator,
    settings: dict,
    retrieve_only=False,
    history=None,
):
    if not question.strip() or len(question) > settings["max_question_chars"]:
        raise ValueError("问题不能为空或超过 max_question_chars")
    start = time.perf_counter()
    rewrite_settings = settings.get(
        "rewrite",
        {"enabled": False, "max_history_chars": 12000, "max_history_messages": 6},
    )
    rerank_settings = {
        "enabled": False,
        "per_query_k": 15,
        "candidate_k": 20,
        "rrf_constant": 60,
        **settings.get("rerank", {}),
    }
    history = validate_history([] if history is None else history, rewrite_settings)
    rewrite_start = time.perf_counter()
    plan = {"standalone_question": question, "subquestions": [], "queries": [question]}
    rewrite_info = {"status": "disabled"}
    if rewrite_settings["enabled"] and not retrieve_only and generator is not None:
        rewrite_info = {"status": "not_needed"}
        if needs_rewrite(question, history):
            try:
                plan = plan_queries(question, history, generator, rewrite_settings)
                rewrite_info = {"status": "rewritten", **plan}
            except Exception as error:  # noqa: BLE001 -- optional rewrite falls back to the original query.
                rewrite_info = {
                    "status": "fallback_original",
                    **failure_details(error, generator),
                }
    rewrite_info["elapsed_seconds"] = time.perf_counter() - rewrite_start
    retrieval_start = time.perf_counter()
    refinement = (
        (rerank_settings["enabled"] or len(plan["queries"]) > 1)
        and not retrieve_only
        and generator is not None
    )
    if refinement:
        results = [
            (query, retriever.retrieve(query, rerank_settings["per_query_k"]))
            for query in plan["queries"]
        ]
        candidates = fuse_hits(
            results, rerank_settings["candidate_k"], rerank_settings["rrf_constant"]
        )
    else:
        candidates = retriever.retrieve(question, settings["top_k"])
    retrieval_seconds = time.perf_counter() - retrieval_start
    rerank_start = time.perf_counter()
    rerank_info = {"status": "disabled"}
    ordered = candidates
    if rerank_settings["enabled"] and refinement and candidates:
        try:
            ordered, metadata = rerank_parents(
                question,
                plan,
                candidates,
                retriever.parents,
                generator,
                rerank_settings,
            )
            rerank_info = {"status": "reranked", **metadata}
        except Exception as error:  # noqa: BLE001 -- optional rerank falls back to fusion ordering.
            rerank_info = {
                "status": "fallback_fusion",
                **failure_details(error, generator),
            }
    rerank_info["elapsed_seconds"] = time.perf_counter() - rerank_start
    hits = ordered[: settings["top_k"]]
    evidence, omitted = select_evidence(
        hits, retriever.parents, settings["max_context_bytes"]
    )
    record = {
        "question": question,
        "history": history,
        "query_plan": plan,
        "rewrite": rewrite_info,
        "rerank": rerank_info,
        "retrieval_candidates": candidates,
        "reranked_candidates": ordered,
        "collection": retriever.store.name,
        "embedding_model": retriever.model,
        "generation_model": settings["generation"]["model"],
        "retrieval_top_k": settings["top_k"],
        "context_budget_bytes": settings["max_context_bytes"],
        "retrieval_hits": hits,
        "evidence": evidence,
        "omitted_for_context_budget": omitted,
        "context_bytes": len(make_prompt("", evidence).encode("utf-8")),
        "retrieval_seconds": retrieval_seconds,
    }
    if retrieve_only:
        return {
            **record,
            "status": "retrieved",
            "elapsed_seconds": time.perf_counter() - start,
        }
    if not evidence:
        return {
            **record,
            "status": "insufficient_evidence",
            "answer": "未检索到可用的完整规则证据，或完整证据超过上下文预算。",
            "citations": [],
            "insufficient_evidence": True,
            "usage": None,
            "elapsed_seconds": time.perf_counter() - start,
        }
    generation_start = time.perf_counter()
    generation_question = question
    if history or plan["standalone_question"] != question or plan["subquestions"]:
        generation_question = json.dumps(
            {
                "latest_question": question,
                "standalone_question": plan["standalone_question"],
                "retrieval_subquestions": plan["subquestions"],
                "conversation_for_reference_resolution_only": history,
            },
            ensure_ascii=False,
        )
    record["generation_question"] = generation_question
    try:
        result = generator.generate(generation_question, evidence)
    except Exception as error:
        # Caller persists retrieval diagnostics even when generation fails.
        error.rag_record = {
            **record,
            "status": "generation_failed",
            "error_type": type(error).__name__,
            "elapsed_seconds": time.perf_counter() - start,
        }
        if hasattr(error, "rejected_generation"):
            error.rag_record["rejected_generation"] = error.rejected_generation
        raise
    return {
        **record,
        **result,
        "status": "insufficient_evidence"
        if result["insufficient_evidence"]
        else "answered",
        "generation_seconds": time.perf_counter() - generation_start,
        "elapsed_seconds": time.perf_counter() - start,
    }
