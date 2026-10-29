# Warhammer Agent Evaluation

- Run ID: `20261029T191630Z_b5705336`
- Dataset: `tests/eval_cases/agent.json`
- Model override: `gemini-3.6-flash`
- Judge model: `disabled`
- Cases: 12
- Passed: 12

## Metrics

| Metric | Result | Target | Meets target |
|---|---:|---:|:---:|
| End-to-end pass rate | 100.0% | 80.0% | yes |
| Route accuracy | 100.0% | 90.0% | yes |
| Status accuracy | 100.0% | n/a | n/a |
| Agent trace accuracy | 100.0% | 90.0% | yes |
| Required-source coverage | 100.0% | n/a | n/a |
| PDF Hit Rate@5 | 100.0% | 80.0% | yes |
| PDF Precision@5 | 20.0% | n/a | n/a |
| PDF MAP@5 | 100.0% | n/a | n/a |
| Context recall | 100.0% | n/a | n/a |
| Context precision | 20.0% | n/a | n/a |
| SQL execution success | 100.0% | n/a | n/a |
| SQL result accuracy | 100.0% | 100.0% | yes |
| Required-fact coverage | 100.0% | 80.0% | yes |
| Citation validity | 100.0% | 100.0% | yes |
| Faithfulness (optional judge) | n/a | 80.0% | n/a |
| Answer relevancy (optional judge) | n/a | 80.0% | n/a |
| Factual correctness (optional judge) | n/a | 80.0% | n/a |

## Runtime

- Average latency: 27.777 seconds
- Median latency: 27.041 seconds
- Total reported agent tokens: 117130
- Total reported judge tokens: 0

## Results by category

| Category | Cases | Pass rate | Route accuracy |
|---|---:|---:|---:|
| clarification | 1 | 100.0% | 100.0% |
| database | 4 | 100.0% | 100.0% |
| hybrid | 3 | 100.0% | 100.0% |
| rules | 4 | 100.0% | 100.0% |

## Case details

| Case | Category | Route | Status | Sources | Facts | Result |
|---|---|---|---|---:|---:|:---:|
| `rules_grenade` | rules | yes | yes | yes | 100.0% | pass |
| `rules_stratagem` | rules | yes | yes | yes | 100.0% | pass |
| `rules_deep_strike` | rules | yes | yes | yes | 100.0% | pass |
| `rules_scoring` | rules | yes | yes | yes | 100.0% | pass |
| `database_intercessor_toughness` | database | yes | yes | yes | 100.0% | pass |
| `database_heavy_intercessor_profile` | database | yes | yes | yes | 100.0% | pass |
| `database_toughness_six_count` | database | yes | yes | yes | 100.0% | pass |
| `database_custodian_guard_profile` | database | yes | yes | yes | 100.0% | pass |
| `hybrid_toughness_count_and_wounds` | hybrid | yes | yes | yes | 100.0% | pass |
| `hybrid_strength_six_vs_heavy_intercessor` | hybrid | yes | yes | yes | 100.0% | pass |
| `hybrid_intercessor_cover` | hybrid | yes | yes | yes | 100.0% | pass |
| `clarification_space_marine` | clarification | yes | yes | yes | 100.0% | pass |

## Failed cases

None.

The deterministic metrics compare the frozen references with structured run records. They do not replace human review or an optional independent LLM judge for semantic faithfulness and answer relevance.
