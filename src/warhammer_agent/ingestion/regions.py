"""Apply reviewed, source-specific PDF regions without modifying raw Docling output."""

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf


def clean_regions(pdf_path: Path, rules: dict) -> dict:
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    if digest != rules["source_sha256"]:
        raise ValueError("PDF changed: review region rules before applying them")
    with pymupdf.open(pdf_path) as doc:
        page = doc[rules["page"] - 1]
        spans = []
        for bi, block in enumerate(page.get_text("dict")["blocks"]):
            for li, line in enumerate(block.get("lines", [])):
                for si, span in enumerate(line["spans"]):
                    spans.append(
                        {
                            "id": f"b{bi}/l{li}/s{si}",
                            "text": span["text"],
                            "bbox": list(span["bbox"]),
                            "size": span["size"],
                        }
                    )
        used: set[str] = set()
        sections = []
        for region in rules["regions"]:
            rect = pymupdf.Rect(region["bbox"])
            selected = [
                s
                for s in spans
                if s["size"] >= rules["min_font_size"]
                and rect.contains(pymupdf.Rect(s["bbox"]))
            ]
            headings = [
                s for s in selected if s["size"] >= rules["heading_min_font_size"]
            ]
            body = [s for s in selected if s["size"] < rules["heading_min_font_size"]]
            title = " ".join(" ".join(s["text"] for s in headings).split())
            text = " ".join(" ".join(s["text"] for s in body).split())
            if title != region["expected_heading"] or not text:
                raise ValueError(
                    f"Region {region['id']} changed: heading/body requires review"
                )
            ids = {s["id"] for s in selected}
            if used & ids:
                raise ValueError("Overlapping regions assign the same text twice")
            used.update(ids)
            sections.append(
                {
                    "id": region["id"],
                    "page": rules["page"],
                    "bbox": region["bbox"],
                    "heading": title,
                    "text": text,
                    "source_spans": selected,
                }
            )
        excluded = [
            {
                **s,
                "reason": "Below page-specific font threshold or outside reviewed regions",
            }
            for s in spans
            if s["id"] not in used
        ]
        return {
            "source": str(pdf_path),
            "source_sha256": digest,
            "page": rules["page"],
            "coordinate_system": "PDF points, top-left origin",
            "rules": rules,
            "sections": sections,
            "excluded_spans": excluded,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cleaned"))
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    report = clean_regions(args.pdf, rules)
    pages = args.output_dir / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    stem = f"page_{report['page']:03d}"
    markdown = (
        "\n\n".join(f"## {s['heading']}\n\n{s['text']}" for s in report["sections"])
        + "\n"
    )
    (pages / f"{stem}.md").write_text(markdown, encoding="utf-8")
    (args.output_dir / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Cleaned page {report['page']}: {len(report['sections'])} sections; {len(report['excluded_spans'])} spans isolated"
    )


if __name__ == "__main__":
    main()
