"""Apply a reviewed figure grouping while retaining raw annotations and provenance."""

import argparse
import hashlib
import json
from html import escape
from pathlib import Path

import pymupdf


def group_page(document: dict, rules: dict) -> dict:
    nodes = {
        t["self_ref"]: t
        for t in document["texts"]
        if any(p["page_no"] == rules["page"] for p in t.get("prov", []))
    }
    selected = (
        rules["body_refs"]
        + rules["summary_refs"]
        + rules["caption_refs"]
        + rules["annotation_refs"]
        + rules["furniture_refs"]
    )
    if len(selected) != len(set(selected)) or set(selected) != set(nodes):
        raise ValueError("Page nodes changed or assigned twice; review figure rules")

    def resolve(refs):
        return [nodes[ref] for ref in refs]

    captions = resolve(rules["caption_refs"])
    if rules.get("caption_groups"):
        grouped = [ref for group in rules["caption_groups"] for ref in group]
        if grouped != rules["caption_refs"]:
            raise ValueError("Caption groups must cover caption refs in order")
        captions = [
            {
                "text": " ".join(nodes[ref]["text"] for ref in group),
                "source_nodes": resolve(group),
                "prov": [prov for ref in group for prov in nodes[ref]["prov"]],
            }
            for group in rules["caption_groups"]
        ]
    return {
        "page": rules["page"],
        "body": resolve(rules["body_refs"]),
        "summary": resolve(rules["summary_refs"]),
        "figure": {
            "id": rules["figure_id"],
            "page": rules["page"],
            "bbox": rules["figure_bbox"],
            "coordinate_system": "PDF points, top-left origin",
            "image": rules.get("image", "images/page_006_coherency.png"),
            "title": rules.get("figure_title", "Unit Coherency — illustrated examples"),
            "alt": rules.get(
                "figure_alt",
                rules.get("figure_title", "Unit Coherency — illustrated examples"),
            ),
            "captions": captions,
            "annotations": resolve(rules["annotation_refs"]),
        },
        "excluded_furniture": resolve(rules["furniture_refs"]),
    }


def render_markdown(report: dict) -> str:
    blocks = []
    for node in report["body"]:
        blocks.append(
            (
                "## "
                if node["label"] == "section_header"
                else "- "
                if node["label"] == "list_item"
                else ""
            )
            + node["text"].removeprefix("■").strip()
        )
    for index, node in enumerate(report["summary"]):
        prefix = "  - " if index in (1, 2) else "- "
        blocks.append(prefix + node["text"].removeprefix("■ ").strip())
    body = "\n\n".join(blocks[: len(report["body"])])
    summary = "\n".join(blocks[len(report["body"]) :])
    figure = report["figure"]
    captions = "\n\n".join(
        (
            "**" + n["text"][0] + "** " + n["text"][2:]
            if n["text"].startswith(("A ", "B "))
            else n["text"]
        )
        for n in figure["captions"]
    )
    return (
        body
        + "\n\n"
        + summary
        + f"\n\n### {figure['title']}\n\n"
        + f"![{figure.get('alt', figure['title'])}](../{figure['image']})\n\n"
        + captions
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--document", type=Path, default=Path("reports/docling/document.json")
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("config/corrections/core_rules/page_006.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cleaned"))
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text())
    for path, key in [(args.pdf, "source_sha256"), (args.document, "document_sha256")]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != rules[key]:
            raise ValueError("Source changed; review figure rules before applying")
    report = group_page(json.loads(args.document.read_text()), rules)
    report.update({"source": str(args.pdf), "rules": rules})
    out = args.output_dir
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    with pymupdf.open(args.pdf) as doc:
        doc[rules["page"] - 1].get_pixmap(
            matrix=pymupdf.Matrix(2, 2), clip=pymupdf.Rect(rules["figure_bbox"])
        ).save(out / report["figure"]["image"])
    stem = f"page_{rules['page']:03d}"
    (out / "pages" / f"{stem}.md").write_text(render_markdown(report), encoding="utf-8")
    (out / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    content = "".join(
        f"<h2>{escape(n['text'])}</h2>"
        if n["label"] == "section_header"
        else f"<p>{escape(n['text'])}</p>"
        for n in report["body"]
    )
    content += (
        "<ul>"
        + "".join(f"<li>{escape(n['text'])}</li>" for n in report["summary"])
        + "</ul>"
    )
    content += (
        f'<figure><img style="width:100%" src="{escape(report["figure"]["image"])}" alt="{escape(report["figure"]["title"])}"><figcaption>'
        + "".join(f"<p>{escape(n['text'])}</p>" for n in report["figure"]["captions"])
        + "</figcaption></figure>"
    )
    (out / f"{stem}.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Cleaned PDF page</title><body style="max-width:900px;margin:40px auto;padding:20px;font-family:system-ui;line-height:1.6">'
        + content
        + "</body></html>",
        encoding="utf-8",
    )
    print(
        f"Page {rules['page']} cleaned: complete figure with A/B captions; annotations retained in JSON only"
    )


if __name__ == "__main__":
    main()
