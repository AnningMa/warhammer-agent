"""Experimental complete-rule parents with paragraph-based retrieval children."""

import argparse
import copy
import json
import re
from itertools import pairwise
from pathlib import Path

import numpy as np

from .chroma_store import ChromaStore
from .cli import evaluate, expand_evidence, fingerprint, load_blocks, load_index, sha256
from .providers import create_embedder


def build_records(parents, tokenizer, threshold=512, target=384):
    if not 0 < target <= threshold:
        raise ValueError("Require 0 < target_tokens <= split_above_tokens")

    def count(text):
        return len(tokenizer.encode(text, add_special_tokens=True, truncation=False))

    records, children = [], []
    for parent in parents:
        records.append({**parent, "record_type": "parent"})
        text = parent["text"]
        split = count(parent["embedding_text"]) > threshold
        prefix = ""
        if split:
            context = parent.get("embedding_context", {})
            if context.get("terrain"):
                prefix += f"Terrain: {context['terrain']}\n"
            prefix += "Rule: " + " > ".join(parent["section_path"]) + "\n\n"
        # Paragraph boundaries retain entire Markdown tables and list paragraphs.
        units = [
            (m.start(), m.end()) for m in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text)
        ]
        if split:
            refined = []
            for a, b in units:
                paragraph = text[a:b]
                # Keep tables and list groups atomic. Long prose can be
                # divided at sentence boundaries, never at arbitrary tokens.
                if count(prefix + paragraph) > target and not re.search(
                    r"(?m)^\s*(?:\||[-*+]\s|\d+[.)]\s)", paragraph
                ):
                    cuts = (
                        [a]
                        + [
                            a + m.end()
                            for m in re.finditer(r"[.!?]\s+(?=[A-Z])", paragraph)
                        ]
                        + [b]
                    )
                    refined.extend(pairwise(cuts))
                else:
                    refined.append((a, b))
            units = refined
        spans = []
        if split:
            start, end = units[0]
            for next_start, next_end in units[1:]:
                heading_only = bool(re.fullmatch(r"\s*#+[^\n]*\s*", text[start:end]))
                if heading_only or count(prefix + text[start:next_end]) <= target:
                    end = next_end
                else:
                    spans.append((start, end))
                    start, end = next_start, next_end
            spans.append((start, end))
        else:
            spans = [(0, len(text))]
        for i, (start, end) in enumerate(spans):
            child = copy.deepcopy(parent)
            child.pop("corpus_audit", None)
            child["block_id"] = parent["block_id"] + f".child_{i + 1:03d}"
            child["record_type"] = "child"
            child["parent_block_id"] = parent["block_id"]
            child["parent_text_sha256"] = sha256(text.encode())
            child["parent_text_span"] = {
                "start": start,
                "end": end,
                "unit": "unicode_character",
            }
            child["text"] = text[start:end]
            child["text_sha256"] = sha256(child["text"].encode())
            child["embedding_text"] = (
                prefix + child["text"] if split else parent["embedding_text"]
            )
            child["token_count"] = count(child["embedding_text"])
            child["atomic_over_target"] = split and child["token_count"] > target
            sources = []
            for segment in parent.get("source_segments", []):
                a, b = segment["text_span"]["start"], segment["text_span"]["end"]
                if max(a, start) < min(b, end):
                    selected = copy.deepcopy(segment)
                    selected["parent_text_span"] = selected.pop("text_span")
                    selected["text_span"] = {
                        "start": max(a, start) - start,
                        "end": min(b, end) - start,
                        "unit": "unicode_character",
                    }
                    selected["source_mapping_granularity"] = "original_source_segment"
                    sources.append(selected)
            child["source_segments"] = sources
            child["page_numbers"] = (
                sorted({s["page_number"] for s in sources}) or parent["page_numbers"]
            )
            child["page_number"] = child["page_numbers"][0]
            children.append(child)
            records.append(child)
    return records, children


def parent_hits(store, children, parents, vector, top_k):
    """Rank unique parents by their best child; expand candidate pool as needed."""
    by_child = {b["block_id"]: b for b in children}
    by_parent = {b["block_id"]: b for b in parents}
    candidates = min(len(children), max(top_k * 4, 20))
    while True:
        result, seen = [], set()
        for hit in store.query(vector, candidates):
            parent_id = by_child[hit["block_id"]]["parent_block_id"]
            if parent_id in seen:
                continue
            seen.add(parent_id)
            parent = by_parent[parent_id]
            result.append(
                {
                    **hit,
                    "retrieval_child_id": hit["block_id"],
                    "block_id": parent_id,
                    "page_numbers": parent["page_numbers"],
                    "section_title": parent["section_title"],
                }
            )
            if len(result) == top_k:
                return result
        if candidates == len(children):
            return result
        candidates = min(len(children), candidates * 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/parent_child.json"))
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--query")
    action.add_argument("--evaluate", action="store_true")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("top-k must be positive")
    root = Path.cwd()
    settings = json.loads(args.config.read_text())
    config = json.loads((root / settings["embedding_config"]).read_text())
    # Keep model settings/fingerprint identical to the baseline; offline mode
    # controls the loader through the environment, not vector compatibility.
    import torch

    torch.set_num_threads(settings["cpu_threads"])
    embedder = create_embedder("qwen", config["qwen"], root)
    try:
        path = root / settings["output"]
        if args.query or args.evaluate:
            records = [
                json.loads(line) for line in path.read_text().splitlines() if line
            ]
            parents = [b for b in records if b["record_type"] == "parent"]
            children = [b for b in records if b["record_type"] == "child"]
        else:
            parents = load_blocks(root / settings["input"])
            records, children = build_records(
                parents,
                embedder.model.tokenizer,
                settings["split_above_tokens"],
                settings["target_tokens"],
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in records),
                encoding="utf-8",
            )
            temporary.replace(path)
        signature = fingerprint("qwen", config["qwen"])
        source_hash = sha256(path.read_bytes())
        chroma = {**config["chroma"], "collections": {"qwen": settings["collection"]}}
        store = ChromaStore(
            root, chroma, "qwen", signature, source_hash, config["qwen"]["dimensions"]
        )
        search = lambda vector, k: parent_hits(store, children, parents, vector, k)
        if args.query:
            hits = search(embedder.embed_query(args.query), args.top_k)
            output = {
                "collection": store.name,
                "results": expand_evidence(hits, parents),
            }
            for item in output["results"]:
                parent = next(b for b in parents if b["block_id"] == item["block_id"])
                item["source_segments"] = parent["source_segments"]
        elif args.evaluate:
            cases = json.loads((root / "tests/eval_cases/retrieval.json").read_text())
            output = evaluate(cases, parents, None, embedder, args.top_k, search=search)
            output.update(
                collection=store.name,
                ranking_unit="unique_parent",
                strategy="parent_child",
            )
        else:
            reusable = {}
            baseline = root / config["output_dir"] / "qwen.npz"
            if baseline.exists():
                old_blocks, old_vectors = load_index(
                    baseline, signature, sha256((root / settings["input"]).read_bytes())
                )
                reusable = {
                    b["embedding_text"]: v for b, v in zip(old_blocks, old_vectors)
                }
            pending = [b for b in children if b["embedding_text"] not in reusable]
            print(
                json.dumps(
                    {
                        "parents": len(parents),
                        "children": len(children),
                        "reuse_vectors": len(children) - len(pending),
                        "new_embeddings": len(pending),
                    }
                ),
                flush=True,
            )
            for start in range(0, len(pending), config["qwen"]["batch_size"]):
                batch = pending[start : start + config["qwen"]["batch_size"]]
                vectors = embedder.embed_documents(batch)
                reusable.update(
                    {b["embedding_text"]: v for b, v in zip(batch, vectors)}
                )
                print(
                    f"Embedded {min(start + len(batch), len(pending))}/{len(pending)}",
                    flush=True,
                )
            vectors = np.stack([reusable[b["embedding_text"]] for b in children])
            # Full parent payload lives in Chroma metadata, too; only children
            # have vectors. No fabricated parent embeddings are introduced.
            by_parent = {b["block_id"]: b for b in parents}
            stored = [
                {**b, "parent_record": by_parent[b["parent_block_id"]]}
                for b in children
            ]
            info = {
                "fingerprint": signature,
                "input_sha256": source_hash,
                "dimensions": config["qwen"]["dimensions"],
                "provider": "qwen",
                "model": config["qwen"]["model"],
            }
            store.write(stored, vectors, info)
            output = {
                **info,
                "collection": store.name,
                "parents": len(parents),
                "children": len(children),
                "split_parents": sum(
                    sum(c["parent_block_id"] == p["block_id"] for c in children) > 1
                    for p in parents
                ),
                "atomic_over_target": sum(c["atomic_over_target"] for c in children),
            }
        report = (
            root
            / "storage/parent_child"
            / (
                "evaluation.json"
                if args.evaluate
                else "query.json"
                if args.query
                else "build.json"
            )
        )
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        embedder.close()
