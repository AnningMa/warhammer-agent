import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("chromadb")

from warhammer_agent.embeddings.chroma_store import ChromaStore
from warhammer_agent.embeddings.cli import evaluate, expand_evidence


def config():
    return {
        "path": "db",
        "collections": {"qwen": "test_rules_qwen", "gemini": "test_rules_gemini"},
        "batch_size": 1,
        "ef_search": 200,
    }


def blocks():
    return [
        {
            "block_id": "main",
            "document_id": "rules",
            "source_hash": "pdf",
            "page_number": 6,
            "page_numbers": [6, 7],
            "section_title": "UNIT COHERENCY",
            "review_status": "partially_reviewed",
            "text": "Within 5 inches vertically.",
            "embedding_text": "Rule: coherency. Within 5 inches vertically.",
            "source_segments": [
                {"page_number": 6, "metadata": {"nested": True}},
                {"page_number": 7},
            ],
        },
        {
            "block_id": "example",
            "document_id": "rules",
            "source_hash": "pdf",
            "page_number": 6,
            "page_numbers": [6],
            "section_title": "Example",
            "review_status": "reviewed_correction",
            "text": "Example distances.",
            "embedding_text": "Example distances.",
            "parent_rule_id": "main",
        },
        {
            "block_id": "woods",
            "document_id": "rules",
            "source_hash": "pdf",
            "page_number": 47,
            "page_numbers": [47],
            "section_title": "BENEFIT OF COVER",
            "review_status": "unreviewed",
            "text": "Cover condition.",
            "embedding_text": "Terrain: WOODS\nCover condition.",
            "embedding_context": {"terrain": "WOODS"},
        },
    ]


def populate(tmp_path):
    store = ChromaStore(tmp_path, config(), "qwen", "signature", "source", 2)
    matrix = np.array([[0, 1], [1, 0], [-1, 0]], dtype=np.float32)
    info = {
        "fingerprint": "signature",
        "input_sha256": "source",
        "dimensions": 2,
        "provider": "qwen",
        "model": "fixture",
    }
    store.write(blocks(), matrix, info)
    return store, matrix, info


def test_persistent_roundtrip_nested_sources_cosine_and_parent_expansion(tmp_path):
    store, matrix, _ = populate(tmp_path)
    reopened = ChromaStore(tmp_path, config(), "qwen", "signature", "source", 2)
    assert reopened.get_blocks() == blocks()
    assert reopened.open().configuration["hnsw"]["space"] == "cosine"
    saved = reopened.open().get(
        ids=["main", "example"], include=["embeddings", "documents"]
    )
    by_id = dict(zip(saved["ids"], saved["documents"]))
    assert by_id["main"] == blocks()[0]["embedding_text"]
    vector_by_id = dict(zip(saved["ids"], saved["embeddings"]))
    np.testing.assert_allclose(vector_by_id["main"], matrix[0], atol=1e-6)
    np.testing.assert_allclose(vector_by_id["example"], matrix[1], atol=1e-6)
    hits = reopened.query(np.array([1, 0]), 1)
    assert hits[0]["block_id"] == "example"
    assert hits[0]["score"] == pytest.approx(1)
    evidence = expand_evidence(hits, reopened.evidence_blocks(hits))
    assert evidence[0]["related_evidence"][0]["page_numbers"] == [6, 7]
    assert (
        evidence[0]["related_evidence"][0]["source_segments"]
        == blocks()[0]["source_segments"]
    )
    assert store.path.is_dir()
    assert (store.path / "chroma.sqlite3").is_file()


def test_repeat_import_removes_extras_and_does_not_duplicate(tmp_path):
    store, matrix, info = populate(tmp_path)
    store.open().upsert(
        ids=["extra"],
        embeddings=[[0.5, 0.5]],
        documents=["Extra"],
        metadatas=[{"position": 99, "block_json": "{}"}],
    )
    store.write(blocks(), matrix, info)
    assert store.open().count() == 3
    assert store.get_blocks() == blocks()


def test_filtering_and_independent_versions(tmp_path):
    store, _, _ = populate(tmp_path)
    hits = store.query(np.array([1, 0]), 5, where={"terrain": "WOODS"})
    assert [h["block_id"] for h in hits] == ["woods"]
    with pytest.raises(ValueError, match="No Chroma collection"):
        ChromaStore(tmp_path, config(), "qwen", "newmodel", "source", 2).open()
    with pytest.raises(ValueError, match="No Chroma collection"):
        ChromaStore(tmp_path, config(), "qwen", "signature", "newsource", 2).open()
    with pytest.raises(ValueError, match="No Chroma collection"):
        ChromaStore(tmp_path, config(), "gemini", "signature", "source", 2).open()
    with pytest.raises(ValueError, match="missing"):
        store.get_blocks(["missing"])


def test_incomplete_import_is_not_readable(tmp_path):
    store, _, _ = populate(tmp_path)
    store.open().modify(metadata={**store.open().metadata, "status": "building"})
    with pytest.raises(ValueError, match="incomplete"):
        ChromaStore(tmp_path, config(), "qwen", "signature", "source", 2).open()


def test_chroma_evaluation_uses_database_ranking(tmp_path):
    store, _, _ = populate(tmp_path)
    fake = type("Fake", (), {"embed_query": lambda self, query: np.array([1, 0])})()
    result = evaluate(
        [
            {
                "id": "main",
                "section_title": "UNIT COHERENCY",
                "page_number": 6,
                "question": "Distance?",
            }
        ],
        store.get_blocks(),
        None,
        fake,
        1,
        search=store.query,
    )
    assert result["hit_rate"] == result["mrr_at_k"] == 0
    assert result["evidence_hit_rate"] == 1


def test_cli_import_uses_saved_vectors_without_loading_embedding_model(
    tmp_path, monkeypatch
):
    from warhammer_agent.embeddings import cli

    root = Path(__file__).resolve().parents[2]
    settings = json.loads((root / "config/embeddings.json").read_text())["qwen"]
    signature = cli.fingerprint("qwen", settings)
    records = blocks()
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps(b) + "\n" for b in records))
    source_hash = cli.sha256(source.read_bytes())
    dimensions = settings["dimensions"]
    matrix = np.zeros((3, dimensions), dtype=np.float32)
    matrix[:, :2] = np.array([[0, 1], [1, 0], [-1, 0]])
    npz = tmp_path / "backup/qwen.npz"
    cli.save_index(
        npz,
        records,
        matrix,
        {
            "fingerprint": signature,
            "input_sha256": source_hash,
            "dimensions": dimensions,
        },
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "backend": "chroma",
                "input": "input.jsonl",
                "output_dir": "backup",
                "qwen": settings,
                "chroma": config(),
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "embed_rules",
            "--provider",
            "qwen",
            "--config",
            str(config_path),
            "--import-npz",
        ],
    )

    def forbidden(*args):
        raise AssertionError("Import must not load an embedding model")

    monkeypatch.setattr(cli, "create_embedder", forbidden)
    backup_before = npz.read_bytes()
    cli.main()
    assert npz.read_bytes() == backup_before
    assert (
        ChromaStore(
            tmp_path, config(), "qwen", signature, source_hash, dimensions
        ).get_blocks()
        == records
    )
