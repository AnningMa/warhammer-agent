# RAG and SQL Agent — Engineering Instructions

## Project Goal

Build a production-oriented conversational agent that answers user questions through controlled routing between two primary capabilities:

1. **PDF RAG route** — retrieve relevant passages from indexed PDF documents and answer with traceable citations.
2. **SQL route** — translate an analytical question into safe, read-only SQL, execute it, and explain the result.

The system should also support:

- **Hybrid requests**, where a definition or rule is retrieved from a PDF and then applied to database data.
- **Clarification requests**, where the user's intent, metric, entity, or time range is too ambiguous to execute safely.

Prefer a deterministic, observable workflow over an unconstrained autonomous agent.

## Core Design Principles

- Treat the language model as a planner and generator, not as a security boundary.
- Keep routing, retrieval, SQL generation, validation, execution, and answer synthesis as separate components.
- Make every workflow step independently testable.
- Return evidence and assumptions alongside answers.
- Never invent missing document facts, schema details, query results, or citations.
- Fail safely when retrieval confidence is low or SQL intent is ambiguous.
- Use structured model outputs wherever a downstream program consumes the response.
- Keep infrastructure choices behind interfaces so that models, vector stores, and databases can be replaced.

## Recommended Architecture

Use the following logical flow:

```text
User Request
    -> Request Normalization
    -> Router
        -> PDF Retrieval Route
        -> SQL Route
        -> Hybrid Route
        -> Clarification Route
    -> Answer Synthesizer
    -> Response with evidence, assumptions, and diagnostics
```

The router must return a structured decision containing at least:

```json
{
  "route": "pdf | sql | hybrid | clarify",
  "confidence": 0.0,
  "rewritten_question": "string",
  "reason": "string"
}
```

Do not expose chain-of-thought. The `reason` field should contain only a short operational explanation suitable for logs.

## Suggested Repository Structure

```text
app/
  main.py
  config.py
  api/
    routes.py
    schemas.py
  agent/
    graph.py
    state.py
    router.py
    prompts.py
    synthesizer.py
  retrieval/
    ingestion.py
    chunking.py
    embeddings.py
    vector_store.py
    retriever.py
    reranker.py
  sql/
    schema_loader.py
    schema_retriever.py
    planner.py
    generator.py
    validator.py
    executor.py
    formatter.py
  llm/
    client.py
    structured_output.py
  common/
    errors.py
    types.py
  observability/
    logging.py
    tracing.py
scripts/
  ingest_pdfs.py
  inspect_schema.py
tests/
  eval_cases/
  test_router.py
  test_retrieval.py
  test_sql_validation.py
```

Keep domain logic out of API handlers. API handlers should validate input, call the application workflow, and serialize the result.

## Shared Agent State

Use a typed state object. It should be explicit enough to inspect after every workflow step.

Recommended fields:

```text
request_id
user_question
conversation_context
route
route_confidence
rewritten_question
retrieved_documents
schema_context
query_plan
generated_sql
sql_result
evidence
assumptions
warnings
errors
final_answer
```

Avoid storing credentials, full database connection strings, or unnecessary sensitive row data in the state or logs.

## PDF RAG Route

The PDF route must return evidence, not only generated prose.

Each retrieved item should preserve:

- Document identifier and filename
- Page number
- Section or heading, when available
- Chunk text
- Retrieval and reranking scores
- Document version or ingestion timestamp
- Relevant access-control metadata

Recommended retrieval flow:

```text
Question rewriting
    -> metadata filtering
    -> hybrid retrieval (semantic + keyword)
    -> reranking
    -> evidence threshold check
    -> grounded answer generation
```

Chunk documents along semantic boundaries where possible. Preserve headings and page associations. Treat tables separately when plain-text extraction would destroy their meaning.

For scanned documents, use OCR and record that OCR was used. Low-confidence OCR content should produce a warning.

If the retrieved evidence does not support a reliable answer, say that the available documents are insufficient. Do not fill gaps using general model knowledge unless the product explicitly allows and clearly labels it.

## SQL Route

Do not implement the SQL route as a single `question -> SQL -> execute` call.

Use this sequence:

```text
Question normalization
    -> metric and dimension identification
    -> relevant schema retrieval
    -> structured query plan
    -> SQL generation
    -> AST-based validation
    -> optional EXPLAIN or bounded dry run
    -> read-only execution
    -> result validation
    -> natural-language explanation
```

The query plan should make intent inspectable before SQL generation. It should include, when relevant:

- Metric
- Dimensions
- Filters
- Time range and timezone
- Aggregation grain
- Candidate tables
- Join assumptions
- Business-definition assumptions

Only provide the model with relevant schema context. Include table and column descriptions, relationships, metric definitions, allowed values, and representative non-sensitive examples when useful.

### Mandatory SQL Safety Rules

- Connect with a dedicated read-only database account.
- Permit only a single read-only query.
- Allow `SELECT` and safe `WITH ... SELECT` forms only.
- Reject DDL, DML, administrative commands, stored procedure calls, and multi-statement input.
- Validate parsed SQL syntax or AST; do not rely only on keyword matching.
- Enforce allowed schemas, tables, columns, and functions.
- Apply a query timeout and result-row limit.
- Apply database-specific resource or scan limits where available.
- Parameterize user-provided values whenever possible.
- Do not let model-generated SQL bypass the validator.
- Limit automatic repair attempts and record each attempt.
- Never expose database credentials or confidential schema metadata to the user.

Treat successful execution as insufficient proof of correctness. Validate time boundaries, joins, aggregation grain, null handling, duplicate amplification, and metric definitions.

## Hybrid Route

Use the hybrid route when the question requires both unstructured policy knowledge and structured data.

Preferred sequence:

```text
Retrieve PDF evidence
    -> extract a structured business definition
    -> validate or clarify the definition
    -> map the definition to approved schema fields
    -> create and validate SQL
    -> execute query
    -> synthesize an answer using both evidence types
```

Do not paste raw PDF text directly into executable SQL. Convert relevant policy content into an explicit intermediate representation first. Preserve the source page for every derived condition.

## Clarification Route

Ask a focused clarification question when proceeding would require a material assumption, including:

- Missing time range
- Ambiguous metric or business definition
- Unclear entity or population
- Multiple plausible database fields
- Conflicting PDF definitions
- A request that appears to exceed the user's data permissions

Ask only for information required to continue. Do not ask the user to choose implementation details that the system can safely infer.

## Response Contract

The application response should support this shape:

```json
{
  "answer": "string",
  "route": "pdf | sql | hybrid | clarify",
  "confidence": 0.0,
  "citations": [],
  "sql": "string or null",
  "assumptions": [],
  "warnings": [],
  "request_id": "string"
}
```

PDF answers must cite document and page. SQL answers should expose the executed query only when product policy and user permissions allow it. Internally, always retain the validated query and execution metadata for audit and debugging.

Clearly distinguish among:

- Facts supported by PDF evidence
- Facts computed from database results
- Assumptions made by the system
- Limitations or incomplete evidence

## Prompt and Model Guidelines

- Store prompts in dedicated modules or versioned prompt files.
- Require schema-validated structured output for routing and query planning.
- Include only the context needed for the current step.
- Do not place authorization or safety enforcement solely in prompts.
- Keep model-provider code behind a small interface.
- Set explicit timeouts and bounded retry policies.
- Record model name, prompt version, latency, and token usage when permitted.
- Never log secrets or unrestricted document/database content.

## Error Handling

Define typed errors for at least:

- Unsupported or ambiguous request
- Retrieval failure
- Insufficient evidence
- Schema retrieval failure
- SQL generation failure
- SQL validation rejection
- Query timeout
- Database execution failure
- Authorization failure
- Model provider failure

Return safe, actionable messages to users. Preserve technical diagnostics in internal logs, keyed by `request_id`.

## Testing Requirements

Add tests at three levels:

1. **Unit tests** for routing, chunking, schema selection, SQL validation, citation formatting, and error mapping.
2. **Integration tests** for PDF ingestion/retrieval and read-only database execution.
3. **Evaluation cases** covering answer quality and end-to-end behavior.

The evaluation set must include:

- Clear PDF-only questions
- Clear SQL-only questions
- Hybrid questions
- Ambiguous questions requiring clarification
- Questions with no supporting document evidence
- Invalid or adversarial SQL requests
- Prompt-injection text inside PDFs
- Unauthorized data requests
- Incorrect join and aggregation traps
- Empty, null-heavy, and very large query results

Measure at least:

- Route accuracy
- Retrieval recall and citation correctness
- SQL execution accuracy
- SQL semantic correctness
- Grounded-answer accuracy
- Clarification quality
- Unsafe-query rejection rate
- Latency and cost

For SQL evaluations, compare more than SQL strings. Check result equivalence, filters, join behavior, aggregation grain, and time semantics.

## Observability

Create traceable events for:

- Request accepted
- Route selected
- Retrieval completed
- Schema context selected
- Query plan created
- SQL validation result
- SQL execution result
- Answer synthesized
- Request completed or failed

Use a request ID across all events. Record timings and counts, but redact credentials, sensitive values, and excessive document or row content.

## Development Workflow

When changing the codebase:

1. Inspect existing code, configuration, tests, and repository instructions first.
2. Make the smallest coherent change that satisfies the requirement.
3. Preserve separation between routing, tools, safety checks, and presentation.
4. Add or update tests for every behavior change.
5. Run targeted tests first, then the broader suite.
6. Run formatting, linting, and type checking when configured.
7. Update documentation and example configuration when interfaces change.
8. Report what changed, what was verified, and any remaining risk.

Do not silently introduce new external services, paid dependencies, or schema migrations. Explain the need and impact first.

## Configuration and Secrets

- Load configuration from environment variables or an approved secret manager.
- Provide a `.env.example` containing placeholders only.
- Never commit API keys, passwords, tokens, private certificates, or production connection strings.
- Keep development, test, and production settings separate.
- Validate configuration at startup and fail with a clear error when required values are missing.

## Initial Delivery Scope

Prioritize the following order:

1. Typed API and agent state
2. Structured router with `pdf`, `sql`, `hybrid`, and `clarify`
3. PDF ingestion with page-level citations
4. SQL schema retrieval, planning, validation, and read-only execution
5. Unified answer synthesis
6. Evaluation dataset and automated tests
7. Tracing and operational hardening

Avoid adding open-ended agent loops, long-term memory, or many additional tools until the core routes are safe, observable, and measurable.

## Definition of Done

A change is complete only when:

- Its behavior is implemented at the correct architectural layer.
- Relevant tests pass.
- SQL safety constraints remain enforced.
- PDF claims retain verifiable citations.
- Errors and low-confidence outcomes fail safely.
- Logs and traces are sufficient to diagnose failures without exposing secrets.
- Public interfaces and configuration changes are documented.


## Current Repository Layout

The ingestion implementation lives under `src/warhammer_agent/ingestion/`.
The four supported CLI entry points are `scripts/probe_pdf.py`,
`scripts/parse_pdf.py`, `scripts/clean_pdf.py`, and `scripts/build_pdf_review.py`.
Reviewed page corrections and their manifest live in
`config/corrections/core_rules/`; historical handler formats remain supported.
See `README.md` and `docs/ingestion.md` for current commands and retention rules.
Tests are split between `tests/unit/` and `tests/integration/`.
Do not assume raw per-page Markdown exists for cleaned pages: recover it from
`reports/docling/document.json` when needed. Preserve the source PDF, original
Docling JSON, correction hashes, and cleaned audit records.
