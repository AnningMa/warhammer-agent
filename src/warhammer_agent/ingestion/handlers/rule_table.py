"""Combine reviewed text hierarchy with a source-verified illustrated rule table."""

import argparse
import hashlib
import json
from html import escape
from pathlib import Path

import pymupdf

from .text import clean_page, render_page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument(
        "--document", type=Path, default=Path("reports/docling/document.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cleaned"))
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text())
    for path, key in [(args.pdf, "source_sha256"), (args.document, "document_sha256")]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != rules[key]:
            raise ValueError("Source changed: review rule table")
    document = json.loads(args.document.read_text())
    report = clean_page(document, rules)
    md, html = render_page(report)
    table = rules["verified_table"]
    original = next(
        n for n in document["tables"] if n["self_ref"] == table["source_ref"]
    )
    report["verified_table"] = {
        **table,
        "original_node": original,
        "method": "Dice-face values visually verified against source PDF; not OCR output",
    }
    out = args.output_dir
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    with pymupdf.open(args.pdf) as pdf:
        pdf[rules["page"] - 1].get_pixmap(
            matrix=pymupdf.Matrix(3, 3), clip=pymupdf.Rect(table["bbox"])
        ).save(out / table["image"])
    md += (
        "\n### "
        + table["title"]
        + "\n\n!["
        + table["title"]
        + "](../"
        + table["image"]
        + ")\n\n"
    )
    md += "| " + " | ".join(table["headers"]) + " |\n|---|---|\n"
    md += "\n".join("| " + " | ".join(row) + " |" for row in table["rows"]) + "\n"
    html += (
        "<h3>"
        + escape(table["title"])
        + '</h3><img src="'
        + table["image"]
        + '" alt="Original wound roll table"><table><tr>'
        + "".join("<th>" + escape(h) + "</th>" for h in table["headers"])
        + "</tr>"
        + "".join(
            "<tr>" + "".join("<td>" + escape(c) + "</td>" for c in row) + "</tr>"
            for row in table["rows"]
        )
        + "</table>"
    )
    stem = f"page_{rules['page']:03d}"
    (out / "pages" / f"{stem}.md").write_text(md, encoding="utf-8")
    (out / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / f"{stem}.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Cleaned attack rules</title><style>body{max-width:900px;margin:40px auto;padding:20px;font-family:system-ui;line-height:1.6}img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:10px}</style>'
        + html
        + "</html>",
        encoding="utf-8",
    )
    print(
        f"Page {rules['page']}: hierarchy corrected; original table image and verified values exported"
    )


if __name__ == "__main__":
    main()
