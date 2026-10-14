"""Embed the existing title blocks or compare retrieval using one saved index."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from .providers import (
    create_embedder,
    gemini_document,
    normalized_vectors,
    validate_settings,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_blocks(path: Path) -> list[dict]:
    blocks = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not blocks:
        raise ValueError("No blocks found")
    ids = set()
    for block in blocks:
        identity = block["block_id"]
        if identity in ids or not block["embedding_text"].strip():
            raise ValueError("Duplicate block ID or blank embedding_text")
        ids.add(identity)
    return blocks


def fingerprint(provider: str, settings: dict) -> str:
    return sha256(
        json.dumps(
            {"provider": provider, "settings": settings, "format_version": 1},
            sort_keys=True,
        ).encode()
    )


def save_index(path: Path, blocks: list[dict], vectors: np.ndarray, info: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(
                stream,
                vectors=vectors,
                blocks=np.array([json.dumps(b, ensure_ascii=False) for b in blocks]),
                info=np.array(json.dumps(info, ensure_ascii=False)),
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_index(path: Path, expected_fingerprint: str, source_hash: str) -> tuple:
    with np.load(path, allow_pickle=False) as data:
        info = json.loads(str(data["info"]))
        if (
            info["fingerprint"] != expected_fingerprint
            or info["input_sha256"] != source_hash
        ):
            raise ValueError(
                "Embedding configuration or source changed; rebuild this provider index"
            )
        blocks = [json.loads(str(b)) for b in data["blocks"]]
        vectors = normalized_vectors(data["vectors"], len(blocks), info["dimensions"])
    return blocks, vectors


def rank(
    blocks: list[dict], vectors: np.ndarray, query: np.ndarray, top_k: int
) -> list[dict]:
    scores = vectors @ query
    order = np.argsort(-scores, kind="stable")[:top_k]
    return [
        {
            "block_id": blocks[i]["block_id"],
            "page_numbers": blocks[i]["page_numbers"],
            "section_title": blocks[i]["section_title"],
            "score": float(scores[i]),
        }
        for i in order
    ]


def evaluate(
    cases: list[dict],
    blocks: list[dict],
    vectors: np.ndarray | None,
    embedder,
    top_k: int,
    search=None,
) -> dict:
    if not cases:
        raise ValueError("Evaluation cases cannot be empty")
    outcomes = []
    for case in cases:
        relevant = [
            b
            for b in blocks
            if b["section_title"] == case["section_title"]
            and case["page_number"] in b["page_numbers"]
        ]
        if len(relevant) != 1:
            raise ValueError(f"Evaluation target is absent or ambiguous: {case['id']}")
        target = relevant[0]["block_id"]
        query = embedder.embed_query(case["question"])
        hits = search(query, top_k) if search else rank(blocks, vectors, query, top_k)
        evidence = expand_evidence(hits, blocks)
        evidence_ids = {h["block_id"] for h in evidence}
        evidence_ids.update(
            p["block_id"] for h in evidence for p in h["related_evidence"]
        )
        positions = [i + 1 for i, hit in enumerate(hits) if hit["block_id"] == target]
        position = positions[0] if positions else None
        outcomes.append(
            {
                "id": case["id"],
                "rank": position,
                "reciprocal_rank": 1 / position if position else 0,
                "hits": hits,
                "evidence_target_covered": target in evidence_ids,
            }
        )
    return {
        "cases": len(cases),
        "top_k": top_k,
        "hit_rate": sum(o["rank"] is not None for o in outcomes) / len(cases),
        "mrr_at_k": sum(o["reciprocal_rank"] for o in outcomes) / len(cases),
        "evidence_hit_rate": sum(o["evidence_target_covered"] for o in outcomes)
        / len(cases),
        "results": outcomes,
    }


def expand_evidence(hits: list[dict], blocks: list[dict]) -> list[dict]:
    """Supplement examples with main rules without changing vector rankings."""
    by_id = {b["block_id"]: b for b in blocks}
    retrieved_ids = {h["block_id"] for h in hits}
    represented = set(retrieved_ids)
    result = []
    for hit in hits:
        block = by_id[hit["block_id"]]
        item = {
            **hit,
            "text": block["text"],
            "review_status": block.get("review_status"),
            "embedding_context": block.get("embedding_context"),
            "related_evidence": [],
        }
        parent_id = block.get("parent_rule_id")
        if parent_id:
            if parent_id not in by_id:
                raise ValueError(
                    "Example parent is missing from this index; build the full corpus"
                )
            item["parent_rule_id"] = parent_id
            item["parent_rule_in_results"] = parent_id in retrieved_ids
            if parent_id not in represented:
                parent = by_id[parent_id]
                item["related_evidence"].append(
                    {
                        "block_id": parent_id,
                        "section_title": parent["section_title"],
                        "page_numbers": parent["page_numbers"],
                        "text": parent["text"],
                        "review_status": parent.get("review_status"),
                        "relationship": "parent_rule",
                        "source_segments": parent.get("source_segments", []),
                        "expanded_from": block["block_id"],
                    }
                )
                represented.add(parent_id)
        result.append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["gemini", "qwen"], required=True)
    parser.add_argument("--config", type=Path, default=Path("config/embeddings.json"))
    parser.add_argument(
        "--backend", choices=["chroma", "npz"], help="Defaults to config.backend"
    )
    parser.add_argument(
        "--limit", type=int, help="Build only the first N blocks as a smoke test"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="No API requests or model downloads"
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--query", help="Search an already-built provider index")
    action.add_argument(
        "--evaluate",
        action="store_true",
        help="Evaluate an already-built provider index",
    )
    action.add_argument(
        "--import-npz",
        action="store_true",
        help="Import saved vectors into Chroma without re-embedding",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--terrain", help="Filter Chroma queries by an exact terrain name, e.g. WOODS"
    )
    args = parser.parse_args()
    if args.top_k < 1 or (args.limit is not None and args.limit < 1):
        parser.error("top-k and limit must be positive")
    if args.limit and (args.query or args.evaluate or args.import_npz):
        parser.error("limit applies only when building an index")
    if args.terrain and not args.query:
        parser.error("terrain applies only to a query")
    root = Path.cwd()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        backend = args.backend or config.get("backend", "npz")
        if backend not in {"chroma", "npz"}:
            raise ValueError("Unknown storage backend")
        if backend != "chroma" and (args.import_npz or args.terrain):
            raise ValueError("import-npz and terrain require the Chroma backend")
        settings = config[args.provider]
        validate_settings(args.provider, settings)
        source = root / config["input"]
        blocks = load_blocks(source)
        input_hash = sha256(source.read_bytes())
        suffix = "-smoke" if args.limit else ""
        path = root / config["output_dir"] / (args.provider + suffix + ".npz")
        signature = fingerprint(args.provider, settings)
        store = None
        vectors = None
        if args.query is not None and not args.query.strip():
            raise ValueError("query cannot be blank")
        if args.import_npz:
            imported, vectors = load_index(path, signature, input_hash)
            if imported != blocks:
                raise ValueError(
                    "NPZ records do not match the complete current corpus; rebuild NPZ first"
                )
        if backend == "chroma":
            from .chroma_store import ChromaStore

            store = ChromaStore(
                root,
                config["chroma"],
                args.provider,
                signature,
                input_hash,
                settings["dimensions"],
                smoke=bool(args.limit),
            )
        if args.query or args.evaluate:
            if store:
                store.open()
                if args.evaluate:
                    blocks = store.get_blocks()
            else:
                blocks, vectors = load_index(path, signature, input_hash)
        elif args.limit:
            blocks = blocks[: args.limit]
        if args.provider == "gemini" and any(
            len(gemini_document(b).encode()) > settings["max_input_bytes"]
            for b in blocks
        ):
            raise ValueError(
                "A block exceeds the Gemini byte guard; split it before embedding"
            )
        summary = {
            "provider": args.provider,
            "backend": backend,
            "model": settings["model"],
            "dimensions": settings["dimensions"],
            "blocks": len(blocks),
            "input_characters": sum(len(b["embedding_text"]) for b in blocks),
            "output": str(store.path.relative_to(root))
            if store
            else str(path.relative_to(root)),
        }
        if store:
            summary["collection"] = store.name
        if args.dry_run:
            print(
                json.dumps(
                    {
                        **summary,
                        "network_used": False,
                        "document_reembedding": not (
                            args.import_npz or args.query or args.evaluate
                        ),
                        "qwen_token_check": "Runs after loading the local tokenizer",
                    },
                    ensure_ascii=False,
                )
            )
            return
        info = {
            "provider": args.provider,
            "model": settings["model"],
            "dimensions": settings["dimensions"],
            "fingerprint": signature,
            "input_sha256": input_hash,
            "block_count": len(blocks),
            "baseline": "one_rule_block_per_vector",
            "normalized": True,
        }
        if args.import_npz:
            store.write(blocks, vectors, info)
            print(
                json.dumps(
                    {**summary, "document_reembedding": False},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        embedder = create_embedder(args.provider, settings, root)
        try:
            if args.query:
                query = embedder.embed_query(args.query)
                if store:
                    hits = store.query(
                        query,
                        args.top_k,
                        where={"terrain": args.terrain} if args.terrain else None,
                    )
                    evidence_blocks = store.evidence_blocks(hits)
                else:
                    hits = rank(blocks, vectors, query, args.top_k)
                    evidence_blocks = blocks
                result = expand_evidence(hits, evidence_blocks)
            elif args.evaluate:
                cases = json.loads(
                    (root / "tests/eval_cases/retrieval.json").read_text(
                        encoding="utf-8"
                    )
                )
                result = evaluate(
                    cases,
                    blocks,
                    vectors,
                    embedder,
                    args.top_k,
                    search=store.query if store else None,
                )
                result.update(
                    provider=args.provider,
                    backend=backend,
                    model=settings["model"],
                    dimensions=settings["dimensions"],
                    input_sha256=input_hash,
                )
            else:
                vectors = embedder.embed_documents(blocks)
                # NPZ remains the exact-search baseline and portable backup.
                save_index(path, blocks, vectors, info)
                if store:
                    store.write(blocks, vectors, info)
                result = {**summary, "npz_backup": str(path.relative_to(root))}
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            embedder.close()
    except (ValueError, KeyError, FileNotFoundError, ImportError) as error:
        parser.exit(2, f"Embedding setup error: {error}\n")
    except Exception as error:  # noqa: BLE001 -- sanitize third-party API failures
        parser.exit(
            1,
            f"Embedding provider/storage failed ({type(error).__name__}); check connectivity, quota, model access and index configuration.\n",
        )
