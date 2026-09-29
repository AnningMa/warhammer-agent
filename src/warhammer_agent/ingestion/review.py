"""Build a local side-by-side view from existing Docling page exports."""

import argparse
from html import escape
from pathlib import Path

import pymupdf

from .render import raw_page_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--result-dir", type=Path, default=Path("reports/docling"))
    parser.add_argument(
        "--pages", type=int, nargs="+", default=[2, 4, 6, 13, 20, 41, 59]
    )
    args = parser.parse_args()
    sections = []
    with pymupdf.open(args.pdf) as doc:
        for number in args.pages:
            page_path = args.result_dir / "pages" / f"page_{number:03d}.md"
            markdown = (
                page_path.read_text(encoding="utf-8")
                if page_path.exists()
                else raw_page_markdown(args.result_dir / "document.json", number)
            )
            directory = args.result_dir / "review_images"
            directory.mkdir(exist_ok=True)
            filename = f"page_{number:03d}.png"
            doc[number - 1].get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3)).save(
                directory / filename
            )
            sections.append(
                f'<section id="p{number}"><h2>PDF 第 {number} 页</h2><div class="pair"><img src="review_images/{filename}" alt="PDF page {number}"><pre>{escape(markdown)}</pre></div></section>'
            )
    links = " · ".join(f'<a href="#p{n}">第 {n} 页</a>' for n in args.pages)
    html = """<!doctype html><html lang="zh"><meta charset="utf-8"><title>Docling 解析对照</title>
<style>body{font-family:system-ui;margin:24px;background:#f5f5f5;color:#222}nav{position:sticky;top:0;background:white;padding:16px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:20px;margin:0;line-height:1.6}section{scroll-margin-top:70px}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style>
<h1>Docling 解析对照</h1><p>左侧为原 PDF，右侧为逐页 Markdown 源文。页码为物理页码，从 1 开始。此页为抽样检查，不代表全篇人工验收。</p>"""
    (args.result_dir / "review.html").write_text(
        html + "<nav>" + links + "</nav>" + "".join(sections) + "</html>",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
