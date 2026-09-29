# Warhammer Agent

Parse and clean Warhammer rule PDFs with Docling. RAG retrieval and a SQL chatbot are planned.

## Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
```

Place `Core Rules.pdf` in `data/` to run PDF processing. The PDF and `wahadb.sqlite` are local inputs and are not included in Git. Correction rules require matching source hashes.

## Usage

Run from the project root:

```bash
uv run --locked python scripts/probe_pdf.py "data/Core Rules.pdf"
uv run --locked python scripts/parse_pdf.py "data/Core Rules.pdf"
uv run --locked python scripts/clean_pdf.py "data/Core Rules.pdf"
uv run --locked python scripts/build_pdf_review.py "data/Core Rules.pdf"
```

Use `--pages 9 41 42` with `clean_pdf.py` to select pages. Use `--output-dir PATH` with processing scripts to keep separate outputs; the review script uses `--result-dir PATH`.

The parser downloads model weights on first use. Outputs are saved under `reports/`.

## Dify Test File

Upload [core_rules_26_units_test.txt](reports/exports/core_rules_26_units_test.txt) and use `<<<RULE_UNIT>>>` as the separator, with zero overlap.

The file contains 26 rule groups. Dify may split long groups further. Some pages still use original Docling text; this is a test corpus, not a fully reviewed knowledge base.

## Structure

- `src/warhammer_agent/ingestion/`: parsing, cleanup, and review logic.
- `scripts/`: command-line entry points.
- `config/corrections/core_rules/`: reviewed page corrections and source hashes.
- `reports/`: parsed data, cleaned pages, images, and test exports.
- `tests/`: unit and integration tests.
- `docs/`: [ingestion guide](docs/ingestion.md), review notes, and [SQL data dictionary](docs/sql_data_dictionary.md).

## Checks

```bash
uv run --locked python -m pytest -q
uv run --locked ruff check src scripts tests
uv run --locked ruff format --check src scripts tests
```

Integration tests use the included Docling JSON, correction configs, and cleaned images.
