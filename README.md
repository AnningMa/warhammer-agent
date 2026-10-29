# Warhammer Agent

An English-language Warhammer 40,000 assistant grounded in two
course-provided sources:

- the Core Rules PDF for general rules and mechanics;
- a SQLite datasheet database for units, profiles, weapons, abilities and other
  structured records.

A LangGraph agent routes each question to the PDF retriever, the read-only SQL
retriever, or both. It then returns a grounded answer with PDF-page and/or
database citations. The project also includes a Streamlit chat, persistent
sessions, automated tests and a resumable end-to-end evaluation pipeline.

## Contributors

- Anning Ma (student number: 22404528)
- Yiwei ZUO (student number: 22400141)

## Main features

- source-traceable PDF parsing and reviewed rule blocks;
- local Qwen embeddings with a persistent Chroma parent-child index;
- conversational PDF retrieval, fusion, Gemini reranking and cited generation;
- schema-aware, validated and read-only Text-to-SQL retrieval;
- LangGraph routing across rules, database, hybrid and clarification paths;
- a local Streamlit chat with cited PDF-page previews and a Google AI Studio key;
- deterministic and optional LLM-assisted evaluation over 12 frozen cases.

## Quick start

Requirements:

- Python 3.10 or later;
- [`uv`](https://docs.astral.sh/uv/);
- a Google AI Studio API key for Gemini generation.

The two course-provided sources, `data/Core Rules.pdf` and
`data/wahadb.sqlite`, are versioned in the repository and ready after cloning.
See [`data/README.md`](data/README.md) for their roles.

Install all runtime dependencies:

```bash
uv sync --locked --extra agent --extra qwen --extra chroma --extra gemini --extra ui
```

Build the local Qwen/Chroma parent-child index when `storage/chroma/` is not
already available:

```bash
uv run --locked --extra qwen --extra chroma python scripts/embed_parent_child.py
```

Start the web chat and enter a Google AI Studio key in the sidebar:

```bash
uv run --locked --extra agent --extra qwen --extra chroma --extra gemini --extra ui \
  streamlit run scripts/chat_app.py
```

The command-line tools read `GEMINI_API_KEY` from the environment or `.env`.
Copy `.env.example` to `.env`, add the key, and run:

```bash
uv run --locked --extra agent --extra qwen --extra chroma --extra gemini \
  python scripts/ask_agent.py \
  --question "How does Deep Strike work?" \
  --model gemini-3-flash-preview
```

## Entry points

| Entry point | Purpose |
|---|---|
| `scripts/chat_app.py` | Streamlit chat over the unified agent |
| `scripts/ask_agent.py` | Unified PDF, SQL and hybrid CLI |
| `scripts/ask_rules.py` | Standalone PDF RAG CLI |
| `scripts/ask_database.py` | Standalone read-only SQL CLI |
| `scripts/evaluate_agent.py` | Resumable 12-case end-to-end evaluation |
| `scripts/build_corpus.py` | Rebuild the reviewed PDF rule corpus |
| `scripts/embed_parent_child.py` | Build or query the default PDF vector index |

## Repository structure

| Path | Responsibility |
|---|---|
| `src/warhammer_agent/ingestion/` | PDF parsing, cleaning, corrections and rule blocks |
| `src/warhammer_agent/embeddings/` | Qwen/Gemini embeddings and Chroma persistence |
| `src/warhammer_agent/rag/` | PDF retrieval, rewriting, reranking, generation and citations |
| `src/warhammer_agent/sql/` | Schema selection, safe Text-to-SQL and read-only execution |
| `src/warhammer_agent/agent/` | LangGraph routing, evidence packing, synthesis and sessions |
| `src/warhammer_agent/evaluation/` | Dataset loading, metrics, reports and resumable runs |
| `scripts/` | User-facing build, query, chat and evaluation commands |
| `config/` | Versioned runtime configuration and correction policies |
| `reports/` | Versioned reviewed corpus and parent-child records |
| `tests/unit/` | Fast isolated component tests |
| `tests/integration/` | Cross-component and persistence tests |
| `tests/eval_cases/` | Frozen retrieval and end-to-end evaluation datasets |

## Documentation

| Document | Content |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Complete system flow and module interaction |
| [`docs/technical_choices.md`](docs/technical_choices.md) | Final technical choices, justifications and trade-offs |
| [`docs/ingestion.md`](docs/ingestion.md) | PDF parsing, corrections, corpus building and provenance |
| [`docs/sql_data_dictionary.md`](docs/sql_data_dictionary.md) | SQLite tables, columns and inferred relationships |
| [`docs/evaluation.md`](docs/evaluation.md) | Evaluation dataset, metrics, storage and resume policy |

## Data and reproducibility

The repository versions the two course-provided sources and the material
required to understand and reproduce the processing choices:

- `data/Core Rules.pdf`: original rulebook used for citations and page previews;
- `data/wahadb.sqlite`: unit datasheet database queried read-only;
- `data/core_rules.docling.json`: immutable parsing snapshot;
- `config/corrections/core_rules/`: reviewed page corrections;
- `config/index_policy.json`: excluded-page policy;
- `config/corpus_relations.json`: verified cross-page relationships;
- `reports/core_rules.txt`: readable reviewed rules;
- `reports/index_blocks.jsonl`: 228 complete source-traceable rule blocks;
- `reports/parent_child_blocks.jsonl`: parent-child retrieval records.

Runtime artifacts remain local:

- `storage/chroma/`: persistent vector index;
- `storage/models/`: cached Qwen weights;
- `storage/agent/`: LangGraph checkpoints and run diagnostics;
- `storage/evaluation/`: resumable live evaluation records and reports.

API keys, model caches, vector indexes and runtime records are excluded from
Git.

## How the system answers a question

1. Gemini rewrites the latest question when conversation context is needed and
   produces focused subquestions.
2. The LangGraph router selects `rules`, `database`, `hybrid` or
   `clarification`.
3. The PDF path embeds the query locally, retrieves Chroma children, restores
   complete parent rules and reranks candidates with Gemini.
4. The database path selects a relevant schema, creates a query plan, generates
   parameterised SQL, validates it locally and executes SQLite read-only.
5. Gemini synthesises one English answer from the supplied evidence.
6. Local checks validate citation identifiers before the answer is returned.

Conversation history may resolve references, but it is not factual evidence.
PDF text and SQL rows are treated as evidence rather than instructions.

## Verification

Run the local checks from the repository root:

```bash
uv run --locked ruff check src scripts tests
uv run --locked ruff format --check src scripts tests
uv run --locked --extra agent --extra qwen --extra chroma --extra gemini \
  python -m pytest -q
```

The automated test suite does not require a live Gemini evaluation. It covers
corpus integrity, Chroma persistence, retrieval, SQL safety and execution,
LangGraph routes and sessions, credentials, the web interface and evaluation
metrics.

## End-to-end evaluation

The frozen dataset in `tests/eval_cases/agent.json` contains 12 rules, database,
hybrid and clarification questions, including the four examples in the project
brief. Run one live case before spending quota on the complete dataset:

```bash
uv run --locked --extra agent --extra qwen --extra chroma --extra gemini \
  python scripts/evaluate_agent.py \
  --case-id rules_deep_strike \
  --model gemini-3-flash-preview
```

Run the complete deterministic evaluation after the implementation and
documentation are frozen:

```bash
uv run --locked --extra agent --extra qwen --extra chroma --extra gemini \
  python scripts/evaluate_agent.py \
  --model gemini-3-flash-preview
```

Each case is saved immediately under `storage/evaluation/runs/<run-id>/cases/`.
If API quota interrupts the run, resume it without repeating successful cases:

```bash
uv run --locked --extra agent --extra qwen --extra chroma --extra gemini \
  python scripts/evaluate_agent.py \
  --resume storage/evaluation/runs/<run-id> \
  --model gemini-3-flash-preview
```

See [`docs/evaluation.md`](docs/evaluation.md) for metric definitions and the
optional independent LLM judge.

## Current limitations

- Figure understanding is limited to extracted captions and reviewed textual
  context; cited-page previews expose the original visual source but are not
  interpreted by the model.
- Gemini model access, latency and quota depend on the Google AI Studio account.
- The SQL retriever rejects unsafe or invalid queries and does not automatically
  repair them.
- Citation validation checks that claims refer to supplied evidence identifiers;
  semantic faithfulness is also assessed by evaluation and human review.
