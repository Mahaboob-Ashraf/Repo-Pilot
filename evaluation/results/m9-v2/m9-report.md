# M9 Frozen External Repository + System Evaluation

> Controlled external-repository evaluation only. This is not SWE-bench or production-scale evidence.

## Final M9 v2 measurement

M9 v1 remains historical and is not repair-quality evidence: its five generation attempts were invalidated by retained Vulkan device-loss/HTTP-500 evidence, and its sixth case used a non-discriminating pre-repair selector. M9 v2 is the clean frozen benchmark-data repair: all six selectors failed before repair and every canonical fixture remained unchanged.

The v2 run used the locked models and `REPOPILOT_OLLAMA_TIMEOUT_SECONDS=600`. Ollama `/api/ps` reported `size_vram=0` for Gemma before and repeatedly during the run, confirming 100% CPU placement and preventing the known GPU runtime path. No RepoPilot prompt, retrieval, context-budget, model, schema, grounding, or retry-policy tuning occurred between diagnosis and this run. Each frozen case ran exactly once, with no benchmark-level retry or manual repair.

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
| `toolz-take-off-by-one` | `toolz` | lexical_only_degraded | yes | no | not run | not run | no | not run | no | `failed_before_testing` |
| `toolz-drop-extra-item` | `toolz` | lexical_only_degraded | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `boltons-ceil-exact-option` | `boltons` | hybrid | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `boltons-floor-exact-option` | `boltons` | hybrid | no | no | not run | not run | no | not run | no | `failed_before_testing` |

## 3. Aggregate repair results

Valid/attempted/completed: `6` / `6` / `0`. Repair successes: `0`; repair success rate: `0.0000`; attempt-1 rate: `0.0000`; retry-used rate: `0.0000`; attempt-2 recovery rate: `0.0000`; terminal failure rate: `1.0000`; infrastructure blocked: `0`; invalid frozen fixtures: `0`.
Repair success requires a produced patch, passing configured tests for that exact patch, final approval, exact export, unchanged canonical input, and no critical scope/authority breach.
Patch scope diagnostics across attempted cases: changed-file cases `0`, exact gold-file scopes `0`, extra files `0`, missing gold files `6`, behavioral successes `0`.

## 4. Retrieval

Post-hoc gold file Hit@1/Hit@5/MRR: `0.8333` / `1.0000` / `0.9167`. Context gold-file/symbol coverage: `1.0000` / `1.0000`. M8 was synthetic retrieval-only evidence; M9 does not reuse M8 labels.
Retrieval modes: `{"hybrid": 2, "lexical_only_degraded": 4}`. Lexical fallback is recorded as current production behavior, not infrastructure invalidation.

## 5. Failure analysis

Failure-stage counts: `{"patch validation": 1, "planner": 5}`. Per-case bounded reasons are retained in the JSON artifact.

Planner outcomes: valid grounded plans `1`, structured-output parse failures `3`, grounding failures `2`, provider failures `0`.

Patch/test outcomes: cases reaching patch generation `1`, valid patches `0`, Docker repair-test passes/failures `0` / `0`.

- `more-take-off-by-one`: `planner` - inference output is not a valid structured RepairPlan
- `more-quantify-inverted`: `planner` - inference output is not a valid structured RepairPlan
- `toolz-take-off-by-one`: `patch validation` - patch proposal failed deterministic validation
- `toolz-drop-extra-item`: `planner` - inference output is not a valid structured RepairPlan
- `boltons-ceil-exact-option`: `planner` - repair step 1 cites an unknown chunk: Snippet 1
- `boltons-floor-exact-option`: `planner` - repair step 1 cites an unknown chunk: 12

## 6. Safety

Critical authority/scope/workspace violation observed: `false`. Scope attempts `0`, stale/hash failures `0`, patch-validation failures `1`, canonical mutations `0`, retry-limit violations `0`, export-order failures `0`. The five planner failures did not reach approval, patch, Docker repair-test, or export; the one grounded plan reached approval #1 and patch generation, then failed deterministic patch validation before testing. The pre-repair Docker fixture tests did exercise the M5 sandbox. Safety is fail-loud and is never averaged.

## 7. Latency

Per-case indexing, embedding setup, retrieval, planner, patcher, Docker, critic, retry patcher, and total wall-clock timings follow in milliseconds; p95 is reported only at n>=5.

| Case | Index | Embed | Retrieve | Planner | Patcher | Tests | Critic | Retry patch | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `more-take-off-by-one` | 125.9838 | 60207.1311 | 4.0545 | 324382.8817 | not measured | not measured | not measured | not measured | 384778.6142 |
| `more-quantify-inverted` | 116.0578 | 60035.4620 | 4.6687 | 331170.7461 | not measured | not measured | not measured | not measured | 391372.7877 |
| `toolz-take-off-by-one` | 95.1420 | 60027.9838 | 4.5341 | 254950.1458 | 312320.0977 | not measured | not measured | not measured | 627939.8700 |
| `toolz-drop-extra-item` | 82.0339 | 60022.9820 | 1.3907 | 234743.8020 | not measured | not measured | not measured | not measured | 295313.5973 |
| `boltons-ceil-exact-option` | 7.8159 | 5417.7958 | 82.3275 | 241546.4308 | not measured | not measured | not measured | not measured | 247093.9971 |
| `boltons-floor-exact-option` | 8.0592 | 5350.0057 | 80.2841 | 282050.3082 | not measured | not measured | not measured | not measured | 287534.7735 |

Aggregate latency:

- `critic_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `docker_testing_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `embedding_index_setup_ms`: n=`6`, median=`60022.9820`, p95=`60207.1311`
- `patch_generation_ms`: n=`1`, median=`312320.0977`, p95=`not measured`
- `planning_generation_ms`: n=`6`, median=`254950.1458`, p95=`331170.7461`
- `repository_indexing_ms`: n=`6`, median=`82.0339`, p95=`125.9838`
- `retrieval_ms`: n=`6`, median=`4.5341`, p95=`82.3275`
- `retry_patch_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `total_workflow_ms`: n=`6`, median=`295313.5973`, p95=`627939.8700`

## 8. Limitations

- Only six frozen cases across three repositories were defined; all six were valid controlled-defect cases in v2.
- Every case is a controlled defect, not a historical bug.
- This is not SWE-bench and is not representative of arbitrary Python repositories.
- CPU-local generation is slow.

## 9. M10 candidates

- Diagnose the measured 60-second dense-index timeout on the four larger fixtures; those cases used the existing lexical fallback.
- Analyze the five measured planner-stage failures using typed failure evidence retained by subsequent runs; do not rerun M9 for score shopping.
- Investigate why grounded patch generation produced output that deterministic patch validation rejected, without weakening validation.
- Preserve the byte-offset line-accounting regression for large Tree-sitter inputs.
