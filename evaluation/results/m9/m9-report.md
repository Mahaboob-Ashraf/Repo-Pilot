# M9 Frozen External Repository + System Evaluation

> Controlled external-repository evaluation only. This is not SWE-bench or production-scale evidence.

## Post-run Task 019C diagnosis

The five original planner-stage attempts are now classified post-hoc as `infrastructure_invalid`: the retained Ollama log ties every generation request to Vulkan device loss and HTTP 500. The historical 0/5 artifact is preserved, but it is not valid repair-quality evidence.

One separately labeled confirmation generation returned a schema-valid plan, then failed grounding as `PlanValidationError`: `repair step 1 cites an unknown chunk: N/A`. No patch or retry ran. A clean full M9 rerun is scientifically justified but was not performed in Task 019C.

## 1. Setup

- Repositories/cases: `3` / `6`
- Case type: external-repository controlled-defect cases (no historical cases)
- Generation / embedding: `gemma4:e4b-it-qat` / `embeddinggemma:latest`
- Docker image: `repopilot-python-test:3.11-pytest9`
- Docker image ID: `sha256:72b98eae96d168dcdd898cdad6b3c198de5e2b8a0092ee1b80ea8ad1e3d972c7`
- Runtime: Python `3.12.13` on `Windows-11-10.0.26200-SP0`; logical CPUs `12`; memory `not measured`
- Evaluation mode: `real`

Repositories:

- `more-itertools` at `9ed3dbb0ae527230cd156d91d0af305478558fba` (`MIT`)
- `toolz` at `568c2b8393973cd172a466546c9d95779c452438` (`BSD-3-Clause`)
- `boltons` at `961dcff3f42e73b245aef65e377fe82763b257bb` (`BSD-3-Clause`)

Locked model identities:

- `embeddinggemma:latest`: `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`
- `gemma4:e4b-it-qat`: `ee665637121887cf3befff38abbb1be4ee117c7db867d97a67e29049ecd7e15f`

## 2. End-to-end results

| Case | Repo | Retrieval | Plan | Patch #1 | Test #1 | Critic | Patch #2 | Test #2 | Final | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| `more-take-off-by-one` | `more-itertools` | lexical_only_degraded | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `more-quantify-inverted` | `more-itertools` | lexical_only_degraded | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `toolz-take-off-by-one` | `toolz` | lexical_only_degraded | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `toolz-drop-extra-item` | `toolz` | lexical_only_degraded | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `boltons-ceil-exact-option` | `boltons` | hybrid | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `boltons-floor-upper-choice` | `boltons` | not run | no | no | not run | not run | no | not run | no | `benchmark_fixture_invalid` |

## 3. Aggregate repair results

Attempted/completed: `5` / `0`. Repair success rate: `0.0000`; attempt-1 rate: `0.0000`; retry-used rate: `0.0000`; attempt-2 recovery rate: `0.0000`; terminal failure rate: `1.0000`; infrastructure blocked: `0`; invalid frozen fixtures: `1`.
Repair success requires a produced patch, passing configured tests for that exact patch, final approval, exact export, unchanged canonical input, and no critical scope/authority breach.
Patch scope diagnostics across attempted cases: changed-file cases `0`, exact gold-file scopes `0`, extra files `0`, missing gold files `5`, behavioral successes `0`.

## 4. Retrieval

Post-hoc gold file Hit@1/Hit@5/MRR: `0.8000` / `1.0000` / `0.9000`. Context gold-file/symbol coverage: `1.0000` / `1.0000`. M8 was synthetic retrieval-only evidence; M9 does not reuse M8 labels.

## 5. Failure analysis

Failure-stage counts: `{"fixture validation": 1, "planner": 5}`. Per-case bounded reasons are retained in the JSON artifact.

- `more-take-off-by-one`: `planner` - Planner failed; typed workflow error detail was not retained by the initial M9 observation.
- `more-quantify-inverted`: `planner` - Planner failed; typed workflow error detail was not retained by the initial M9 observation.
- `toolz-take-off-by-one`: `planner` - Planner failed; typed workflow error detail was not retained by the initial M9 observation.
- `toolz-drop-extra-item`: `planner` - Planner failed; typed workflow error detail was not retained by the initial M9 observation.
- `boltons-ceil-exact-option`: `planner` - Planner failed; typed workflow error detail was not retained by the initial M9 observation.
- `boltons-floor-upper-choice`: `fixture validation` - Configured pre-repair selector passed; the frozen repair case is invalid.

## 6. Safety

Critical authority/scope/workspace violation observed: `false`. Scope attempts `0`, stale/hash failures `0`, patch-validation failures `0`, canonical mutations `0`, export-order failures `0`. Planner failures did not reach either approval, patch, Docker repair-test, or export boundary; the pre-repair Docker fixture tests did exercise the M5 sandbox. Safety is fail-loud and is never averaged.

## 7. Latency

Per-case indexing, embedding setup, retrieval, planner, patcher, Docker, critic, retry patcher, and total wall-clock timings are in `m9-results.json`; medians and p95 (only at n>=5) are aggregated there.
- `critic_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `docker_testing_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `embedding_index_setup_ms`: n=`5`, median=`60029.0263`, p95=`60101.6357`
- `patch_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `planning_generation_ms`: n=`5`, median=`54092.1377`, p95=`54936.6069`
- `repository_indexing_ms`: n=`5`, median=`83.9319`, p95=`89.4424`
- `retrieval_ms`: n=`5`, median=`1.7695`, p95=`143.7428`
- `retry_patch_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `total_workflow_ms`: n=`5`, median=`114240.2928`, p95=`115469.6670`

## 8. Limitations

- Only six frozen cases across three repositories were defined; only five were valid repair attempts.
- Every case is a controlled defect, not a historical bug.
- This is not SWE-bench and is not representative of arbitrary Python repositories.
- CPU-local generation is slow.

## 9. M10 candidates

- Diagnose the measured 60-second dense-index timeout on the four larger fixtures; those cases used the existing lexical fallback.
- Analyze the five measured planner-stage failures using typed failure evidence retained by subsequent runs; do not rerun M9 for score shopping.
- Replace the invalid `boltons-floor-upper-choice` selector only in a future benchmark version, never by rewriting this frozen result.
- Preserve the byte-offset line-accounting regression for large Tree-sitter inputs.
