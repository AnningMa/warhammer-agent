"""Render source-checked page corrections with explicit text/image relationships."""

import argparse
import hashlib
import json
from html import escape
from pathlib import Path

import pymupdf


def refs_in(block: dict) -> set[str]:
    refs = set(block.get("refs", []))
    refs.update(block.get("source_refs", []))
    for group in block.get("captions", []):
        refs.update(group)
    for child in block.get("children", []):
        refs.update(refs_in(child))
    return refs


def validate_coverage(document: dict, rules: dict) -> None:
    texts = {
        n["self_ref"]
        for n in document["texts"]
        if any(p["page_no"] == rules["page"] for p in n.get("prov", []))
    }
    used = set().union(*(refs_in(b) for b in rules["blocks"]))
    excluded = set(rules["excluded_text"])
    if (
        (used & excluded)
        or texts != ((used & texts) | excluded)
        or not excluded <= texts
    ):
        raise ValueError(
            f"Page {rules['page']}: incomplete or conflicting text classification"
        )


def render_blocks(
    blocks: list, nodes: dict, page, out: Path, number: int
) -> tuple[str, str, list]:
    md, html, records = [], [], []
    for i, block in enumerate(blocks):
        kind = block["type"]
        source = [nodes[r] for r in block.get("refs", [])]
        text = block.get("text", " ".join(n.get("text", "") for n in source))
        record = {**block, "source_nodes": [nodes[r] for r in sorted(refs_in(block))]}
        if kind == "text":
            style = block.get("style", "p")
            if style.startswith("h"):
                level = int(style[1:])
                md.append("#" * level + " " + text)
                html.append(f"<h{level}>" + escape(text) + f"</h{level}>")
            elif style == "li":
                text = text.removeprefix("■").strip()
                md.append("- " + text)
                html.append("<p>• " + escape(text) + "</p>")
            elif style == "ordered":
                md.append(f"{block['number']}. " + text)
                html.append(
                    f'<ol start="{block["number"]}"><li>' + escape(text) + "</li></ol>"
                )
            else:
                md.append(text)
                html.append("<p>" + escape(text) + "</p>")
        elif kind == "image":
            bbox = block["bbox"]
            image = f"images/page_{number:03d}_{block['id']}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=pymupdf.Rect(bbox)).save(
                out / image
            )
            title = block.get("title", text)
            md.append(f"![{title}](../{image})")
            caption_texts = [
                " ".join(nodes[r]["text"] for r in group)
                for group in block.get("captions", [])
            ]
            md.extend(caption_texts)
            html.append(
                '<figure><img src="'
                + image
                + '" alt="'
                + escape(title)
                + '"><figcaption>'
                + "".join("<p>" + escape(t) + "</p>" for t in caption_texts)
                + "</figcaption></figure>"
            )
            record.update(
                {
                    "image": image,
                    "caption_texts": caption_texts,
                    "coordinate_system": "PDF points, top-left origin",
                }
            )
        elif kind == "table":
            md.append(
                "| "
                + " | ".join(block["headers"])
                + " |\n|"
                + "|".join("---" for _ in block["headers"])
                + "|\n"
                + "\n".join(
                    "| " + " | ".join(map(str, row)) + " |" for row in block["rows"]
                )
            )
            html.append(
                "<table><tr>"
                + "".join("<th>" + escape(h) + "</th>" for h in block["headers"])
                + "</tr>"
                + "".join(
                    "<tr>"
                    + "".join("<td>" + escape(str(c)) + "</td>" for c in row)
                    + "</tr>"
                    for row in block["rows"]
                )
                + "</table>"
            )
            record["retrieval_records"] = block.get("retrieval_records", [])
        elif kind == "card":
            title = nodes[block["title_ref"]]["text"]
            cp = nodes[block["cp_ref"]]["text"]
            if cp != str(block["expected_cp"]) + "CP":
                raise ValueError("CP value differs from reviewed card mapping")
            md.append("## " + title + "\n\nCP cost: " + cp)
            html.append(
                "<article><h2>"
                + escape(title)
                + "</h2><p><strong>CP cost: "
                + escape(cp)
                + "</strong></p>"
            )
            child_md, child_html, children = render_blocks(
                block["children"], nodes, page, out, number
            )
            md.append(child_md)
            html.append(child_html + "</article>")
            fields = {}
            for child in block["children"]:
                for ref in child.get("refs", []):
                    t = nodes[ref].get("text", "")
                    prefix, sep, value = t.partition(":")
                    if sep and prefix in ["WHEN", "TARGET", "EFFECT", "RESTRICTIONS"]:
                        fields[prefix.lower()] = value.strip()
            record.update(
                {
                    "name": title,
                    "cp_cost": block["expected_cp"],
                    "fields": fields,
                    "children": children,
                }
            )
        else:
            raise ValueError("Unknown block type: " + kind)
        records.append(record)
    return "\n\n".join(md) + "\n", "".join(html), records


def clean(pdf_path: Path, document_path: Path, rules_path: Path, out: Path) -> dict:
    rules = json.loads(rules_path.read_text())
    for path, key in [(pdf_path, "source_sha256"), (document_path, "document_sha256")]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != rules[key]:
            raise ValueError("Source changed; correction requires review")
    document = json.loads(document_path.read_text())
    nodes = {
        n["self_ref"]: n
        for k in ["texts", "pictures", "tables", "groups"]
        for n in document.get(k, [])
    }
    validate_coverage(document, rules)
    for b in rules["blocks"]:
        for ref in refs_in(b):
            if ref not in nodes:
                raise ValueError("Unknown source ref " + ref)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    with pymupdf.open(pdf_path) as pdf:
        md, html, records = render_blocks(
            rules["blocks"], nodes, pdf[rules["page"] - 1], out, rules["page"]
        )
    stem = f"page_{rules['page']:03d}"
    report = {
        "page": rules["page"],
        "source": str(pdf_path),
        "rules": rules,
        "blocks": records,
        "excluded_text": [
            {"node": nodes[r], "reason": reason}
            for r, reason in rules["excluded_text"].items()
        ],
        "review_notes": rules.get("review_notes", []),
    }
    (out / "pages" / f"{stem}.md").write_text(md, encoding="utf-8")
    (out / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / f"{stem}.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Reviewed page '
        + str(rules["page"])
        + "</title><style>body{max-width:1000px;margin:32px auto;padding:20px;font-family:system-ui;line-height:1.6}img{max-width:100%;max-height:1000px}figure{margin:20px 0}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:8px}article{border:1px solid #ccc;padding:20px;margin:24px 0}</style>"
        + html
        + "</html>",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--rules", type=Path, nargs="+", required=True)
    parser.add_argument(
        "--document", type=Path, default=Path("reports/docling/document.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cleaned"))
    args = parser.parse_args()
    for path in args.rules:
        report = clean(args.pdf, args.document, path, args.output_dir)
        print(f"Page {report['page']}: source coverage checked, outputs written")


if __name__ == "__main__":
    main()
