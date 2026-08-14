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
