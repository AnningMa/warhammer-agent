"""Local, versioned Chroma collections with explicit precomputed embeddings."""

import json
from pathlib import Path

import numpy as np

from .providers import normalized_vectors


class ChromaStore:
    def __init__(
        self,
        root: Path,
        config: dict,
        provider: str,
        signature: str,
        source_hash: str,
        dimensions: int,
        smoke: bool = False,
    ):
        self.path = root / config["path"]
        base = config["collections"][provider] + ("_smoke" if smoke else "")
        self.name = f"{base}_{source_hash[:12]}_{signature[:12]}"
        self.signature, self.source_hash, self.dimensions = (
            signature,
            source_hash,
            dimensions,
        )
        self.batch_size = config["batch_size"]
        self.ef_search = config["ef_search"]
        if self.batch_size < 1 or self.ef_search < 1:
            raise ValueError("Chroma batch_size and ef_search must be positive")
        self._client = None
        self._collection = None

    def client(self):
        if self._client is None:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=str(self.path), settings=Settings(anonymized_telemetry=False)
            )
        return self._client

    def open(self):
        if self._collection is None:
            if not self.path.exists():
                raise FileNotFoundError(
                    "Chroma index does not exist; import NPZ or build it first"
                )
            from chromadb.errors import NotFoundError

            try:
                collection = self.client().get_collection(
                    self.name, embedding_function=None
                )
            except NotFoundError as error:
                raise ValueError(
                    "No Chroma collection matches this corpus/model; import NPZ or rebuild"
                ) from error
            metadata = collection.metadata or {}
            if (
                metadata.get("fingerprint") != self.signature
                or metadata.get("input_sha256") != self.source_hash
                or metadata.get("dimensions") != self.dimensions
                or metadata.get("status") != "ready"
                or metadata.get("block_count") != collection.count()
            ):
                raise ValueError(
                    "Chroma collection is incomplete or incompatible; import NPZ or rebuild"
                )
            self._collection = collection
        return self._collection

    @staticmethod
    def record_metadata(block: dict, position: int) -> dict:
        # Scalar filter fields work across Chroma 1.x versions; nested audit
        # and source records are losslessly preserved in block_json.
        metadata = {
            "position": position,
            "document_id": block["document_id"],
            "source_hash": block["source_hash"],
            "page_number": block["page_number"],
            "page_numbers_json": json.dumps(block["page_numbers"]),
            "section_title": block["section_title"] or "",
            "review_status": block["review_status"],
            "block_json": json.dumps(block, ensure_ascii=False),
        }
        if block.get("parent_rule_id"):
            metadata["parent_rule_id"] = block["parent_rule_id"]
        if block.get("embedding_context", {}).get("terrain"):
            metadata["terrain"] = block["embedding_context"]["terrain"]
        return metadata

    def write(self, blocks: list[dict], vectors: np.ndarray, info: dict) -> None:
        if not blocks or len({b["block_id"] for b in blocks}) != len(blocks):
            raise ValueError("Chroma requires nonempty records with unique IDs")
        if (
            info["fingerprint"] != self.signature
            or info["input_sha256"] != self.source_hash
            or info["dimensions"] != self.dimensions
        ):
            raise ValueError(
                "Embedding information does not match the Chroma collection"
            )
        vectors = normalized_vectors(vectors, len(blocks), self.dimensions)
        records = [self.record_metadata(b, i) for i, b in enumerate(blocks)]
        metadata = {
            "fingerprint": self.signature,
            "input_sha256": self.source_hash,
            "dimensions": self.dimensions,
            "block_count": len(blocks),
            "provider": info["provider"],
            "model": info["model"],
            "status": "building",
        }
        collection = self.client().get_or_create_collection(
            name=self.name,
            embedding_function=None,
            metadata=metadata,
            configuration={"hnsw": {"space": "cosine", "ef_search": self.ef_search}},
        )
        existing = collection.metadata or {}
        if any(
            existing.get(k) != metadata[k]
            for k in ["fingerprint", "input_sha256", "dimensions"]
        ):
            raise ValueError(
                "Chroma collection name collision or incompatible existing collection"
            )
        if collection.configuration["hnsw"]["space"] != "cosine":
            raise ValueError("Chroma collection must use cosine distance")
        collection.modify(metadata=metadata)
        self._collection = None
        for start in range(0, len(blocks), self.batch_size):
            end = start + self.batch_size
            collection.upsert(
                ids=[b["block_id"] for b in blocks[start:end]],
                embeddings=vectors[start:end].tolist(),
                documents=[b["embedding_text"] for b in blocks[start:end]],
                metadatas=records[start:end],
            )
        # Removing unexpected records makes repeated imports exact and avoids
        # stale results when a partial same-version import is replaced.
        wanted = {b["block_id"] for b in blocks}
        extras = [i for i in collection.get(include=[])["ids"] if i not in wanted]
        if extras:
            collection.delete(ids=extras)
        if collection.count() != len(blocks):
            raise ValueError("Chroma import count mismatch")
        collection.modify(metadata={**metadata, "status": "ready"})
        self._collection = collection

    def get_blocks(self, ids: list[str] | None = None) -> list[dict]:
        collection = self.open()
        data = (
            collection.get(ids=ids, include=["metadatas"])
            if ids is not None
            else collection.get(include=["metadatas"])
        )
        pairs = []
        for identity, metadata in zip(data["ids"], data["metadatas"]):
            block = json.loads(metadata["block_json"])
            if block["block_id"] != identity:
                raise ValueError("Chroma record ID and source payload disagree")
            pairs.append((metadata["position"], block))
        if ids is not None and {b["block_id"] for _, b in pairs} != set(ids):
            raise ValueError("Chroma evidence record is missing")
        return [b for _, b in sorted(pairs, key=lambda pair: pair[0])]

    def query(
        self, vector: np.ndarray, top_k: int, where: dict | None = None
    ) -> list[dict]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        query = normalized_vectors(
            np.asarray(vector).reshape(1, -1), 1, self.dimensions
        )[0]
        result = self.open().query(
            query_embeddings=[query.tolist()],
            n_results=min(top_k, self.open().count()),
            where=where,
            include=["distances", "metadatas"],
        )
        hits = []
        for identity, distance, metadata in zip(
            result["ids"][0], result["distances"][0], result["metadatas"][0]
        ):
            block = json.loads(metadata["block_json"])
            hits.append(
                {
                    "block_id": identity,
                    "page_numbers": block["page_numbers"],
                    "section_title": block["section_title"],
                    "score": 1.0 - float(distance),
                    "_position": metadata["position"],
                }
            )
        hits.sort(key=lambda h: (-h["score"], h["_position"]))
        for hit in hits:
            hit.pop("_position")
        return hits

    def evidence_blocks(self, hits: list[dict]) -> list[dict]:
        if not hits:
            return []
        blocks = self.get_blocks([h["block_id"] for h in hits])
        known = {b["block_id"] for b in blocks}
        parents = {
            b["parent_rule_id"] for b in blocks if b.get("parent_rule_id")
        } - known
        if parents:
            blocks.extend(self.get_blocks(sorted(parents)))
        return blocks
