# Technical choices

This document describes the final technical choices of the project and their
justifications. The complete runtime flow is documented separately in
[`architecture.md`](architecture.md).

## Contents

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

## Feature-oriented Python package

The source code uses the standard `src/warhammer_agent/` package layout and is
divided by responsibility: ingestion, embeddings, PDF RAG, SQL retrieval,
agent orchestration, and evaluation. This keeps each course requirement visible
while avoiding a shared `base/impl` hierarchy for components that do not expose
the same interface.

## Google AI Studio and Gemini

Gemini is accessed through the official `google-genai` SDK. It performs question
planning, routing, PDF reranking and answer generation, Text-to-SQL planning and
generation, and final hybrid synthesis. The Streamlit interface accepts a Google
AI Studio API key for the current session; command-line tools read
`GEMINI_API_KEY` from the environment or `.env`. Keys are never stored in Git or
run reports.

Using one backend satisfies the course requirement and allows structured JSON
responses to be validated locally. Model access and request quotas still depend
on the user's Google AI Studio account, so live evaluation is resumable.

The default runtime model is the stable `gemini-3.6-flash` release. PDF
refinement, SQL planning, routing, and answer synthesis use the same model so a
run has one explicit model version. The model remains configurable for accounts
with different Google AI Studio availability.

A shared bounded retry helper handles transient rate limits consistently across
the PDF, SQL and agent paths. It retries one 429 response only when Gemini
provides a short wait of at most 90 seconds; longer quota exhaustion is surfaced
to the caller so evaluation runs can be resumed later without blocking for hours.

## PDF parsing and corpus construction

The Core Rules PDF is parsed with Docling and stored as a versioned snapshot
before the retrieval corpus is built. The corpus builder removes navigation
noise, applies reviewed page corrections, and preserves headings, tables, lists,
rule fields, physical page numbers, and source provenance. Hash checks connect
the final records to the PDF, parsing snapshot, corrections, and corpus
configuration, so incompatible inputs stop the rebuild instead of silently
changing the index.

The versioned snapshot separates the expensive PDF parsing step from later
corpus revisions. Reviewed corrections can therefore improve difficult pages
without reparsing the complete document, while the recorded hashes keep the
result reproducible.

Complex layouts, figures, and stratagem cards are handled through reviewed text
and page-specific corrections. Captions can be retained, but the system does not
claim to understand every visual relationship in a page. The original PDF page
therefore remains the authoritative visual source and can be displayed beside a
citation in the web interface.

## Rule-aware parent-child chunking

Complete rules are stored as parent records, and only long rules are divided
into smaller retrieval children. Each child keeps its parent-relative span,
page information, and source metadata. A child can therefore provide a focused
vector match while the complete parent is restored before reranking and answer
generation.

This approach was chosen over arbitrary fixed-size chunks because rule
conditions, effects, restrictions, and exceptions should remain together.
Examples can also be linked back to their main rule, so supplementary context is
added without replacing the original retrieval ranking.

## Local Qwen embeddings and persistent Chroma

The default PDF index uses `Qwen/Qwen3-Embedding-0.6B` locally and stores vectors
in a persistent Chroma collection with cosine distance. Query instructions tell
the embedding model to retrieve passages that answer a rules question. Chroma
collections are versioned by corpus and model configuration to prevent
incompatible vectors from being mixed.

Local embeddings avoid per-query embedding API calls and remain usable after the
model is cached. The trade-off is the initial model download and local CPU,
memory, and storage use. Gemini embedding remains available as an alternative,
but it is not required by the default runtime pipeline.

## PDF Retriever design

The PDF path follows these stages:

```text
Question rewriting -> Qwen query embedding -> Chroma child retrieval
-> parent restoration -> candidate fusion -> Gemini reranking -> PDF evidence
```

Conversation history is used only when a question needs to be rewritten as a
self-contained retrieval query. Compound questions can produce a small set of
focused queries. Their results are combined with reciprocal rank fusion because
cosine scores from different queries are not directly comparable. The local
Qwen instruction frames the task as finding passages that can answer a rules
question, not as general text similarity.

Gemini then ranks the complete parent rules by their usefulness for the current
question. If rewriting or reranking fails, the pipeline keeps the available
local retrieval or fusion order instead of losing the evidence. The final PDF
evidence contains the complete rule text, section title, provenance, and
physical page numbers required for citations.

This combination was selected to balance recall, context, and answer relevance.
Vector search finds a broad local candidate set, parent restoration prevents
fragmentary rules from reaching the answer model, and reranking focuses the
final evidence on the current question. The fallbacks keep the retriever usable
when an optional Gemini refinement call is unavailable.

## Two specialised retrievers

The system keeps separate retrieval paths for the two required sources:

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

The schema catalogue first ranks tables from their documented topics and column
names, then supplies only the most relevant tables and their approved inferred
relationships. Gemini produces a structured plan containing the requested
metric, dimensions, filters, candidate tables, joins, assumptions, and possible
ambiguities. The plan is checked against the selected schema before it can be
used to generate SQL. If a required entity or interpretation is missing, the
retriever returns a focused clarification instead of guessing.

The second Gemini call generates one parameterised SQLite query from the
approved plan. Local checks verify the tables, columns, joins, operators,
placeholders, filter values, output aliases, and allowed functions. SQLGlot
restricts the result to one `SELECT` or `WITH ... SELECT` statement, while
SQLite is opened in read-only and query-only modes with authorisation, row, and
execution-time limits. The returned columns and rows are converted into
structured evidence that the agent can cite alongside PDF evidence.

This design allows natural-language access to the course database without
giving generated SQL write access. It is more complex than directly executing
model output, but provides explicit planning, validation, and reproducible query
evidence.

## LangGraph orchestration and persistent sessions

LangGraph represents planning, routing, retrieval, synthesis, and clarification
as explicit graph nodes. The router chooses the smallest sufficient source set:
rules, database, hybrid, or clarification. Persistent checkpoints retain
conversation context, while previous messages help resolve references but are
never treated as factual evidence.

The runtime flow is `planning -> routing -> retrieval -> evidence collection ->
grounded synthesis -> citation validation`. A hybrid question runs both
retrievers before synthesis, while an underspecified question follows the
clarification path without inventing a PDF rule or database entity.

The explicit graph makes routing decisions and failures inspectable. It adds
some orchestration code compared with a single prompt, but it matches the
multi-source workflow and supports resumable conversations.

## Grounded answers and citations

Both retrievers return structured evidence. The final answer may cite PDF pages
and database tables in a shared `[S1]` numbering space. Local validation rejects
unknown or inconsistent citation identifiers. Retrieved content is treated as
untrusted evidence rather than instructions.

Citation validation proves that a citation refers to supplied evidence; it does
not by itself prove complete semantic entailment. This is assessed separately by
the evaluation pipeline and human review.

## Streamlit interface

Streamlit provides a small local chat interface over the same agent used by the
CLI. It exposes session creation, model selection, API-key entry, answers,
citations, route information, and useful failure messages without duplicating
retrieval logic. PDF citations can optionally render their complete source pages
from the local rulebook. These previews are never sent to Gemini and do not imply
that the model interpreted the page image.

Streamlit was selected for a lightweight course demonstration. The project does
not require a separate web server, authentication system, or hosted deployment.

## Evaluation strategy

The frozen evaluation dataset contains rules, database, hybrid, and
clarification questions. Deterministic metrics measure routing, execution trace,
expected evidence or SQL values, required answer facts, and citations. Reports
are stored as JSON and Markdown, and interrupted live runs can be resumed after
API quota resets.

Deterministic checks make regressions reproducible, while an optional independent
LLM judge and human review can assess semantic faithfulness and answer relevance.
The final live evaluation should be run only after the implementation and
documentation are frozen.
