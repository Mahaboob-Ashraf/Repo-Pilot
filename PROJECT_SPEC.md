# RepoPilot Project Specification

## Scoped V1 thesis

RepoPilot is a local-first, human-controlled coding agent for Python
repositories. Its one bounded workflow is:

```text
repository + issue
    -> AST-aware repository evidence
    -> BM25 + dense retrieval
    -> Reciprocal Rank Fusion (RRF)
    -> one-hop structural expansion
    -> bounded context pack
    -> evidence-grounded repair plan
    -> human approval
    -> scoped patch
    -> Docker tests
    -> optional critic-assisted one retry
    -> final human approval
    -> patch export
```

RepoPilot is an evaluated developer tool, not a repository chatbot, paid-API
wrapper, autonomous merge bot, multi-agent swarm, or complete IDE.

## Locked V1 scope

- Python repositories only.
- Python 3.11+ and FastAPI/Uvicorn backend; React/Vite/TypeScript review UI.
- Tree-sitter semantic code chunks with immutable source provenance.
- SQLite FTS5/BM25 lexical retrieval and local-embedding Chroma dense retrieval.
- Rank-only RRF followed by one-hop import, parent-child, and directly-related
  test expansion.
- Fixed token-budget context packing.
- One fixed Ollama generation model for primary evaluation.
- Two human checkpoints: plan/approved-file scope, then final patch export.
- Approved-file-only patching and a maximum of two repair attempts total.
- Docker test execution with network, time, process, CPU, and memory restrictions.
- Structured run traces and patch export, never autonomous PR creation or merge.

The default path is local, API-key-free, and zero-cost apart from the user's
own hardware and electricity.

## Exact V1 stack

| Area | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Workflow orchestration (M3+) | LangGraph state machine with persistence/interrupts where needed |
| Selective LLM composition (M3+) | LangChain prompt/message/structured-output/Runnable utilities where useful |
| Default inference | One fixed local Ollama generation model for primary evaluation |
| Embeddings | Local model through the RepoPilot embedding-provider boundary |
| Lexical/vector retrieval | SQLite FTS5 BM25 and Chroma with precomputed embeddings |
| Parsing | tree-sitter Python parser and semantic chunks |
| Patch workspace | Git through a narrow approved-path adapter |
| Test sandbox | Docker with disabled-by-default networking and explicit limits |
| Frontend | React, Vite, TypeScript, and a focused review workspace |
| Evidence | Structured local run traces and frozen evaluation artifacts |

Lock Python dependencies with `uv.lock`, frontend dependencies with
`package-lock.json`, container images with explicit tags, and model identities
in `models.lock.json`.

## One bounded repair workflow

LangGraph is introduced in M3 as the orchestration and state-machine layer for
this single workflow. In M3 it owns the planner, first human approval interrupt,
approve/reject transitions, and checkpoint persistence. Later milestones add the
remaining stage transitions, the conditional test-failure branch,
maximum-one-retry control, and the second human pause. Planner,
retriever, context packer, patcher, test runner, and critic are nodes/stages of
one bounded graph; they must not be described as an autonomous multi-agent
swarm.

LangChain is used selectively inside the M3 planner for prompt templating and
Pydantic structured-output parsing. It may be used inside later LLM-backed nodes
when message composition or Runnable composition provides concrete value.
RepoPilot's custom `CodeChunk` pipeline,
SQLite/BM25 retrieval, Chroma retrieval, RRF, structural expansion, and context
packing remain first-party boundaries and are not replaced merely to add a
framework. The existing RepoPilot `InferenceProvider` remains the generation
boundary.

Required future run state includes repository/run identity, issue text,
retrieved chunk IDs and provenance, packed context, plan, approved file set,
patch/diff hashes, test evidence, attempt count, checkpoint decisions, risk
flags, degradation state, and final status.

## Retrieval algorithm

1. Build Python tree-sitter function, class, method, and test chunks with path,
   symbol, type, line range, imports, exact source hash, and provenance.
2. Query SQLite FTS5 BM25 and Chroma dense retrieval independently.
3. Fuse 1-based ranks with RRF; never add or normalize raw BM25 and cosine
   values across their incompatible scales.
4. Expand one hop through imports, parent-child relationships, and
   directly-related tests.
5. Pack evidence under a fixed token budget while preserving provenance and
   prioritizing tests, signatures, interfaces, and human-pinned chunks.

If dense retrieval is unavailable, retrieval continues with BM25 and records an
explicit degraded lexical-only state. Fixed-size chunks remain a later
evaluation baseline, not the V1 code-RAG representation.

## Evaluation

Retrieval evaluation uses frozen cases whose gold paths/symbols are scoring data
only and never query input. Retrieval metrics are relevant-file Hit@1/Hit@5,
relevant-symbol Hit@5 where symbol labels exist, explicit file and symbol
reciprocal rank, and per-case retrieval wall-clock latency. M2C also measures
file/symbol context coverage, file/symbol chunk precision and token waste, and
budget utilization against completed ContextPacks.

Later safety, repair, external, and system evaluation must freeze inputs and
record environment, model, configuration, run count, method, failures, and
limitations. Controlled toy cases prove harness behavior; they are not
SWE-bench or public benchmark results.

## Security and human authority

- Treat repository content, issue text, tool output, and model output as
  untrusted data, not instructions.
- Normalize paths and reject traversal or edits outside the repository root and
  the first checkpoint's approved file set.
- Allowlisted repository tests execute only in Docker, with networking disabled
  by default and explicit time/resource/process limits.
- A model proposes plans and patches but cannot approve, export, or merge them.
- Bind checkpoint decisions to immutable reviewed payload/diff hashes.
- Stop after the initial repair plus at most one critic-assisted retry.
- Export a patch only after final human approval; never create or merge a PR.
- Detect or redact likely secrets before prompts, traces, fixtures, or logs.

## Canonical milestone sequence

- M2A — Dense vector index + embedding pipeline — Complete
- M2B — RRF + retrieval benchmark harness — Complete
- M2C — One-hop structure + context packer — Complete
- M3 — Plan + approval state using LangGraph; selective LangChain — Complete
- M4 — Scoped patch workspace
- M5 — Docker test runner
- M6 — Critic + one retry + final review
- M7 — React review workspace
- M8 — Retrieval + safety evaluation
- M9 — External + system evaluation
- M10 — Measured optimization + polish

## Explicit V1 non-goals

- Model-size benchmark matrix or vLLM.
- Multi-language parsing.
- A many-agent showcase or autonomous multi-agent swarm.
- Five approval checkpoints.
- Prometheus/Grafana/OpenTelemetry stack.
- RAGAS.
- Full IDE scope.
- Autonomous PR creation or merge.
- Rerankers, HyDE, or query rewriting without later benchmark evidence.
- Cloud deployment as a completion requirement.
- Unsupported full-leaderboard or commercial-tool comparison.
