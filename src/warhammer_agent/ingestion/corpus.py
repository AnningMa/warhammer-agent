"""Build a source-checked, heading-preserving corpus before retrieval chunking."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory

from .validation import verify_hash


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def section_blocks(markdown: str, metadata: dict) -> list[dict]:
    """Lossless heading sections, not size-limited retrieval chunks.

    Offsets refer to Unicode characters in the selected page Markdown. Tables,
    cards and figure captions are never split by blank lines or length limits.
    Heading context resets on each page: no inferred cross-page hierarchy.
    """
    boundaries = [0]
    headings = {}
    offset = 0
    fence = None
    for line in markdown.splitlines(keepends=True):
        stripped = line.lstrip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        match = None if fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            if offset:
                boundaries.append(offset)
            headings[offset] = (len(match.group(1)), match.group(2))
        offset += len(line)
    boundaries.append(len(markdown))
    result = []
    stack: list[tuple[int, str]] = []
    for start, end in pairwise(boundaries):
        text = markdown[start:end]
        if not text.strip():
            continue
        if start in headings:
            level, title = headings[start]
            stack = [(n, t) for n, t in stack if n < level] + [(level, title)]
        images = re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text)
        table = bool(re.search(r"^\s*\|.*\|\s*$", text, re.MULTILINE))
        kind = (
            "mixed"
            if images and table
            else ("figure" if images else "table" if table else "text")
        )
        path = [title for _, title in stack]
        prefix = "\n".join("#" * n + " " + title for n, title in stack)
        # Keep the existing heading exactly; prepend only missing ancestors.
        ancestors = stack[:-1] if start in headings else stack
        context = "\n".join("#" * n + " " + title for n, title in ancestors)
        identity = f"{metadata['source_hash']}:{metadata['page_number']}:{start}:{text}"
        result.append(
            {
                **metadata,
                "block_id": "core_rules." + digest(identity.encode())[:24],
                "section_title": path[-1] if path else None,
                "section_path": path,
                "heading_context": prefix,
                "content_type": kind,
                "text": text,
                "embedding_text": (context + "\n\n" if context else "") + text,
                "markdown_span": {
                    "start": start,
                    "end": end,
                    "unit": "unicode_character",
                },
                "text_sha256": digest(text.encode()),
                "assets": [{"alt": alt, "target": target} for alt, target in images],
                "warnings": metadata["warnings"]
                + (
                    [
                        "Image geometry and image-only text are not represented by text retrieval."
                    ]
                    if images or "<!-- image -->" in text
                    else []
                ),
            }
        )
    return result


def text_only(markdown: str, page: int) -> str:
    """Keep captions while replacing disposable image links with PDF references."""
    return re.sub(
        r"!\[([^\]]*)\]\([^)]+\)",
        lambda m: f"[Figure: {m.group(1)}; see source PDF page {page}]",
        markdown,
    ).replace("<!-- image -->", f"[Image; see source PDF page {page}]")


def write_outputs(blocks: list[dict], output: Path) -> None:
    """The readable TXT and JSONL contain exactly the same ordered evidence."""
    parts = []
    offset = 0
    for block in blocks:
        header = (
            f"<<<RULE_BLOCK>>>\nBlock ID: {block['block_id']}\n"
            f"Source: {block['source']} | Physical PDF pages: "
            + ", ".join(map(str, block.get("page_numbers", [block["page_number"]])))
            + "\n"
            f"Review status: {block['review_status']}\n\n"
        )
        text = block["embedding_text"]
        start = offset + len(header)
        block["txt_span"] = {
            "start": start,
            "end": start + len(text),
            "unit": "unicode_character",
            "file": "core_rules.txt",
        }
        piece = header + text + "\n\n"
        parts.append(piece)
        offset += len(piece)
    payload = "".join(parts)
    txt_hash = digest(payload.encode())
    for block in blocks:
        block["txt_sha256"] = txt_hash
    output.mkdir(parents=True, exist_ok=True)
    (output / "core_rules.txt").write_text(payload, encoding="utf-8")
    (output / "index_blocks.jsonl").write_text(
        "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blocks),
        encoding="utf-8",
    )


def build_corpus(root: Path, output: Path) -> dict:
    from docling_core.types.doc import DoclingDocument

    manifest_path = root / "config/corrections/core_rules/manifest.json"
    corrections = read_json(manifest_path)
    source = root / corrections["source"]
    document_path = root / corrections["document"]
    verify_hash(source, corrections["source_sha256"])
    verify_hash(document_path, corrections["document_sha256"])
    document = DoclingDocument.model_validate(read_json(document_path))
    pages = sorted(int(n) for n in document.pages)
    selected = {item["page"]: item for item in corrections["pages"]}
    if len(selected) != len(corrections["pages"]) or not set(selected) <= set(pages):
        raise ValueError("Duplicate or out-of-range corrected page")
    policy_path = root / "config/index_policy.json"
    policy = read_json(policy_path)
    excluded = set(policy["excluded_pages"])
    if not excluded <= set(pages):
        raise ValueError("Out-of-range exclusion")
    blocks, page_entries = [], []
    # Reviewed renderers validate source hashes and classification. All their
    # Markdown, HTML, PNG and audit files exist only in this temporary folder.
    with TemporaryDirectory(prefix="warhammer-corpus-") as temporary:
        rebuilt = Path(temporary)
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/clean_pdf.py"),
                corrections["source"],
                "--manifest",
                str(manifest_path.relative_to(root)),
                "--document",
                corrections["document"],
                "--output-dir",
                str(rebuilt),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        for number in pages:
            stem = f"page_{number:03d}"
            item = selected.get(number)
            lineage = {}
            if item:
                chosen = rebuilt / "pages" / f"{stem}.md"
                markdown = chosen.read_text(encoding="utf-8")
                rules = manifest_path.parent / item["rules"]
                audit = rebuilt / f"{stem}.json"
                lineage = {
                    "correction_path": str(rules.relative_to(root)),
                    "correction_sha256": digest(rules.read_bytes()),
                    "audit_sha256": digest(audit.read_bytes()),
                    "handler": item["handler"],
                }
                status, origin = item["status"], "reviewed_cleaned"
            else:
                chosen = document_path
                markdown = document.export_to_markdown(
                    page_no=number, traverse_pictures=True
                )
                status, origin = "unreviewed", "original_docling"
            metadata = {
                "schema_version": 2,
                "document_id": "core_rules",
                "source": source.name,
                "source_path": str(source.relative_to(root)),
                "source_hash": corrections["source_sha256"],
                "document_path": str(document_path.relative_to(root)),
                "document_sha256": corrections["document_sha256"],
                "page_number": number,
                "page_numbers": [number],
                "page_number_basis": "physical_pdf_1_based",
                "review_status": status,
                "origin": origin,
                "source_representation": "regenerated_page_markdown",
                "selected_markdown_sha256": digest(markdown.encode()),
                "corrections_manifest_sha256": digest(manifest_path.read_bytes()),
                "index_policy_path": str(policy_path.relative_to(root)),
                "index_policy_sha256": digest(policy_path.read_bytes()),
                "ocr_used": False,
                "warnings": ["Original Docling page has not been manually reviewed."]
                if status == "unreviewed"
                else [],
                **lineage,
            }
            page_entries.append(
                {
                    "page_number": number,
                    "origin": origin,
                    "index_eligible": number not in excluded,
                }
            )
            page_blocks = section_blocks(markdown, metadata)
            for block in page_blocks:
                block["_markdown"] = block["text"]
                for asset in block["assets"]:
                    if not item:
                        raise ValueError(
                            "Unexpected image link in original Docling export"
                        )
                    path = (chosen.parent / asset.pop("target")).resolve()
                    if not path.is_relative_to(rebuilt.resolve()) or not path.is_file():
                        raise ValueError(
                            f"Missing or external regenerated image: {path}"
                        )
                    asset.update(
                        source_pdf_page=number,
                        stored=False,
                        regenerated_image_sha256=digest(path.read_bytes()),
                    )
                block["text"] = text_only(block["text"], number)
                block["embedding_text"] = text_only(block["embedding_text"], number)
                block["text_sha256"] = digest(block["text"].encode())
            if number not in excluded:
                blocks.extend(page_blocks)
    from .optimize import optimize_blocks

    relations_path = root / "config/corpus_relations.json"
    blocks = optimize_blocks(
        blocks, read_json(relations_path), digest(relations_path.read_bytes())
    )
    from .context import enrich_blocks

    context_path = root / "config/rule_context.json"
    blocks = enrich_blocks(
        blocks, read_json(context_path), digest(context_path.read_bytes())
    )
    write_outputs(blocks, output)
    return {
        "pages": page_entries,
        "block_count": len(blocks),
        "index_block_count": len(blocks),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = (
        args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    )
    result = build_corpus(root, output)
    print(
        json.dumps(
            {
                "pages": len(result["pages"]),
                "blocks": result["block_count"],
                "index_blocks": result["index_block_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
