# Technical choices

This document explains the main technical choices we made for the project and
why we made them. The complete runtime flow is documented separately in
[`architecture.md`](architecture.md).

## Contents

- [Design overview](#design-overview)
- [Feature-oriented Python package](#feature-oriented-python-package)
- [Google AI Studio and Gemini](#google-ai-studio-and-gemini)
- [PDF parsing and corpus construction](#pdf-parsing-and-corpus-construction)
- [Rule-aware parent-child chunking](#rule-aware-parent-child-chunking)
- [Local Qwen embeddings and persistent Chroma](#local-qwen-embeddings-and-persistent-chroma)
- [PDF Retriever design](#pdf-retriever-design)
- [Two specialised retrievers](#two-specialised-retrievers)
- [SQL Retriever design](#sql-retriever-design)
- [LangGraph orchestration and persistent sessions](#langgraph-orchestration-and-persistent-sessions)
- [Grounded answers and citations](#grounded-answers-and-citations)
- [Streamlit interface](#streamlit-interface)
- [Evaluation strategy](#evaluation-strategy)

## Design overview

| Component | Main design | Problem addressed |
|---|---|---|
| LLM backend | Gemini is accessed through Google AI Studio with structured JSON responses and local validation. | Keeps one configurable LLM backend across routing, retrieval refinement, SQL generation and answer synthesis. |
| PDF parsing | Docling creates a versioned parsing snapshot, followed by reviewed corrections and provenance checks. | Handles complex rulebook layouts while keeping corpus construction reproducible. |
| Chunking | Complete rules are stored as parents, while long rules are divided into smaller retrieval children. | Improves retrieval precision without separating conditions, effects, restrictions and exceptions in the final evidence. |
| Embeddings and index | Local Qwen embeddings are stored in versioned Chroma collections using cosine distance. | Avoids repeated embedding API calls and prevents incompatible corpus or model versions from being mixed. |
| PDF Retriever | Conversational rewriting, vector retrieval, parent restoration, candidate fusion and Gemini reranking are applied in sequence. | Supports follow-up and compound questions while returning complete and relevant rules. |
| SQL Retriever | Relevant schemas are selected before Gemini produces a validated query plan and parameterised SQL for read-only execution. | Reduces schema confusion and prevents unsafe or unsupported generated queries from reaching SQLite. |
| Agent and chat | LangGraph routes questions to the PDF Retriever, SQL Retriever, both retrievers, or a clarification response. | Provides one conversation flow for rules, database and hybrid questions without guessing missing information. |
| Grounding and citations | Both retrievers return structured evidence, followed by grounded synthesis and local citation validation. | Makes answers traceable to PDF pages or database tables and rejects unsupported citation identifiers. |
| Evaluation | A fixed twelve-case dataset evaluates rules, database, hybrid and clarification routes with deterministic metrics. | Detects regressions across the complete system and allows interrupted API-based runs to be resumed. |

## Feature-oriented Python package

We organised the source code as a standard `src/warhammer_agent/` package and
divided it by responsibility: ingestion, embeddings, PDF RAG, SQL retrieval,
agent orchestration, and evaluation. This keeps module responsibilities clear
and makes the components easier to test and maintain. It also avoids a shared
`base/impl` hierarchy for components that do not expose the same interface.

## Google AI Studio and Gemini

We use Gemini through the official `google-genai` SDK for question planning,
routing, PDF reranking and answer generation, Text-to-SQL planning and
generation, and final hybrid synthesis. The Streamlit interface accepts a Google
AI Studio API key for the current session; command-line tools read
`GEMINI_API_KEY` from the environment or `.env`. Keys are never stored in Git or
run reports.

Using one backend keeps model configuration consistent and allows structured
JSON responses to be validated locally. Model access and request quotas still
depend on the user's Google AI Studio account, so live evaluation is resumable.

The default runtime configurations use `gemini-3.6-flash` for PDF refinement,
SQL planning, routing, and answer synthesis. The Streamlit interface and
evaluation runner apply their model override to both retrieval paths. In the
unified command-line interface, `--model` overrides routing, PDF refinement, and
synthesis, while SQL retains the model configured in `config/sql.json`. This
keeps the default consistent while allowing each path to be configured
explicitly.

A shared bounded retry helper handles transient rate limits consistently across
the PDF, SQL and agent paths. It retries one 429 response only when Gemini
provides a short wait of at most 90 seconds; longer quota exhaustion is surfaced
to the caller so evaluation runs can be resumed later without blocking for hours.

## PDF parsing and corpus construction

We parse the Core Rules PDF with Docling and store the result as a versioned
snapshot before building the retrieval corpus. Our corpus builder removes
navigation noise, applies reviewed page corrections, and preserves headings,
tables, lists, rule fields, physical page numbers, and source provenance. Hash
checks connect the final records to the PDF, parsing snapshot, corrections, and
corpus configuration, so incompatible inputs stop the rebuild instead of
silently changing the index.

The versioned snapshot separates the expensive PDF parsing step from later
corpus revisions. Reviewed corrections can therefore improve difficult pages
without reparsing the complete document, while the recorded hashes keep the
result reproducible.

Complex layouts, figures, and stratagem cards are handled through reviewed text
and page-specific corrections. Captions can be retained, but the system does not
claim to understand every visual relationship in a page. The original PDF page
therefore remains the authoritative visual source and can be displayed beside a
citation in the web interface.

The complete rebuild procedure, generated files, and provenance checks are
documented in [`ingestion.md`](ingestion.md).

## Rule-aware parent-child chunking

We store complete rules as parent records and divide only long rules into
smaller retrieval children. Each child keeps its parent-relative span, page
information, and source metadata. A child can therefore provide a focused
vector match while the complete parent is restored before reranking and answer
generation.

We chose this approach over arbitrary fixed-size chunks because rule
conditions, effects, restrictions, and exceptions should remain together.
Examples can also be linked back to their main rule, so supplementary context is
added without replacing the original retrieval ranking.

## Local Qwen embeddings and persistent Chroma

We use `Qwen/Qwen3-Embedding-0.6B` locally for the default PDF index and store
its vectors in a persistent Chroma collection with cosine distance. Query
instructions tell the embedding model to retrieve passages that answer a rules
question. Chroma collections are versioned by corpus and model configuration to
prevent incompatible vectors from being mixed.

Local embeddings avoid per-query embedding API calls and remain usable after the
model is cached. The trade-off is the initial model download and local CPU,
memory, and storage use. Gemini embedding remains available as an alternative,
but it is not required by the default runtime pipeline.

We did not add a separate BM25 index because the rule-aware dense retrieval and
Gemini reranking already met our evaluation targets. Keeping one persistent
retrieval index also makes the local setup and index versioning simpler.

For first-time setup, we support either building this index locally or importing
a precomputed portable archive. A published SHA-256 checksum verifies the
downloaded archive. The import then validates its file inventory, embedded file
hashes, corpus hash, model configuration, record identities, and vector values
before writing Chroma. The archive does not include Qwen model weights, so the
same local model is still used to embed each user query.

## PDF Retriever design

The PDF path follows these stages:

```text
Question rewriting -> Qwen query embedding -> Chroma child retrieval
-> parent restoration -> candidate fusion -> Gemini reranking -> PDF evidence
```

We use conversation history only when a question needs to be rewritten as a
self-contained retrieval query. Compound questions can produce a small set of
focused queries. We combine their results with reciprocal rank fusion because
cosine scores from different queries are not directly comparable. The local
Qwen instruction frames the task as finding passages that can answer a rules
question, not as general text similarity.

Gemini then ranks the complete parent rules by their usefulness for the current
question. If rewriting or reranking fails, the pipeline keeps the available
local retrieval or fusion order instead of losing the evidence. The final PDF
evidence contains the complete rule text, section title, provenance, and
physical page numbers required for citations.

We selected this combination to balance recall, context, and answer relevance.
Vector search finds a broad local candidate set, parent restoration prevents
fragmentary rules from reaching the answer model, and reranking focuses the
final evidence on the current question. The fallbacks keep the retriever usable
when an optional Gemini refinement call is unavailable.

## Two specialised retrievers

We keep separate retrieval paths for the two data sources:

- the PDF RAG pipeline retrieves and reranks Core Rules passages;
- the SQL pipeline queries structured datasheet information.

Keeping them separate preserves source-specific validation and citations. The
LangGraph agent selects the PDF path, the database path, or both, then combines
their evidence in one answer.

## SQL Retriever design

The SQL path follows a separate, schema-aware process:

```text
Question -> relevant schema selection -> structured query plan
-> parameterised SQL generation -> local safety validation
-> read-only SQLite execution -> structured SQL evidence
```

We first use the schema catalogue to rank tables from their documented topics
and column names, then supply only the most relevant tables and their approved
inferred relationships. Gemini produces a structured plan containing the
requested metric, dimensions, filters, candidate tables, joins, assumptions,
and possible ambiguities. The plan is checked against the selected schema before
it can be used to generate SQL. If a required entity or interpretation is
missing, the retriever returns a focused clarification instead of guessing.

The second Gemini call generates one parameterised SQLite query from the
approved plan. Local checks verify the tables, columns, joins, operators,
placeholders, filter values, output aliases, and allowed functions. SQLGlot
restricts the result to one `SELECT` or `WITH ... SELECT` statement, while
SQLite is opened in read-only and query-only modes with authorisation, row, and
execution-time limits. The returned columns and rows are converted into
structured evidence that the agent can cite alongside PDF evidence.

We chose this design to allow natural-language access to the datasheet database
without giving generated SQL write access. It is more complex than directly
executing model output, but provides explicit planning, validation, and
reproducible query evidence.

## LangGraph orchestration and persistent sessions

We use LangGraph to represent planning, routing, retrieval, synthesis, and
clarification as explicit graph nodes. The router chooses the smallest
sufficient source set: rules, database, hybrid, or clarification. Persistent
checkpoints retain conversation context, while previous messages help resolve
references but are never treated as factual evidence.

The runtime flow is `planning -> routing -> retrieval -> evidence collection ->
grounded synthesis -> citation validation`. A hybrid question runs both
retrievers before synthesis, while an underspecified question follows the
clarification path without inventing a PDF rule or database entity.

The explicit graph makes routing decisions and failures inspectable. It adds
some orchestration code compared with a single prompt, but it matches the
multi-source workflow and supports resumable conversations.

## Grounded answers and citations

We require both retrievers to return structured evidence. The final answer may
cite PDF pages and database tables in a shared `[S1]` numbering space. Local
validation rejects unknown or inconsistent citation identifiers. Retrieved
content is treated as untrusted evidence rather than instructions.

Citation validation proves that a citation refers to supplied evidence; it does
not by itself prove complete semantic entailment. This is assessed separately by
the evaluation pipeline and human review.

## Streamlit interface

We chose Streamlit to provide a small local chat interface over the same agent
used by the CLI. It exposes session creation, model selection, API-key entry,
answers, citations, route information, and useful failure messages without
duplicating retrieval logic. PDF citations can optionally render their complete
source pages from the local rulebook. These previews are never sent to Gemini
and do not imply that the model interpreted the page image.

This choice gives us a lightweight project demonstration. The project does not
require a separate web server, authentication system, or hosted deployment.

## Evaluation strategy

We built a frozen twelve-case evaluation dataset containing four rules
questions, four database questions, three hybrid questions, and one
clarification question. Deterministic metrics evaluate routing decisions,
execution traces, retrieved evidence, SQL results, required answer facts, and
citation validity. This makes the results reproducible and helps detect
regressions.

An optional independent LLM judge and human review can also be used to assess
faithfulness and answer relevance. The detailed dataset design, metrics,
acceptance thresholds, and resume policy are documented in
[`evaluation.md`](evaluation.md). Final measured results are available in
[`evaluation_results.md`](evaluation_results.md).
