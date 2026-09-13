# RepoPilot M10 final engineering report

M10 used a separate synthetic development suite to select changes, then measured unchanged frozen M8 and M9 fixtures in new result directories. Original baseline artifacts remain intact.

## Optimizations

- Kept optional Ollama JSON-schema output, while retaining Pydantic parsing and deterministic validators.
- Kept deterministic 32-document embedding batches and setup timing diagnostics.
- Kept retrieval depth 5; depth 3 was rejected because development coverage fell.
- Reverted the explicit allowed-ID list because it overflowed the 4,096-token runtime context on the medium case.
- Kept the patch prompt and exact validator unchanged; added bounded failure diagnostics.
- Fixed indented-method freshness after M9-v3 exposed a column-zero assumption.

## M8 comparison

| Metric | M8 baseline | M8-v2 |
|---|---:|---:|
| Hybrid file Hit@1 | 1.0000 | 1.0000 |
| Hybrid file Hit@5 | 1.0000 | 1.0000 |
| File context precision | 0.3750 | 0.4145 |
| File token waste | 0.6195 | 0.5837 |
| Gold file coverage | 1.0000 | 1.0000 |
| Safety scenarios | 33/33 | 33/33 |

## M9 comparison

| Metric | M9-v2 baseline | M9-v3 optimized |
|---|---:|---:|
| Repair success | 0/6 | 1/6 |
| Grounded plans | 1/6 | 3/6 |
| Planner parse failures | 3 | 0 |
| Planner grounding failures | 2 | 3 |
| Valid patches | 0 | 1 |
| Docker test passes | 0 | 1 |
| Retry recoveries | 0 | 0 |
| Retrieval H@1 | 0.8333 | 0.8333 |
| Context file coverage | 1.0000 | 1.0000 |
| Lexical fallbacks | 4 | 4 |
| Median total latency (ms) | 295313.6 | 110912.3 |

M9-v3 repaired 1/6 controlled external cases. This is a frozen controlled external evaluation across 3 public Python repositories, not SWE-bench or a production-accuracy estimate.

## Safety

M8-v2 passed all 33 deterministic scenarios. M9-v3 recorded no critical safety failure, scope violation, canonical mutation, retry-limit violation, or export-order failure. The two stale rejections were safe failures caused by a correctness bug fixed after measurement.

## Final verification

The complete backend suite passed 332 tests in 7.58 seconds. Frontend Vitest passed 18 tests across two files; TypeScript checking and the production Vite build passed.

## Reproducibility and limitations

The locked models were `gemma4:e4b-it-qat` and `embeddinggemma:latest`; Gemma was verified with `size_vram=0`. Docker used the pinned local pytest image. See `final-results.json` for identities, per-case failures, latencies, and limitations.
