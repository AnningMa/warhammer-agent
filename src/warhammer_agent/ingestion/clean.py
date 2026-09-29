"""Unified CLI for source-specific, reviewed page corrections."""

import argparse
import importlib
import json
import sys
from pathlib import Path

from .validation import verify_hash

HANDLERS = {
    "blocks",
    "regions",
    "text",
    "figure",
    "figures",
    "visibility",
    "table",
    "rule_table",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/corrections/core_rules/manifest.json"),
    )
    parser.add_argument("--rules", type=Path, nargs="+")
    parser.add_argument("--pages", type=int, nargs="+")
    parser.add_argument(
        "--document", type=Path, default=Path("reports/docling/document.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/cleaned"))
    args = parser.parse_args()
    if args.rules:
        paths = args.rules
    else:
        manifest = json.loads(args.manifest.read_text())
        verify_hash(args.pdf, manifest["source_sha256"])
        verify_hash(args.document, manifest["document_sha256"])
        paths = [args.manifest.parent / item["rules"] for item in manifest["pages"]]
    selected = [(p, json.loads(p.read_text())) for p in paths]
    if args.pages:
        selected = [(p, r) for p, r in selected if r["page"] in args.pages]
        missing = set(args.pages) - {r["page"] for _, r in selected}
        if missing:
            parser.error(f"No reviewed corrections for pages: {sorted(missing)}")
    for path, rules in selected:
        handler = rules["handler"]
        if rules.get("schema_version") != 1 or handler not in HANDLERS:
            parser.error(f"Unsupported correction schema or handler: {path}")
        module = importlib.import_module(
            ".regions" if handler == "regions" else ".handlers." + handler, __package__
        )
        argv = ["clean_pdf", "--rules", str(path), "--output-dir", str(args.output_dir)]
        if handler != "text":
            argv.append(str(args.pdf))
        if handler != "regions":
            argv.extend(["--document", str(args.document)])
        previous = sys.argv
        try:
            sys.argv = argv
            module.main()
        finally:
            sys.argv = previous


if __name__ == "__main__":
    main()
