# Technical choices

This document describes the final technical choices of the project and their
justifications. The complete runtime flow is documented separately in
[`architecture.md`](architecture.md).

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

## PDF ingestion and rule-aware chunks

The Core Rules PDF is converted into source-traceable rule blocks. Headings,
tables, lists, rule fields, page numbers, and reviewed corrections are retained.
Complete rules are used as parent records; only long rules are split into
retrieval children. Retrieval therefore operates on focused text while answers
receive the complete rule and its source metadata.

This approach was chosen over arbitrary fixed-size chunks because rule
conditions, effects, restrictions, and exceptions should remain together. Image
understanding is limited to extracted captions and reviewed textual context; the
original PDF page remains the authoritative visual source.

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

## Two specialised retrievers

The system keeps separate retrieval paths for the two required sources:

- the PDF RAG pipeline retrieves and reranks Core Rules passages;
- the SQL pipeline queries structured datasheet information.

Keeping them separate preserves source-specific validation and citations. The
LangGraph agent selects the PDF path, the database path, or both, then combines
their evidence in one answer.

## Safe Text-to-SQL

The SQL retriever first selects a small relevant schema and asks Gemini for a
structured query plan, then generates parameterised SQLite SQL. SQLGlot and
local checks restrict execution to one read-only `SELECT` or `WITH ... SELECT`
statement. SQLite is opened in read-only mode and query limits are applied.

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
retrieval logic.

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
