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

The optional `--judge` mode adds faithfulness, answer relevancy and factual
correctness scores. It is disabled by default because it requires additional
Gemini calls and model access. The final twelve-case evaluation uses the
deterministic metrics only, so the judge scores are reported as `n/a`.

## Storage and resume

Each case is saved immediately under
`storage/evaluation/runs/<run-id>/cases/`. Running the evaluation again with
`--resume` reuses completed cases and retries failed ones, so an interrupted run
can continue without repeating successful API calls.

Live cases are separated by the delay configured in `config/evaluation.json`.
Short 429 rate-limit errors are retried once when Gemini provides a wait of no
more than 90 seconds. Longer quota errors remain saved and can be retried later
with `--resume`.

The CLI also supports selecting cases with `--case-id`, `--category` and
`--limit`. The complete dataset should be run only when the smoke tests work and
sufficient API quota is available.
