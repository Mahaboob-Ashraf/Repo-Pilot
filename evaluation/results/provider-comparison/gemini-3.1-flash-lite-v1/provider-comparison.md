# Controlled Gemma vs Gemini provider comparison

The frozen six-case M9-v2 fixture set, retrieval stack, prompts, schemas, validators, Docker policy, approvals, and two-attempt limit were held constant. Only generation provider/model changed.

| Metric | Gemma local CPU | Gemini remote API |
|---|---:|---:|
| Repair success | 1/6 | 6/6 |
| Attempt-1 success | 1/6 | 6/6 |
| Grounded plans | 3/6 | 6/6 |
| Planner parse failures | 0 | 0 |
| Planner grounding failures | 3 | 0 |
| Exact citation validity | 0.5 | 1.0 |
| Cases reaching patcher | 3 | 6 |
| Valid patches | 1 | 6 |
| Docker test passes | 1 | 6 |
| Critic usage | 0 | 0 |
| Retry usage | 0.0 | 0.0 |
| Retry recoveries | 0 | 0 |
| Provider/API failures | 0 | 0 |
| Retrieval H@1 | 0.8333333333333334 | 0.8333333333333334 |
| Retrieval H@5 | 1.0 | 1.0 |
| Retrieval MRR | 0.9166666666666666 | 0.9166666666666666 |
| Context gold file coverage | 1.0 | 1.0 |
| Context gold symbol coverage | 1.0 | 1.0 |
| Median planner latency | 85.169s | 2.288s |
| Median patcher latency | 104.993s | 2.443s |
| Median total latency | 110.912s | 20.928s |
| Total generation tokens | not retained | 73416 |

## Gemini case outcomes

| Case | Result | Failure category | Plan | Patch | Tests |
|---|---|---|---:|---:|---:|
| `more-take-off-by-one` | repaired | - | yes | yes | pass |
| `more-quantify-inverted` | repaired | - | yes | yes | pass |
| `toolz-take-off-by-one` | repaired | - | yes | yes | pass |
| `toolz-drop-extra-item` | repaired | - | yes | yes | pass |
| `boltons-ceil-exact-option` | repaired | - | yes | yes | pass |
| `boltons-floor-exact-option` | repaired | - | yes | yes | pass |

## Interpretation and limits

Gemma generation ran locally on CPU. Gemini generation used a hosted API and network, while retrieval stayed local through Ollama/EmbeddingGemma. This is not a hardware-equivalent latency comparison.

Gemini mode sends bounded issue text, ContextPack source, approved plan, and later patch/test evidence to Google's Gemini API when those stages run. Deterministic citation, scope, hash, exact-match, retry, Docker, approval, and export boundaries are identical.

The benchmark contains only six controlled defects across three public repositories and is neither SWE-bench nor production evidence. Gemma token totals are unavailable because the frozen M9-v3 artifact did not retain them; no monetary cost is estimated.

Gemini failure categories: `{}`.
