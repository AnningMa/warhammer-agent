"""Portable parent-child index archives, independent of Chroma's disk layout."""

import argparse
import io
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .chroma_store import ChromaStore
from .cli import fingerprint, sha256
from .providers import normalized_vectors

FORMAT_VERSION = 1
MAX_UNPACKED_BYTES = 64 * 1024 * 1024
MEMBERS = {"manifest.json", "vectors.npz", "parent_child_blocks.jsonl", "README.txt"}


def _context(root, config_path, chroma_path=None):
    settings = json.loads((root / config_path).read_text())
    config = json.loads((root / settings["embedding_config"]).read_text())
    corpus = (root / settings["output"]).read_bytes()
    records = [json.loads(line) for line in corpus.decode().splitlines() if line]
    parents = [r for r in records if r["record_type"] == "parent"]
    children = [r for r in records if r["record_type"] == "child"]
    if (
        not parents
        or not children
        or len({r["block_id"] for r in records}) != len(records)
    ):
        raise ValueError("The local parent-child corpus is empty or has duplicate IDs")
    # The existing builder stores baseline parent payloads without record_type.
    by_parent = {
        p["block_id"]: {k: v for k, v in p.items() if k != "record_type"}
        for p in parents
    }
    for child in children:
        parent = by_parent.get(child["parent_block_id"])
        if parent is None or child["parent_text_sha256"] != sha256(
            parent["text"].encode()
        ):
            raise ValueError("Child references a missing or changed parent")
    stored = [{**c, "parent_record": by_parent[c["parent_block_id"]]} for c in children]
    chroma = {**config["chroma"], "collections": {"qwen": settings["collection"]}}
    if chroma_path is not None:
        chroma["path"] = str(chroma_path)
    signature = fingerprint("qwen", config["qwen"])
    info = {
        "provider": "qwen",
        "model": config["qwen"]["model"],
        "dimensions": config["qwen"]["dimensions"],
        "fingerprint": signature,
        "input_sha256": sha256(corpus),
    }
    sources = {
        name: sha256((root / name).read_bytes())
        for name in dict.fromkeys([settings["input"], settings["output"]])
    }
    store = ChromaStore(
        root, chroma, "qwen", signature, info["input_sha256"], info["dimensions"]
    )
    return store, corpus, parents, stored, info, sources


def _vectors(matrix, count, dimensions):
    matrix = np.asarray(matrix, dtype=np.float32)
    normalized_vectors(
        matrix, count, dimensions
    )  # Validate shape, finite values, nonzero norms.
    if not np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-4):
        raise ValueError("Package vectors must be unit normalized")
    return matrix


def export_package(root, config_path, output):
    """Read a complete existing collection; never load a model or call an API."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing to replace an existing package: {output}")
    store, corpus, parents, stored, info, sources = _context(root, config_path)
    if store.get_blocks() != stored:
        raise ValueError("Stored Chroma records do not match the complete local corpus")
    ids = [r["block_id"] for r in stored]
    data = store.open().get(ids=ids, include=["embeddings", "documents"])
    positions = {identity: i for i, identity in enumerate(data["ids"])}
    if set(positions) != set(ids) or len(data["ids"]) != len(ids):
        raise ValueError(
            "The collection does not contain exactly the required child vectors"
        )
    if any(
        data["documents"][positions[r["block_id"]]] != r["embedding_text"]
        for r in stored
    ):
        raise ValueError("Stored embedding documents differ from the corpus")
    matrix = _vectors(
        [data["embeddings"][positions[i]] for i in ids], len(ids), info["dimensions"]
    )
    stream = io.BytesIO()
    np.savez_compressed(stream, ids=np.asarray(ids, dtype=np.str_), vectors=matrix)
    readme = f"""Warhammer Agent precomputed Qwen parent-child index

Model: {info["model"]}; dimensions: {info["dimensions"]}.
Includes {len(parents)} complete parents and {len(ids)} child vectors.
No API key, model weights, conversations or Chroma internal database files are included.

Use source code with matching config and reports. From the repository root:
1. Install dependencies:
   uv sync --locked --extra agent --extra qwen --extra chroma --extra gemini --extra ui
2. Verify the downloaded archive against the published SHA256SUMS.txt.
3. Validate (no model loading, API request or Chroma writes):
   .venv/bin/python scripts/index_package.py validate --archive PATH_TO_THIS_ZIP
4. Import (no model loading or API request):
   .venv/bin/python scripts/index_package.py import --archive PATH_TO_THIS_ZIP
5. Download/cache Qwen once if it is not already cached:
   uv run --locked --extra qwen --extra chroma python scripts/embed_parent_child.py --query "How does Deep Strike work?" --top-k 1
6. Start the app and enter your own Gemini API key:
   .venv/bin/python -m streamlit run scripts/chat_app.py

Qwen is STILL required to encode user queries. Document embeddings do not need
rebuilding. Existing same-version records are upserted; other collections remain
untouched. A corpus or model-configuration mismatch is rejected before writing.
Never use Gemini query embeddings against these Qwen document vectors.
"""
    payload = {
        "vectors.npz": stream.getvalue(),
        "parent_child_blocks.jsonl": corpus,
        "README.txt": readme.encode(),
    }
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    manifest = {
        "format_version": FORMAT_VERSION,
        "index_kind": "parent_child",
        **info,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "parents": len(parents),
        "children": len(ids),
        "sources": sources,
        "files": {name: sha256(value) for name, value in payload.items()},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, data in payload.items():
                archive.writestr(name, data)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(f"{sha256(output.read_bytes())}  {output.name}\n")
    return {"archive": str(output), "checksum": str(checksum), "manifest": manifest}


def validate_package(root, config_path, archive_path, chroma_path=None):
    """Read named entries only; never extract paths or unpickle NumPy objects."""
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) != len(MEMBERS) or {m.filename for m in members} != MEMBERS:
            raise ValueError("Unexpected, duplicate or missing archive members")
        if sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
            raise ValueError("Archive exceeds the supported unpacked size")
        content = {name: archive.read(name) for name in MEMBERS}
    manifest = json.loads(content["manifest.json"])
    if (
        manifest.get("format_version") != FORMAT_VERSION
        or manifest.get("index_kind") != "parent_child"
    ):
        raise ValueError("Unsupported index package format")
    expected_files = MEMBERS - {"manifest.json"}
    if set(manifest.get("files", {})) != expected_files:
        raise ValueError("Manifest file inventory mismatch")
    for name in expected_files:
        if manifest["files"][name] != sha256(content[name]):
            raise ValueError(f"Package checksum mismatch: {name}")
    store, corpus, parents, stored, info, sources = _context(
        root, config_path, chroma_path
    )
    if any(manifest.get(k) != v for k, v in info.items()):
        raise ValueError(
            "Package model, dimensions or configuration do not match this project"
        )
    if (
        manifest.get("sources") != sources
        or content["parent_child_blocks.jsonl"] != corpus
    ):
        raise ValueError("Package corpus/source hashes do not match this project")
    if manifest.get("parents") != len(parents) or manifest.get("children") != len(
        stored
    ):
        raise ValueError("Package record counts do not match the corpus")
    binary = io.BytesIO(content["vectors.npz"])
    with zipfile.ZipFile(binary) as arrays:
        if sum(m.file_size for m in arrays.infolist()) > MAX_UNPACKED_BYTES:
            raise ValueError("Vector array exceeds the supported unpacked size")
    binary.seek(0)
    with np.load(binary, allow_pickle=False) as arrays:
        if set(arrays.files) != {"ids", "vectors"}:
            raise ValueError("Unexpected vector array fields")
        ids = arrays["ids"]
        if (
            ids.ndim != 1
            or ids.dtype.kind != "U"
            or ids.tolist() != [r["block_id"] for r in stored]
        ):
            raise ValueError("Vector IDs/order do not match the corpus")
        matrix = _vectors(arrays["vectors"], len(stored), info["dimensions"])
    return manifest, store, stored, matrix, info


def import_package(root, config_path, archive_path, chroma_path=None):
    manifest, store, stored, matrix, info = validate_package(
        root, config_path, archive_path, chroma_path
    )
    store.write(stored, matrix, info)
    if store.get_blocks() != stored:
        raise ValueError("Imported records failed the post-write check")
    return {
        "collection": store.name,
        "chroma_path": str(store.path),
        "children": manifest["children"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/parent_child.json"))
    commands = parser.add_subparsers(dest="action", required=True)
    export = commands.add_parser(
        "export", help="Export an existing Qwen parent-child collection"
    )
    export.add_argument("--output", type=Path, required=True)
    for name in ("validate", "import"):
        command = commands.add_parser(name)
        command.add_argument("--archive", type=Path, required=True)
        command.add_argument(
            "--chroma-path", type=Path, help="Override local Chroma destination"
        )
    args = parser.parse_args()
    root = Path.cwd()
    try:
        if args.action == "export":
            result = export_package(root, args.config, args.output)
        elif args.action == "import":
            result = import_package(root, args.config, args.archive, args.chroma_path)
        else:
            result = validate_package(
                root, args.config, args.archive, args.chroma_path
            )[0]
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Index package failed: {error}\n")
