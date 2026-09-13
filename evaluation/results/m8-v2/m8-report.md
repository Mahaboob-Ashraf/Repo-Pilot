# M8 Frozen Retrieval + Safety Evaluation

> Controlled local evaluation only. This is not SWE-bench, production evidence, or a statistically representative sample of Python repositories.

## 1. Evaluation setup

- Fixture set: `m8-frozen-local-v1` (`0dccc964a8da7a4e0a0988116e54d8e3b2f4d3354a05d35763b39a4c28ec9e7b`)
- Git commit: `9d4d05d64ce54a7001caaa0175e7787664f3b630`
- Embedding model: `embeddinggemma:latest`
- Embedding model digest: `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`
- RRF k / candidate k / returned k: `60` / `20` / `5`
- Context budget: `16384` estimated UTF-8-byte units

## 2. Retrieval results

| Variant | Status | File Hit@1 | File Hit@5 | File MRR | Symbol Hit@1 | Symbol Hit@5 | Symbol MRR | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ast_bm25` | measured | 0.9000 | 1.0000 | 0.9500 | 1.0000 | 1.0000 | 1.0000 | 0.2735 | 0.5205 |
| `ast_dense` | measured | 0.9000 | 1.0000 | 0.9500 | 0.9000 | 1.0000 | 0.9500 | 74.1154 | 107.0510 |
| `ast_hybrid_rrf` | measured | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 72.3334 | 105.3152 |

## 3. Structural expansion

Structure helped 1 cases, was unchanged for 6, and added only non-gold evidence for 3. Mean additions: 0.5000 chunks / 43.1000 source units.

## 4. Context packing

Mean gold-file coverage `1.0000`; mean gold-symbol coverage `1.0000`; mean file/symbol chunk precision `0.4145` / `0.3202`; mean file/symbol token waste `0.5837` / `0.6795`; mean budget utilization `0.1838`. Relevant evidence was budget-excluded in `0` cases. Pack statuses: `{"complete": 10}`.

### Fixed-budget policy scenarios

| Case | Pack status | Used / 16384 | Gold coverage | Relevant excluded |
|---|---|---:|---:|---|
| `all_evidence_fits` | `complete` | 1342 | 1.0000 | false |
| `useful_evidence_competes` | `partial_budget` | 14849 | 0.5000 | true |
| `highest_priority_near_boundary` | `complete` | 15527 | 1.0000 | false |
| `oversized_highest_priority` | `oversized_highest_priority` | 195 | 0.0000 | true |

## 5. Safety scorecard

| Category | Scenarios | Passed | Failed |
|---|---:|---:|---:|
| Scope authority | 5 | 5 | 0 |
| Path isolation | 4 | 4 | 0 |
| Stale-state binding | 5 | 5 | 0 |
| Prompt-injection authority | 4 | 4 | 0 |
| Workspace integrity | 4 | 4 | 0 |
| Test execution | 4 | 4 | 0 |
| Retry bound | 3 | 3 | 0 |
| Final approval/export | 4 | 4 | 0 |

## 6. Fault injection

Deterministic probes injected unapproved/mixed edits, invented and unrelated evidence, stale source and approval hashes, a workspace write failure, an operational critic instruction, an attempt-three request, pre-approval/wrong-hash exports, and export conflicts. The expected boundaries rejected them, downstream authority did not expand, and canonical-repository bytes remained unchanged. Detailed observations remain visible in `m8-results.json`.

## 7. Key findings

BM25 and dense retrieval each placed a gold file first in 9/10 cases and within five in 10/10; hybrid RRF did both in 10/10. At returned k=10 on these small repositories, one-hop structure added no chunks in any case. All final ContextPacks covered every labeled gold file and symbol. All 33 deterministic safety scenarios passed with no canonical repository mutation.

## 8. Weaknesses discovered

BM25 ranked the wrong file first in the deliberately ambiguous same-name `normalize` case. Dense retrieval ranked a related test above the gold helper in the cross-module email case. Structural expansion had no observable effect at the current returned-k setting on these small fixtures. ContextPacks achieved full gold coverage but had mean file chunk precision 0.3750 and mean file token waste 0.6195. The suite remains too small and synthetic for broad accuracy claims.

## 9. What M9 must test

M9 must evaluate frozen external repositories and complete repair success through the existing two-checkpoint, two-attempt workflow. M8 does not provide that system-level evidence.
