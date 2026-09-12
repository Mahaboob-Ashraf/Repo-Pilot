# RepoPilot Evaluation Plan

No project benchmark has run. Every public-quality or comparative result is
currently **Not measured**. The controlled Task 011 retrieval cases and Task
012 structural/context cases validate code and metric behavior only; they are
not benchmark, SWE-bench, or retrieval-quality claims. Task 013 planner and
approval tests are functional/safety evidence and likewise make no model-quality
or repair-success claim.

## Evidence record required for every future measured run

- Date and commit SHA.
- Hardware: CPU, RAM, GPU/VRAM, operating system.
- Frozen dataset name/version, exact cases, labels, and count.
- Fixed generation model, quantization, Ollama version, context window, and
  prompt/template version when generation is involved.
- Embedding model tag/digest/dimension, document format, Chroma version, and
  cosine configuration.
- SQLite version, FTS tokenizer/weights, RRF constant, candidate depth, and
  returned depth.
- Software/container versions.
- Warm-up, run count, aggregation method, and timer boundaries.
- Failures, degraded cases, exclusions, uncertainty, and limitations.

## Implemented M2B retrieval-evaluation harness

### Frozen case schema

Each immutable serializable case contains:

- `case_id`: unique stable identifier;
- `query`: issue/query text passed unchanged to retrieval;
- `repository_ref`: normalized relative POSIX fixture/root reference;
- `relevant_files`: one or more gold repository-relative file paths;
- `relevant_symbols`: one or more gold symbols when known, otherwise `null`.

Gold files and symbols are evaluation-only labels. Retriever adapters accept
only `query` and `top_k`, so labels cannot be added to the query being scored.

### Implemented variants

| Variant | Definition | Status |
|---|---|---|
| `ast_bm25` | Tree-sitter `CodeChunk` + SQLite FTS5/BM25 | Implemented |
| `ast_dense` | Tree-sitter `CodeChunk` + precomputed Chroma cosine vectors | Implemented |
| `ast_hybrid_rrf` | Independent BM25/dense candidates fused by RRF | Implemented |
| `fixed_bm25` | Fixed-size chunk baseline | Deferred; not implemented |
| `hybrid_structure` | RRF, one-hop structure, then bounded ContextPack | Implemented for context evaluation |

### RRF baseline

For each document/chunk `d`:

```text
score(d) = sum over retrieval lists of 1 / (k_rrf + rank(d))
```

Ranks are 1-based. `k_rrf` defaults to `60`, a conventional initial baseline,
not a measured optimum. Each modality supplies up to configurable
`candidate_k`; the fused response independently returns `top_k`. Equal fused
scores break by canonical `chunk_id`.

RRF is rank-only because raw SQLite BM25 scores (smaller/more-negative is
better) and raw Chroma cosine distances (smaller is better) are not calibrated
to a common scale. Those raw values remain attached as diagnostic metadata and
are never normalized or added in the fused score.

If the dense path encounters an expected embedding-provider or Chroma
count/query failure, the vector layer exposes `VectorRetrievalError` and
`ast_hybrid_rrf` continues with unchanged BM25 candidates. It records
`lexical_only_degraded` plus a degradation reason and must not report normal
hybrid mode. This fallback is not a retry mechanism. Unexpected programming
errors still propagate, and the standalone `ast_dense` variant surfaces its
own failure.

### Implemented metrics

- **Relevant-file Hit@1:** `1` when a returned chunk from any gold file is at
  rank 1; otherwise `0`.
- **Relevant-file Hit@5:** `1` when a returned chunk from any gold file is at
  rank 1 through 5 inclusive; otherwise `0`.
- **Relevant-symbol Hit@5:** when symbol gold exists, `1` when a returned
  chunk's symbol or qualified symbol matches any gold symbol at rank 1 through
  5; otherwise `0`. When no symbol gold exists the value is `null` and the case
  is excluded from symbol aggregate denominators.
- **File reciprocal rank:** reciprocal of the first rank whose chunk path is a
  gold file; `0` when no gold file is retrieved. The aggregate mean is explicit
  file-level MRR.
- **Symbol reciprocal rank:** reciprocal of the first rank whose symbol or
  qualified symbol matches symbol gold; `0` when labeled but missed, and
  `null` when no symbol gold exists. The aggregate mean excludes unlabeled
  cases and is explicit symbol-level MRR.
- **Retrieval latency:** wall-clock duration around the variant adapter at the
  harness boundary, recorded per case. Aggregate p50/p95 use deterministic
  nearest-rank percentiles only with at least five measured cases; smaller
  groups report `null` rather than overstating percentiles.

Per-case output also records case/variant, ranked chunk IDs and provenance,
gold labels, degradation status, and retrieval mode. Result and aggregate
objects expose JSON-friendly dictionaries suitable for later JSON/CSV writers.

### Controlled harness-validation set

`backend/tests/fixtures/retrieval_cases.json` contains four cases against the
canonical three-chunk discount repository:

1. exact `apply_discount` identifier;
2. semantic percentage-reduction paraphrase;
3. exact zero-percent test identifier;
4. twenty-percent related-test phrasing used to exercise hybrid behavior.

Offline tests use deterministic, explicitly fake embeddings. Separate
hand-ranked tests prove candidates that occur in both lists, BM25 only, and
dense only. The controlled zero-percent case also deliberately gives BM25 and
the fake dense retriever different depth-one candidates, proving lexical-only
and vector-only membership in an end-to-end hybrid harness run. These cases
prove schema, isolation, fusion, metric, and output behavior; their hit rates
and latencies must not be presented as benchmark results.

## Existing lexical and dense functional evidence

The SQLite baseline indexes semantic chunk source, symbol, qualified symbol,
path, type, and imports with safely quoted OR-token queries and fixed BM25
weights. Toy searches validate implementation and provenance, not quality.

The Chroma baseline stores exact-source precomputed local embeddings with no
default Chroma embedding function and cosine distance. Automated tests use a
deterministic fake. A real `embeddinggemma` smoke observed a 768-dimensional
vector and successful three-chunk indexing/querying; that single toy run is
functional smoke evidence, not a latency or retrieval benchmark.

## Implemented M2C context evaluation

M2C adds a separate `hybrid_structure` path: query-only hybrid retrieval,
exactly one structural hop, fixed-budget packing, then evaluation against gold
labels. The retriever, expander, and packer never receive gold files or
symbols. Per-case context records preserve included chunk order, canonical
provenance, origin, counted item cost, pack/degradation status, total cost,
configured budget, and pipeline-boundary wall-clock latency.

- **Relevant-file context coverage:** `1` when at least one included chunk path
  matches any gold file; otherwise `0`.
- **Relevant-symbol context coverage:** when symbol labels exist, `1` when an
  included chunk symbol or qualified symbol matches; otherwise `0`. It is
  `null` when symbol ground truth is absent.
- **File context chunk precision:** included chunks whose paths match gold
  files divided by all included chunks. An empty pack reports `null`.
- **Symbol context chunk precision:** included chunks whose symbol or qualified
  symbol matches symbol gold divided by all included chunks. It is `null` for
  absent symbol labels or an empty pack.
- **File context token waste:** counted evidence-item cost belonging to chunks
  outside gold files divided by total included evidence-item cost. It is
  `null` when the included item-cost denominator is zero.
- **Symbol context token waste:** the corresponding nonmatching-symbol ratio;
  it is also `null` without symbol labels or a nonzero denominator.
- **Budget utilization:** complete rendered pack cost, including issue/evidence
  framing, divided by the configured hard budget.

Token waste is label-relative accounting, not a universal claim that
nonmatching context is useless. Current production counts use the documented
UTF-8-byte estimator and are estimated units, not exact Gemma tokens. Exact
deterministic fake counters validate metric and budget math in automated tests.

`backend/tests/fixtures/structure_repo/` and `structure_cases.json` validate
parent/child, local-import, directly-related-test, third-party exclusion,
one-hop, deduplication, budget exclusion, and gold-isolation behavior. These
controlled fixtures and the canonical toy functional smoke are harness
validation only. No aggregate result from them is a public benchmark claim.

## M3 planner/approval functional evidence

Offline tests use a deterministic fake `InferenceProvider`; they do not invoke
Ollama and do not measure planning quality. They verify prompt trust boundaries,
strict Pydantic parsing, ContextPack-only citations and file paths, canonical
plan hashes, a real LangGraph interrupt, hash-bound approve/reject transitions,
thread isolation, no planner rerun on resume, and no repository mutation.

Persistence tests use isolated temporary SQLite databases. One test closes the
first workflow/service and reconstructs a second over the same database, then
resumes the paused thread with its original plan hash. This proves local
checkpoint durability and thread semantics only; it is not a latency,
throughput, scale, or reliability benchmark.

One later real local smoke used the canonical toy issue and ContextPack with
`gemma4:e4b-it-qat`. Retrieval completed normally, but the single 51.015-second
generation call surfaced `PlannerInferenceError` before model output could be
parsed. No retry occurred. This failed functional smoke is not a planning
latency or quality benchmark.

The one permitted diagnostic rerun took 52.784 seconds and again stopped before
model output. Bounded diagnostics identified an Ollama HTTP 500, and only newly
appended local server-log bytes identified the underlying Vulkan device loss.
This single failed request is environment/runtime diagnostic evidence, not a
generation-latency benchmark.

## M4 patch functional evidence

Offline M4 tests use deterministic fake providers and do not measure model
quality or runtime performance. They validate approved-scope authority,
evidence freshness, all-or-nothing exact replacements, rollback, workspace
isolation, deterministic diff/hash identity, LangGraph routing, and replay.

One later CPU-only functional smoke used the canonical discount issue,
`gemma4:e4b-it-qat`, and the normal 1,805/2,000-unit ContextPack. `ollama ps`
reported `100% CPU`. Exactly one planner generation (183.976 seconds) and one
patcher generation (161.725 seconds) ran. The exact in-run plan/hash was
approved through LangGraph, the isolated workspace reached `patch_ready`, and
the canonical repository stayed byte-identical. No test execution or retry ran.
These single-run observations are functional smoke evidence, not latency,
throughput, quality, or comparative benchmark results.

## M5 sandbox functional evidence

The 42 focused M5 tests use deterministic process and runner fakes. They prove
fixed argv construction, selector rejection, sandbox flags, status mapping,
bounded logs, M4 integrity checks, disposable snapshot cleanup, durable
workspace preservation, replay identity, and LangGraph routing. They do not
measure Docker startup, pytest runtime, resource isolation strength, repair
quality, or host performance.

The optional real Docker smoke did not run. Docker client 29.7.2 was installed,
but the `desktop-linux` daemon endpoint was unavailable, so local image
inventory and the configured image could not be verified. This is environment
preflight evidence and a functional-smoke blocker, not a benchmark result.

## Later scoped evaluation

## M6 bounded-workflow functional evidence

M6 automated tests use deterministic fake inference providers and fake test
runners. They validate strict critic parsing/grounding, eligible-failure-only
routing, a hard two-attempt maximum, clean-baseline retry workspaces, final
hash/test-bound interrupt persistence, exact export, and replay isolation. They
do not measure critic quality, repair success rate, generation latency, Docker
runtime, throughput, or production reliability.

On 2026-09-12 the focused M6 set passed 32/32 and the complete backend suite
passed 266/266. Those counts are regression evidence only, not benchmark
results.

The optional real critic generation was not run: the automated acceptance path
was complete, while CPU-only `gemma4:e4b-it-qat` calls previously required
minutes and the task explicitly allowed skipping a materially delaying smoke.
A complete real M6 end-to-end smoke remains blocked by the unavailable local
Docker daemon/image prerequisite recorded under M5. This is a functional-smoke
blocker, not benchmark evidence.

## Later scoped evaluation

M8 will freeze a meaningful retrieval and safety case set before reporting
comparative metrics. M9 will evaluate a feasible frozen external task set and
complete-system behavior under the same two-checkpoint, two-attempt workflow.
No selected subset may be described as equivalent to a published full split.

V1 does not require a model-size benchmark matrix, vLLM, RAGAS, rerankers,
HyDE, query rewriting, full observability deployment, or cloud deployment.
Measured optimization belongs to M10 and must follow recorded evidence.
