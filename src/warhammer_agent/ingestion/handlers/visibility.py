"""Export reviewed page 8 diagrams beside their matching visibility rules."""

import argparse
import hashlib
import json
from html import escape
from pathlib import Path

import pymupdf

from ..geometry import top_left_bbox


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--document", type=Path, default=Path("reports/docling/document.json")
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("config/corrections/core_rules/page_008.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cleaned"))
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text())
    for path, key in [(args.pdf, "source_sha256"), (args.document, "document_sha256")]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != rules[key]:
            raise ValueError("Source changed: review page 8 mappings")
    doc = json.loads(args.document.read_text())
    nodes = {n["self_ref"]: n for kind in ["texts", "pictures"] for n in doc[kind]}
    out = args.output_dir
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    intro = [nodes[r] for r in rules["intro_refs"]]
    md = [f"## {intro[0]['text']}", intro[1]["text"]]
    html = [
        f"<h1>{escape(intro[0]['text'])}</h1>",
        f"<p>{escape(intro[1]['text'])}</p>",
    ]
    sections = []
    with pymupdf.open(args.pdf) as pdf:
        page = pdf[7]
        for spec in rules["sections"]:
            heading, body = [nodes[r] for r in spec["text_refs"]]
            picture = nodes[spec["picture_ref"]]
            captions = [nodes[c["$ref"]] for c in picture["children"]]
            if heading["text"] != spec["expected_heading"]:
                raise ValueError("Heading changed: review mapping")
            prov = picture["prov"][0]
            if prov["page_no"] != 8:
                raise ValueError("Picture is on the wrong page")
            bbox = top_left_bbox(prov["bbox"], page.rect.height)
            image = f"images/page_008_{spec['id']}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=pymupdf.Rect(bbox)).save(
                out / image
            )
            md.extend(
                [
                    f"## {heading['text']}",
                    body["text"],
                    f"![{captions[0]['text']}](../{image})",
                ]
            )
            md.extend(c["text"] for c in captions[1:])
            html.extend(
                [
                    f"<h2>{escape(heading['text'])}</h2>",
                    f"<p>{escape(body['text'])}</p>",
                    f'<figure><img src="{image}" alt="{escape(captions[0]["text"])}"><figcaption>'
                    + " ".join(escape(c["text"]) for c in captions)
                    + "</figcaption></figure>",
                ]
            )
            sections.append(
                {
                    "id": spec["id"],
                    "page": 8,
                    "heading": heading,
                    "body": body,
                    "figure": {
                        "image": image,
                        "bbox": bbox,
                        "coordinate_system": "PDF points, top-left origin",
                        "source_node": picture,
                        "captions": captions,
                    },
                }
            )
    summary = [nodes[r] for r in rules["summary_refs"]]
    md.append("\n".join("- " + n["text"].removeprefix("■ ") for n in summary))
    html.append(
        "<ul>"
        + "".join(
            "<li>" + escape(n["text"].removeprefix("■ ")) + "</li>" for n in summary
        )
        + "</ul>"
    )
    (out / "pages/page_008.md").write_text("\n\n".join(md) + "\n", encoding="utf-8")
    report = {
        "source": str(args.pdf),
        "page": 8,
        "rules": rules,
        "intro": intro,
        "sections": sections,
        "summary": summary,
        "excluded_furniture": [nodes[r] for r in rules["furniture_refs"]],
    }
    (out / "page_008.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "page_008.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Page 8 — visibility</title><style>body{max-width:900px;margin:40px auto;padding:20px;font-family:system-ui;line-height:1.6}img{max-width:100%}figure{margin:24px 0}</style>'
        + "".join(html)
        + "</html>",
        encoding="utf-8",
    )
    print(
        "Page 8: four diagrams linked to matching rules, with original captions and provenance"
    )


if __name__ == "__main__":
    main()
