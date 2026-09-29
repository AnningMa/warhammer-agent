"""Group multiple reviewed diagrams with their corresponding sections and captions."""

import argparse
import hashlib
import json
from html import escape
from pathlib import Path

import pymupdf

from .figure import group_page, render_markdown


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
            raise ValueError("Source changed: review diagram mappings")
    document = json.loads(args.document.read_text())
    nodes = {
        n["self_ref"]: n
        for n in document["texts"]
        if any(p["page_no"] == rules["page"] for p in n.get("prov", []))
    }
    selected = list(rules["furniture_refs"])
    for section in rules["sections"]:
        for key in [
            "body_refs",
            "summary_refs",
            "caption_refs",
            "annotation_refs",
            "furniture_refs",
        ]:
            selected.extend(section[key])
    if len(selected) != len(set(selected)) or set(selected) != set(nodes):
        raise ValueError("Page node coverage changed or duplicated")
    out = args.output_dir
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    reports, markdown, html = [], [], []
    with pymupdf.open(args.pdf) as pdf:
        for section in rules["sections"]:
            ids = {
                ref
                for key in [
                    "body_refs",
                    "summary_refs",
                    "caption_refs",
                    "annotation_refs",
                    "furniture_refs",
                ]
                for ref in section[key]
            }
            report = group_page(
                {"texts": [nodes[ref] for ref in nodes if ref in ids]}, section
            )
            figure = report["figure"]
            pdf[rules["page"] - 1].get_pixmap(
                matrix=pymupdf.Matrix(2, 2), clip=pymupdf.Rect(figure["bbox"])
            ).save(out / figure["image"])
            md = render_markdown(report)
            if section.get("examples_heading"):
                md = md.replace(
                    "\n\n### ", "\n\n## " + section["examples_heading"] + "\n\n### ", 1
                )
            markdown.append(md)
            body = md.split("\n\n### ", 1)[0]
            html.append(
                "<section><pre>"
                + escape(body)
                + '</pre><figure><img src="'
                + escape(figure["image"])
                + '" alt="'
                + escape(figure["title"])
                + '"><figcaption>'
                + "".join(
                    "<p>" + escape(n["text"]) + "</p>" for n in figure["captions"]
                )
                + "</figcaption></figure></section>"
            )
            reports.append(report)
    stem = f"page_{rules['page']:03d}"
    (out / "pages" / f"{stem}.md").write_text("\n\n".join(markdown), encoding="utf-8")
    (out / f"{stem}.json").write_text(
        json.dumps(
            {
                "source": str(args.pdf),
                "rules": rules,
                "sections": reports,
                "excluded_furniture": [nodes[r] for r in rules["furniture_refs"]],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / f"{stem}.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Cleaned diagrams</title><style>body{max-width:900px;margin:40px auto;padding:20px;font-family:system-ui;line-height:1.6}pre{white-space:pre-wrap;font:inherit}img{max-width:100%}figure{margin:20px 0}</style>'
        + "".join(html)
        + "</html>",
        encoding="utf-8",
    )
    print(f"Page {rules['page']}: {len(reports)} diagrams linked to matching sections")


if __name__ == "__main__":
    main()
