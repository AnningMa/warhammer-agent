"""Portable packages round-trip through a fresh Chroma without model inference."""

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("chromadb")

from warhammer_agent.embeddings.chroma_store import ChromaStore
from warhammer_agent.embeddings.cli import fingerprint, sha256
from warhammer_agent.embeddings.package import (
    export_package,
    import_package,
    validate_package,
)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "reports").mkdir()
    settings = {
        "input": "reports/index_blocks.jsonl",
        "output": "reports/parent_child_blocks.jsonl",
        "embedding_config": "config/embeddings.json",
        "collection": "fixture_parent_child",
    }
    config = {
        "qwen": {"model": "fixture", "dimensions": 2},
        "chroma": {
            "path": "source-chroma",
            "collections": {"qwen": settings["collection"]},
            "batch_size": 2,
            "ef_search": 100,
        },
    }
    for path, obj in [
        ("config/parent_child.json", settings),
        ("config/embeddings.json", config),
    ]:
        (tmp_path / path).write_text(json.dumps(obj))
    parents = []
    children = []
    for i in range(2):
        parent = {
            "block_id": f"parent-{i}",
            "record_type": "parent",
            "text": f"Complete rule {i}",
            "embedding_text": f"Complete rule {i}",
            "document_id": "fixture",
            "source_hash": "fixture-source",
            "page_number": i + 1,
            "page_numbers": [i + 1],
            "section_title": f"Rule {i}",
            "review_status": "reviewed_correction",
            "source_segments": [{"page_number": i + 1}],
        }
        parents.append(parent)
        children.append(
            {
                **parent,
                "block_id": f"child-{i}",
                "record_type": "child",
                "parent_block_id": parent["block_id"],
                "parent_text_sha256": sha256(parent["text"].encode()),
            }
        )
    (tmp_path / settings["input"]).write_text(
        "".join(json.dumps(p) + "\n" for p in parents)
    )
    corpus = "".join(json.dumps(r) + "\n" for r in [*parents, *children]).encode()
    (tmp_path / settings["output"]).write_bytes(corpus)
    info = {
        "provider": "qwen",
        "model": "fixture",
        "fingerprint": fingerprint("qwen", config["qwen"]),
        "input_sha256": sha256(corpus),
        "dimensions": 2,
    }
    store = ChromaStore(
        tmp_path, config["chroma"], "qwen", info["fingerprint"], info["input_sha256"], 2
    )
    stored = [
        {
            **c,
            "parent_record": {
                k: v for k, v in parents[i].items() if k != "record_type"
            },
        }
        for i, c in enumerate(children)
    ]
    matrix = np.eye(2, dtype=np.float32)
    store.write(stored, matrix, info)
    archive = tmp_path / "release.zip"
    return tmp_path, Path("config/parent_child.json"), store, stored, matrix, archive


def rewrite_zip(path, change, *, update_hashes=False):
    with zipfile.ZipFile(path) as z:
        content = {name: z.read(name) for name in z.namelist()}
    change(content)
    if update_hashes:
        manifest = json.loads(content["manifest.json"])
        manifest["files"] = {
            name: sha256(value)
            for name, value in content.items()
            if name != "manifest.json"
        }
        content["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, value in content.items():
            z.writestr(name, value)


def test_export_validate_import_and_repeat_preserve_exact_records(project):
    root, config, original, stored, matrix, archive = project
    exported = export_package(root, config, archive)
    checksum = Path(exported["checksum"]).read_text().split()[0]
    assert checksum == sha256(archive.read_bytes())
    destination = root / "fresh-chroma"
    validate_package(root, config, archive, destination)
    assert not destination.exists()  # Validate-only does not initialize Chroma.
    imported = import_package(root, config, archive, destination)
    import_package(root, config, archive, destination)
    _, store, _, _, _ = validate_package(root, config, archive, destination)
    assert store.open().count() == len(stored)
    assert store.get_blocks() == stored
    assert imported["collection"] == original.name
    for i in range(2):
        assert store.query(matrix[i], 1)[0]["block_id"] == f"child-{i}"
    assert original.open().count() == 2
    with pytest.raises(FileExistsError):
        export_package(root, config, archive)


def test_tampered_package_rejected_before_any_chroma_writes(project):
    root, config, _, _, _, archive = project
    export_package(root, config, archive)
    rewrite_zip(archive, lambda c: c.update({"vectors.npz": b"tampered"}))
    destination = root / "must-not-exist"
    with pytest.raises(ValueError, match="checksum"):
        import_package(root, config, archive, destination)
    assert not destination.exists()


def test_corpus_or_model_mismatch_rejected(project):
    root, config, _, _, _, archive = project
    export_package(root, config, archive)
    source = root / "reports/index_blocks.jsonl"
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="corpus/source"):
        validate_package(root, config, archive)
    source.write_bytes(source.read_bytes()[:-1])
    cfg = root / "config/embeddings.json"
    changed = json.loads(cfg.read_text())
    changed["qwen"]["model"] = "different-model"
    cfg.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="configuration"):
        validate_package(root, config, archive)


@pytest.mark.parametrize("invalid", ["order", "nan"])
def test_invalid_vector_payload_rejected_even_with_matching_file_hash(project, invalid):
    root, config, _, _, matrix, archive = project
    export_package(root, config, archive)

    def change(content):
        ids = np.asarray(["child-0", "child-1"])
        values = matrix.copy()
        if invalid == "order":
            ids = ids[::-1]
        else:
            values[0, 0] = np.nan
        stream = io.BytesIO()
        np.savez_compressed(stream, ids=ids, vectors=values)
        content["vectors.npz"] = stream.getvalue()

    rewrite_zip(archive, change, update_hashes=True)
    with pytest.raises(ValueError, match="IDs/order|non-finite"):
        validate_package(root, config, archive)


def test_path_traversal_members_rejected_without_extraction(project):
    root, config, _, _, _, archive = project
    export_package(root, config, archive)
    rewrite_zip(archive, lambda c: c.update({"../unexpected.txt": b"no"}))
    with pytest.raises(ValueError, match="archive members"):
        validate_package(root, config, archive)
    assert not (root.parent / "unexpected.txt").exists()
