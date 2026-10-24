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

The dataset includes the four example chatbot questions from the project brief
verbatim, including the ambiguous Space Marine Toughness question.

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

The CLI supports `--case-id`, `--category`, `--limit`, `--model`, `--judge`,
`--judge-model` and `--resume`. Start with one case because a rules, database or
hybrid turn can consume several Gemini requests. Run the complete frozen dataset
only after the smoke cases work and sufficient quota is available.
