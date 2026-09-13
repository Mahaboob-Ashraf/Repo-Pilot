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
| `more-take-off-by-one` | `more-itertools` | lexical_only_degraded | yes | no | not run | not run | no | not run | no | `failed_before_testing` |
| `more-quantify-inverted` | `more-itertools` | lexical_only_degraded | yes | yes | passed | not run | no | not run | yes | `solved_on_attempt_1` |
| `toolz-take-off-by-one` | `toolz` | lexical_only_degraded | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `toolz-drop-extra-item` | `toolz` | lexical_only_degraded | no | no | not run | not run | no | not run | no | `failed_before_testing` |
| `boltons-ceil-exact-option` | `boltons` | hybrid | yes | no | not run | not run | no | not run | no | `failed_before_testing` |
| `boltons-floor-exact-option` | `boltons` | hybrid | no | no | not run | not run | no | not run | no | `failed_before_testing` |

## 3. Aggregate repair results

Valid/attempted/completed: `6` / `6` / `1`. Repair successes: `1`; repair success rate: `0.1667`; attempt-1 rate: `0.1667`; retry-used rate: `0.0000`; attempt-2 recovery rate: `0.0000`; terminal failure rate: `0.8333`; infrastructure blocked: `0`; invalid frozen fixtures: `0`.
Repair success requires a produced patch, passing configured tests for that exact patch, final approval, exact export, unchanged canonical input, and no critical scope/authority breach.
Patch scope diagnostics across attempted cases: changed-file cases `1`, exact gold-file scopes `1`, extra files `0`, missing gold files `5`, behavioral successes `1`.

## 4. Retrieval

Post-hoc gold file Hit@1/Hit@5/MRR: `0.8333` / `1.0000` / `0.9167`. Context gold-file/symbol coverage: `1.0000` / `1.0000`. M8 was synthetic retrieval-only evidence; M9 does not reuse M8 labels.
Retrieval modes: `{"hybrid": 2, "lexical_only_degraded": 4}`. Lexical fallback is recorded as current production behavior, not infrastructure invalidation.

## 5. Failure analysis

Failure-stage counts: `{"patch validation": 2, "planner": 3}`. Per-case bounded reasons are retained in the JSON artifact.

Planner outcomes: valid grounded plans `3`, structured-output parse failures `0`, grounding failures `3`, provider failures `0`.

Patch/test outcomes: cases reaching patch generation `3`, valid patches `1`, Docker repair-test passes/failures `1` / `0`.

- `more-take-off-by-one`: `patch validation` - approved evidence no longer matches source
- `toolz-take-off-by-one`: `planner` - repair step 1 cites an unknown chunk: toolz/tests/test_itertoolz.py::test::test_frequencies::312-322
- `toolz-drop-extra-item`: `planner` - repair step 1 cites an unknown chunk: toolz/tests/test_itertoolz.py::test::test_getter::0-6
- `boltons-ceil-exact-option`: `patch validation` - approved evidence no longer matches source
- `boltons-floor-exact-option`: `planner` - repair step 1 cites an unknown chunk: Evidence 18

## 6. Safety

Critical authority/scope/workspace violation observed: `false`. Scope attempts `0`, stale/hash failures `2`, patch-validation failures `0`, canonical mutations `0`, retry-limit violations `0`, export-order failures `0`. The five planner failures did not reach approval, patch, Docker repair-test, or export; the one grounded plan reached approval #1 and patch generation, then failed deterministic patch validation before testing. The pre-repair Docker fixture tests did exercise the M5 sandbox. Safety is fail-loud and is never averaged.

## 7. Latency

Per-case indexing, embedding setup, retrieval, planner, patcher, Docker, critic, retry patcher, and total wall-clock timings follow in milliseconds; p95 is reported only at n>=5.

| Case | Index | Embed | Retrieve | Planner | Patcher | Tests | Critic | Retry patch | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `more-take-off-by-one` | 105.8024 | 17756.4128 | 3.3177 | 92986.9245 | 1.5855 | not measured | not measured | not measured | 110912.3223 |
| `more-quantify-inverted` | 92.0054 | 15895.3893 | 2.0975 | 133066.3994 | 104992.9273 | 982.4381 | not measured | not measured | 255095.0800 |
| `toolz-take-off-by-one` | 72.0205 | 36356.3798 | 1.1678 | 79752.1826 | not measured | not measured | not measured | not measured | 116704.0956 |
| `toolz-drop-extra-item` | 82.7072 | 36341.4375 | 1.4968 | 98370.1065 | not measured | not measured | not measured | not measured | 135187.8063 |
| `boltons-ceil-exact-option` | 11.0663 | 5297.1822 | 76.4494 | 85168.7230 | 1.4818 | not measured | not measured | not measured | 90602.1960 |
| `boltons-floor-exact-option` | 6.9462 | 5022.6697 | 75.0864 | 80344.9474 | not measured | not measured | not measured | not measured | 85485.4094 |

Aggregate latency:

- `repository_indexing_ms`: n=`6`, median=`72.0205`, p95=`105.8024`
- `embedding_index_setup_ms`: n=`6`, median=`15895.3893`, p95=`36356.3798`
- `retrieval_ms`: n=`6`, median=`2.0975`, p95=`76.4494`
- `planning_generation_ms`: n=`6`, median=`85168.7230`, p95=`133066.3994`
- `patch_generation_ms`: n=`3`, median=`1.5855`, p95=`not measured`
- `docker_testing_ms`: n=`1`, median=`982.4381`, p95=`not measured`
- `critic_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `retry_patch_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `total_workflow_ms`: n=`6`, median=`110912.3223`, p95=`255095.0800`

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
