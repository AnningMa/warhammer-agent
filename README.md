# Warhammer Agent

PDF 规则解析、人工核验清洗与后续 RAG / SQL chatbot 项目。

## 安装与运行

在仓库根目录运行 `uv sync --locked`。

```bash
uv run --locked python scripts/probe_pdf.py "data/Core Rules.pdf"
uv run --locked python scripts/parse_pdf.py "data/Core Rules.pdf"
uv run --locked python scripts/clean_pdf.py "data/Core Rules.pdf"
uv run --locked python scripts/build_pdf_review.py "data/Core Rules.pdf"
```

单页或部分页面清洗：

```bash
uv run --locked python scripts/clean_pdf.py "data/Core Rules.pdf" --pages 9 41 42
```

清洗入口默认读取 `config/corrections/core_rules/manifest.json`。用 `--output-dir` 指定独立输出目录，避免覆盖已审查产物。输入变化导致哈希不匹配时必须重新审查。

## 目录

- `src/warhammer_agent/ingestion/`：解析、清洗、审查实现；`handlers/` 保留不同历史修正格式的处理器。
- `scripts/`：四个薄命令行入口。
- `config/corrections/core_rules/`：36 页人工修正规则、处理器类型、来源哈希与清单。
- `data/`：原始 PDF 和 SQLite 数据库。
- `reports/`：解析、清洗与预览产物；原始 JSON 是清洗审计依据。
- `docs/ingestion.md`：处理流程、保留策略与当前边界。
- `docs/reviews/`：历史人工检查记录。
- `docs/sql_data_dictionary.md`：数据库说明。
- `tests/unit/`：独立逻辑测试；`tests/integration/`：真实配置与文档回归检查。

## 验证

```bash
uv run --locked python -m pytest -q
uv run --locked ruff check src scripts tests
uv run --locked ruff format --check src scripts tests
```

集成测试依赖本仓库保留的原始 Docling JSON、人工配置及清洗图片；它们不是脱离数据的单元测试。

## Source inputs after cloning

The original PDF and business database are local inputs and are not included in Git.
Place the matching `Core Rules.pdf` and `wahadb.sqlite` under `data/` when running
PDF conversion/cleanup or future SQL queries. The checked-in correction configs
verify the PDF and Docling snapshot hashes; a different source requires review.
The original Docling JSON and cleaned review artifacts are included so the current
test suite and exported text can be inspected without rerunning conversion.

For Dify testing, upload `reports/exports/core_rules_26_units_test.txt`;
use `<<<RULE_UNIT>>>` as the separator. This export contains 26 rule groups,
not a finalized parent/child retrieval corpus.
