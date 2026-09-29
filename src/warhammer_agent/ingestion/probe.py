"""Inspect native PDF content without OCR or model downloads."""

import argparse
import csv
import json
from pathlib import Path

import pymupdf


def probe_pdf(path: Path) -> dict:
    pages = []
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF requires a password")
        metadata = doc.metadata
        for page in doc:
            row = {"page": page.number + 1, "rotation": page.rotation}
            errors = {}
            try:
                text = page.get_text()
                row["text_length"] = len(text)
                row["non_whitespace_length"] = sum(not c.isspace() for c in text)
                row["no_text"] = row["non_whitespace_length"] == 0
            except Exception as exc:  # noqa: BLE001 - preserve per-page diagnostics
                errors["text"] = str(exc)
            try:
                row["image_count"] = len(page.get_image_info())
            except Exception as exc:  # noqa: BLE001 - preserve per-page diagnostics
                errors["images"] = str(exc)
            try:
                tables = page.find_tables().tables
                row["table_count"] = len(tables)
                row["table_bboxes"] = [list(table.bbox) for table in tables]
            except Exception as exc:  # noqa: BLE001 - preserve per-page diagnostics
                errors["tables"] = str(exc)
            row["errors"] = errors
            pages.append(row)
        return {
            "source": str(path),
            "pymupdf_version": pymupdf.VersionBind,
            "page_count": len(doc),
            "metadata": metadata,
            "definitions": {
                "page": "1-based physical PDF page number",
                "no_text": "No non-whitespace native text; not necessarily blank",
                "image_count": "Displayed raster image instances, not unique assets or vectors",
                "table_count": "Heuristic candidates from default find_tables; not verified tables",
                "rotation": "PDF page rotation metadata, not detected text orientation",
                "errors": "Failed measurements are absent, never counted as zero",
            },
            "summary": {
                "no_text_pages": [r["page"] for r in pages if r.get("no_text")],
                "image_instances_measured": sum(r.get("image_count", 0) for r in pages),
                "candidate_table_pages": [
                    r["page"] for r in pages if r.get("table_count")
                ],
                "rotated_pages": [r["page"] for r in pages if r["rotation"]],
                "pages_with_errors": [r["page"] for r in pages if r["errors"]],
            },
            "pages": pages,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/pdf_probe"))
    args = parser.parse_args()
    report = probe_pdf(args.pdf)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = [
        "page",
        "text_length",
        "non_whitespace_length",
        "no_text",
        "image_count",
        "table_count",
        "rotation",
        "errors",
    ]
    with (args.output_dir / "pages.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in report["pages"]:
            writer.writerow(
                {**row, "errors": json.dumps(row["errors"], ensure_ascii=False)}
            )
    print(
        json.dumps({"page_count": report["page_count"], **report["summary"]}, indent=2)
    )


if __name__ == "__main__":
    main()
