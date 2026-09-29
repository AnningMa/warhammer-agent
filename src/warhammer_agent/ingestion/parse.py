"""CPU Docling conversion with page-level exports and native-text comparison."""

import argparse
import json
import logging
import re
import time
from collections import Counter
from pathlib import Path

import pymupdf


def words(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def token_recall(native: str, extracted: str) -> float | None:
    """Order-independent diagnostic, not a measure of semantic correctness."""
    source = words(native)
    return (
        round(sum((source & words(extracted)).values()) / sum(source.values()), 4)
        if source
        else None
    )


def main() -> None:
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/docling"))
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    with pymupdf.open(args.pdf) as pdf:
        end = args.end_page or len(pdf)
        if not 1 <= args.start_page <= end <= len(pdf):
            parser.error("Invalid page range")
        native = {n: pdf[n - 1].get_text() for n in range(args.start_page, end + 1)}
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "pages").mkdir(exist_ok=True)
    options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=True,
        accelerator_options=AcceleratorOptions(
            device=AcceleratorDevice.CPU, num_threads=args.threads
        ),
    )
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    started = time.monotonic()
    result = converter.convert(args.pdf, page_range=(args.start_page, end))
    doc = result.document
    doc.save_as_json(out / "document.json")
    (out / "document.md").write_text(
        doc.export_to_markdown(traverse_pictures=True), encoding="utf-8"
    )
    rows = []
    for number, text in native.items():
        markdown = doc.export_to_markdown(page_no=number, traverse_pictures=True)
        (out / "pages" / f"page_{number:03d}.md").write_text(markdown, encoding="utf-8")
        items = []
        counts: Counter[str] = Counter()
        for item, level in doc.iterate_items(page_no=number, traverse_pictures=True):
            label = str(item.label.value)
            counts[label] += 1
            items.append(
                {
                    "ref": item.self_ref,
                    "label": label,
                    "level": level,
                    "text": getattr(item, "text", ""),
                    "provenance": [p.model_dump(mode="json") for p in item.prov],
                }
            )
        rows.append(
            {
                "page": number,
                "native_chars": len(text),
                "markdown_chars": len(markdown),
                "native_token_recall": token_recall(text, markdown),
                "labels": dict(counts),
                "ordered_items": items,
            }
        )
    report = {
        "source": str(args.pdf),
        "status": result.status.value,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "settings": {
            "device": "cpu",
            "ocr": False,
            "traverse_pictures": True,
            "table_structure": True,
            "page_range": [args.start_page, end],
        },
        "errors": [e.model_dump(mode="json") for e in result.errors],
        "notes": [
            "Token recall compares native words ignoring order; not an accuracy score.",
            "Markdown includes picture child text but excludes some furniture; JSON preserves provenance.",
            "OCR disabled: scanned and image-only text is not recovered.",
        ],
        "pages": rows,
    }
    (out / "quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "pages": len(rows),
                "elapsed_seconds": report["elapsed_seconds"],
                "errors": report["errors"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
