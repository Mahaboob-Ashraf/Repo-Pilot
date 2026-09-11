# RepoPilot Benchmark Plan

No benchmarks have run. Every result is currently **Not measured**.

## Evidence record required for every run

- Date and commit SHA
- Hardware: CPU, RAM, GPU/VRAM, operating system
- Dataset name, version, exact instances, and count
- Model, quantization, backend, context window, and prompt/template version
- Embedding/reranker versions and retrieval configuration
- Software/container versions
- Warm-up, number of runs, aggregation method, and timers
- Failures, exclusions, uncertainty, and known limitations

## Retrieval ablation

Compare on the same issue set and relevance labels:

| Variant | Relevant-file hit@5 | Relevant-symbol hit@10 | MRR | Avg context tokens | Token waste | Notes |
|---|---:|---:|---:|---:|---:|---|
| Fixed-size baseline | Not measured | Not measured | Not measured | Not measured | Not measured | Baseline only |
| AST chunks | Not measured | Not measured | Not measured | Not measured | Not measured | Preserve semantic units |
| AST + graph expansion | Not measured | Not measured | Not measured | Not measured | Not measured | One-hop dependencies |

Define relevance labels and token waste before running the benchmark.

### SQLite FTS5 lexical baseline

The implemented lexical baseline indexes semantic `CodeChunk` source, symbol,
qualified symbol, path, chunk type, and imports with SQLite FTS5 `unicode61`.
It uses safely quoted OR-token queries and fixed weighted `bm25()` ranking.
Raw SQLite scores sort ascending because smaller, more negative values are
better; `chunk_id` provides deterministic tie-breaking.

The toy-repository searches used to verify Task 009 are functional tests, not a
retrieval benchmark. No hit-rate, MRR, latency, or quality value has been
measured. A future baseline run must freeze queries and relevance judgments,
record the SQLite version, tokenizer, field weights, top-k, corpus/chunk count,
hardware, run count, and timing method, and report filename/import ambiguity as
an observed error category.

### Chroma vector baseline

The implemented vector baseline uses precomputed embeddings from the separate
RepoPilot `EmbeddingProvider`, exact `CodeChunk.source_text` documents, and a
local Chroma 1.5.9 collection configured for cosine distance. The locked local
runtime/model default is Ollama `embeddinggemma`; generation remains assigned
to `gemma4:e4b-it-qat`. The same provider/model identity is required for index
and query embeddings.

Automated toy tests use an explicitly labeled deterministic fake provider so
they can verify vector ordering, provenance, rebuilds, stale-record removal,
and model mismatch behavior without Ollama, a model download, or network
access. Those fake distances do not measure EmbeddingGemma quality. The real
model was not installed during Task 010, so no real dimension, latency, or
quality value has been measured.

A future vector baseline must record the exact Ollama model tag/digest,
embedding dimension, Chroma version, cosine configuration, document format,
corpus/chunk count, queries and relevance labels, top-k, hardware, warm-up,
run count, and timing method. Compare ranks rather than combining raw cosine
distances with BM25 scores directly.

## Model/inference comparison

Test only tiers supported by available hardware. A larger model is not presumed better under a fixed time budget.

| Model | Backend | Patch success | Tokens/sec | TTFT | Peak memory | p50/p95 run latency | Avg iterations |
|---|---|---:|---:|---:|---:|---:|---:|
| Gemma 4 E2B | Ollama | Not measured | Not measured | Not measured | Not measured | Not measured | Not measured |
| Gemma 4 E4B | Ollama | Not measured | Not measured | Not measured | Not measured | Not measured | Not measured |
| Larger available tier | Ollama/vLLM | Not measured | Not measured | Not measured | Not measured | Not measured | Not measured |

## SWE-bench Lite path

Start with five development tasks to validate setup. If feasible, freeze and publish a selected 20-50 task subset before evaluation. Save instance IDs, environment images, configs, generated patches, test logs, resolved/unresolved status, stop reason, and failures.

Never compare a selected-subset result as equivalent to a published full-split baseline.
