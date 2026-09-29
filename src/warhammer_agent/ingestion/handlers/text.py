"""Apply reviewed text-node selection, with an audit trail for omissions."""

import argparse
import hashlib
import json
from html import escape
from pathlib import Path


def clean_page(document: dict, rules: dict) -> dict:
    nodes = {
        n["self_ref"]: n
        for n in document["texts"]
        if any(p["page_no"] == rules["page"] for p in n.get("prov", []))
    }
    selected = rules["keep_refs"] + list(rules["omit_reasons"])
    if len(selected) != len(set(selected)) or set(selected) != set(nodes):
        raise ValueError("Page nodes changed or duplicated: review selection")
    return {
        "page": rules["page"],
        "rules": rules,
        "kept_nodes": [nodes[r] for r in rules["keep_refs"]],
        "omitted_nodes": [
            {"node": nodes[r], "reason": reason}
            for r, reason in rules["omit_reasons"].items()
        ],
        "omitted_picture_nodes": [
            n
            for n in document["pictures"]
            if any(p["page_no"] == rules["page"] for p in n.get("prov", []))
        ],
    }


def render_page(report: dict) -> tuple[str, str]:
    markdown, html = [], []
    for node in report["kept_nodes"]:
        inserted = report["rules"].get("headings_before", {}).get(node["self_ref"])
        if inserted:
            level = inserted["level"]
            markdown.append("#" * level + " " + inserted["text"])
            html.append(f"<h{level}>" + escape(inserted["text"]) + f"</h{level}>")
        text = (
            report["rules"]
            .get("heading_overrides", {})
            .get(node["self_ref"], node["text"])
        )
        label = node["label"]
        number = report["rules"].get("ordered_items", {}).get(node["self_ref"])
        if number is not None:
            markdown.append(f"{number}. " + text)
            html.append(f'<ol start="{number}"><li>' + escape(text) + "</li></ol>")
        elif label == "section_header":
            level = report["rules"].get("heading_levels", {}).get(node["self_ref"], 2)
            markdown.append("#" * level + " " + text)
            html.append(f"<h{level}>" + escape(text) + f"</h{level}>")
        elif label == "list_item":
            text = text.removeprefix("■").strip()
            markdown.append("- " + text)
            html.append("<p>• " + escape(text) + "</p>")
        else:
            markdown.append(text)
            html.append("<p>" + escape(text) + "</p>")
    return "\n\n".join(markdown) + "\n", "".join(html)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument(
        "--document", type=Path, default=Path("reports/docling/document.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cleaned"))
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text())
    if (
        hashlib.sha256(args.document.read_bytes()).hexdigest()
        != rules["document_sha256"]
    ):
        raise ValueError("Source changed: review text correction")
    report = clean_page(json.loads(args.document.read_text()), rules)
    markdown, html = render_page(report)
    out = args.output_dir
    (out / "pages").mkdir(parents=True, exist_ok=True)
    stem = f"page_{rules['page']:03d}"
    (out / "pages" / f"{stem}.md").write_text(markdown, encoding="utf-8")
    (out / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / f"{stem}.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Cleaned page '
        + str(rules["page"])
        + "</title><style>body{max-width:900px;margin:40px auto;padding:20px;font-family:system-ui;line-height:1.6}</style>"
        + html
        + "</html>",
        encoding="utf-8",
    )
    print(
        f"Page {rules['page']}: kept {len(report['kept_nodes'])} nodes; isolated {len(report['omitted_nodes'])} nodes"
    )


if __name__ == "__main__":
    main()
