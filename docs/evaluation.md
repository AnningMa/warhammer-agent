# End-to-end evaluation

The evaluation pipeline runs the real unified agent on a small, versioned
reference dataset. It evaluates retrieval, SQL results, answer grounding,
agent traces, latency and token usage. It complements unit tests; it is not a
replacement for them.

## Dataset

`tests/eval_cases/agent.json` contains twelve cases:

- four Core Rules questions;
- four SQLite questions;
- three questions that require both sources;
- one ambiguous database question that should request clarification.

### Case selection

The twelve cases were selected to cover every route supported by the agent:

- four rules questions evaluate retrieval from the Core Rules PDF;
- four database questions evaluate Text-to-SQL generation and structured results;
- three hybrid questions require evidence from both the PDF and SQLite;
- one clarification question checks whether the agent avoids answering an
  underspecified query.

The dataset includes the four example chatbot questions from the project brief
verbatim, including the ambiguous Space Marine Toughness question. The remaining
cases were chosen to cover representative operations such as direct fact
retrieval, filtering, counting, profile comparison and multi-source reasoning.
Each case is answerable from the versioned project sources and has manually
checked reference evidence or SQL values.

Each case records its expected route and status, required source kinds, relevant
PDF section titles, expected structured SQL values, acceptable answer facts, a
reference answer and human-readable reference contexts. SQL reference values
were checked directly against `data/wahadb.sqlite`. Freeze and version this file
so separate evaluation runs remain comparable. Review any proposed changes to
questions or references before committing them. The project team should review
all twelve cases before treating the current dataset version as frozen.

## Deterministic metrics

The default run does not add a separate judge call. It calculates:

- route, status and agent-trace accuracy;
- exact required-source coverage;
- PDF Hit Rate@k, Precision@k and MAP@k;
- deterministic context recall and precision over reviewed section labels;
- SQL execution success and expected-value accuracy;
- required-fact coverage and citation validity;
- end-to-end pass rate, latency and reported Gemini tokens.

A case passes end to end only when all applicable route, trace, retrieval, SQL,
fact and citation checks pass. The context metrics based on section labels are
transparent deterministic proxies; they are not claimed to reproduce every
detail of RAGAS's LLM-scored metrics.

The thresholds in `config/evaluation.json` are internal targets selected for
this project, not benchmarks provided by the course:

- **90%** for route and trace accuracy, to require reliable orchestration while
  allowing one occasional failure;
- **80%** for PDF retrieval, required fact coverage and end-to-end success;
- **100%** for SQL result accuracy and citation validity, since incorrect
  database results or invalid citations should not be accepted.

Since the dataset contains only twelve cases, the evaluation is intended as a
small regression check rather than a large-scale statistical assessment.

## Optional LLM judge

`--judge` adds three semantic metrics taught in the course: faithfulness, answer
relevancy and factual correctness. The judge receives the question, retrieved
evidence, answer and reviewed reference. Its 1-5 scores are normalized to 0-1.
The configured judge is `gemini-2.5-pro`, intentionally different from the
default answer model. Access and quotas vary, so the judge is opt-in and its
failure never discards deterministic results. The judge output includes a short
rationale and usage metadata.

## Storage and resume

Every case is saved immediately under
`storage/evaluation/runs/<run-id>/cases/`. The completed run also contains
`evaluation.json` and `evaluation.md`. A failed case is retried by `--resume`;
completed cases are reused. `selection.json` preserves the selected case IDs and
model settings, so a resumed single-case or partial run does not expand to the
full dataset. This makes a multi-call evaluation recoverable after quota or
transient API errors.

Live cases are separated by `inter_case_delay_seconds` from
`config/evaluation.json`. The default 65-second interval reduces bursts between
cases, but a single agent case can still make several model calls. The shared
Gemini helper waits and retries once when a 429 response provides a short retry
delay of at most 90 seconds. Longer quota failures remain saved for a later
`--resume`. Reused successful case records do not incur the inter-case delay.

The CLI supports `--case-id`, `--category`, `--limit`, `--model`, `--judge`,
`--judge-model` and `--resume`. Start with one case because a rules, database or
hybrid turn can consume several Gemini requests. Run the complete frozen dataset
only after the smoke cases work and sufficient quota is available.
