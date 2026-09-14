# M9 Frozen External Repository + System Evaluation

> Controlled external-repository evaluation only. This is not SWE-bench or production-scale evidence.

## Controlled provider experiment

This run uses the unchanged frozen M9-v2 fixtures and production workflow with Gemini selected only for planner, patcher, and critic generation. Retrieval remains local through EmbeddingGemma. Each case runs once; there is no benchmark-level regeneration or manual repair.

## 1. Setup

- Repositories/cases: `3` / `6`
- Case type: external-repository controlled-defect cases (no historical cases)
- Generation provider: `gemini`
- Generation / embedding: `gemini-3.1-flash-lite` / `embeddinggemma:latest`
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
- `gemini-3.1-flash-lite`: `hosted model name (no local digest)`

## 2. End-to-end results

| Case | Repo | Retrieval | Plan | Patch #1 | Test #1 | Critic | Patch #2 | Test #2 | Final | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| `more-take-off-by-one` | `more-itertools` | lexical_only_degraded | yes | yes | passed | not run | no | not run | yes | `solved_on_attempt_1` |
| `more-quantify-inverted` | `more-itertools` | lexical_only_degraded | yes | yes | passed | not run | no | not run | yes | `solved_on_attempt_1` |
| `toolz-take-off-by-one` | `toolz` | lexical_only_degraded | yes | yes | passed | not run | no | not run | yes | `solved_on_attempt_1` |
| `toolz-drop-extra-item` | `toolz` | lexical_only_degraded | yes | yes | passed | not run | no | not run | yes | `solved_on_attempt_1` |
| `boltons-ceil-exact-option` | `boltons` | hybrid | yes | yes | passed | not run | no | not run | yes | `solved_on_attempt_1` |
| `boltons-floor-exact-option` | `boltons` | hybrid | yes | yes | passed | not run | no | not run | yes | `solved_on_attempt_1` |

## 3. Aggregate repair results

Valid/attempted/completed: `6` / `6` / `6`. Repair successes: `6`; repair success rate: `1.0000`; attempt-1 rate: `1.0000`; retry-used rate: `0.0000`; attempt-2 recovery rate: `0.0000`; terminal failure rate: `0.0000`; infrastructure blocked: `0`; invalid frozen fixtures: `0`.
Repair success requires a produced patch, passing configured tests for that exact patch, final approval, exact export, unchanged canonical input, and no critical scope/authority breach.
Patch scope diagnostics across attempted cases: changed-file cases `6`, exact gold-file scopes `6`, extra files `0`, missing gold files `0`, behavioral successes `6`.

## 4. Retrieval

Post-hoc gold file Hit@1/Hit@5/MRR: `0.8333` / `1.0000` / `0.9167`. Context gold-file/symbol coverage: `1.0000` / `1.0000`. M8 was synthetic retrieval-only evidence; M9 does not reuse M8 labels.
Retrieval modes: `{"hybrid": 2, "lexical_only_degraded": 4}`. Lexical fallback is recorded as current production behavior, not infrastructure invalidation.

## 5. Failure analysis

Failure-stage counts: `{}`. Per-case bounded reasons are retained in the JSON artifact.

Planner outcomes: valid grounded plans `6`, structured-output parse failures `0`, grounding failures `0`, provider failures `0`.

Patch/test outcomes: cases reaching patch generation `6`, valid patches `6`, Docker repair-test passes/failures `6` / `0`.


## 6. Safety

Critical authority/scope/workspace violation observed: `false`. Scope attempts `0`, stale/hash failures `0`, patch-validation failures `0`, canonical mutations `0`, retry-limit violations `0`, export-order failures `0`. Validator rejections are safe failures rather than authority violations. The pre-repair Docker fixture tests exercise the same M5 sandbox. Safety is fail-loud and is never averaged.

## 7. Latency

Per-case indexing, embedding setup, retrieval, planner, patcher, Docker, critic, retry patcher, and total wall-clock timings follow in milliseconds; p95 is reported only at n>=5.

| Case | Index | Embed | Retrieve | Planner | Patcher | Tests | Critic | Retry patch | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `more-take-off-by-one` | 90.3978 | 16618.5461 | 2.2717 | 2187.2740 | 2443.3295 | 835.1287 | not measured | not measured | 22250.9773 |
| `more-quantify-inverted` | 82.2054 | 14924.4091 | 1.9803 | 2520.6558 | 2522.7003 | 806.0830 | not measured | not measured | 20928.3263 |
| `toolz-take-off-by-one` | 67.9926 | 35434.4643 | 1.7487 | 2948.3036 | 3390.1702 | 1164.1739 | not measured | not measured | 43407.4158 |
| `toolz-drop-extra-item` | 70.2981 | 34653.8634 | 1.0748 | 2179.7144 | 2165.4830 | 1104.6512 | not measured | not measured | 40644.3088 |
| `boltons-ceil-exact-option` | 7.5301 | 5267.4724 | 75.1610 | 2288.1831 | 3682.5060 | 713.4025 | not measured | not measured | 12101.6406 |
| `boltons-floor-exact-option` | 8.3791 | 5255.1733 | 70.3235 | 2594.5694 | 2407.0373 | 700.7160 | not measured | not measured | 11098.3555 |

Aggregate latency:

- `repository_indexing_ms`: n=`6`, median=`67.9926`, p95=`90.3978`
- `embedding_index_setup_ms`: n=`6`, median=`14924.4091`, p95=`35434.4643`
- `retrieval_ms`: n=`6`, median=`1.9803`, p95=`75.1610`
- `planning_generation_ms`: n=`6`, median=`2288.1831`, p95=`2948.3036`
- `patch_generation_ms`: n=`6`, median=`2443.3295`, p95=`3682.5060`
- `docker_testing_ms`: n=`6`, median=`806.0830`, p95=`1164.1739`
- `critic_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `retry_patch_generation_ms`: n=`0`, median=`not measured`, p95=`not measured`
- `total_workflow_ms`: n=`6`, median=`20928.3263`, p95=`43407.4158`

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
