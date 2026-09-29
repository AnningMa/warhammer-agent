"""Replace a reviewed incomplete table with its source image and verified values."""

import argparse
import hashlib
import json
from html import escape
from pathlib import Path

import pymupdf

from ..render import raw_page_markdown
from ..validation import verify_hash


def replace_table(markdown: str, rules: dict) -> tuple[str, str, str]:
    original = rules["original_fragment"]
    if markdown.count(original) != 1:
        raise ValueError("Expected exactly one matching table; review correction")
    table = "| D6 result | D3 result |\n|---|---|\n"
    table += "\n".join(
        f"| {' or '.join(map(str, row['d6']))} | {row['d3']} |" for row in rules["rows"]
    )
    replacement = f"### ROLLING A D3\n\n![Rolling a D3 — original diagram](../{rules['image']})\n\n{table}"
    before, after = markdown.split(original)
    return before + replacement + after, before, after


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--rules",
        type=Path,
        default=Path("config/corrections/core_rules/page_009.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cleaned"))
    parser.add_argument(
        "--document", type=Path, default=Path("reports/docling/document.json")
    )
    args = parser.parse_args()
    rules = json.loads(args.rules.read_text())
    verify_hash(args.pdf, rules["source_sha256"])
    verify_hash(args.document, rules["document_sha256"])
    source = raw_page_markdown(args.document, rules["page"])
    if hashlib.sha256(source.encode()).hexdigest() != rules["markdown_sha256"]:
        raise ValueError("Re-export changed; review table correction")
    markdown, before, after = replace_table(source, rules)
    out = args.output_dir
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    with pymupdf.open(args.pdf) as doc:
        doc[rules["page"] - 1].get_pixmap(
            matrix=pymupdf.Matrix(3, 3), clip=pymupdf.Rect(rules["bbox"])
        ).save(out / rules["image"])
    stem = f"page_{rules['page']:03d}"
    (out / "pages" / f"{stem}.md").write_text(markdown, encoding="utf-8")
    (out / f"{stem}.json").write_text(
        json.dumps(
            {
                "source": str(args.pdf),
                "page": rules["page"],
                "correction": rules,
                "method": "Manually verified dice-face transcription from source image; no OCR or rule inference",
                "scope": "Only the D3 table and its four fragmented image placeholders are replaced; other content unchanged",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    rows = "".join(
        f"<tr><td>{' or '.join(map(str, r['d6']))}</td><td>{r['d3']}</td></tr>"
        for r in rules["rows"]
    )
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Page 9 — corrected D3 table</title><style>body{max-width:900px;margin:40px auto;padding:20px;font-family:system-ui;line-height:1.6}img{max-width:100%}pre{white-space:pre-wrap}table{border-collapse:collapse}th,td{border:1px solid #aaa;padding:8px 24px}</style>'
    html += f'<pre>{escape(before)}</pre><h2>ROLLING A D3</h2><img src="{rules["image"]}" alt="Original D3 conversion diagram"><table><tr><th>D6 result</th><th>D3 result</th></tr>{rows}</table><pre>{escape(after)}</pre></html>'
    (out / f"{stem}.html").write_text(html, encoding="utf-8")
    print(f"Page {rules['page']}: source image and verified table exported")


if __name__ == "__main__":
    main()
