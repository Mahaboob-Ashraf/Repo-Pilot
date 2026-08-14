# RepoPilot Project Specification

## Thesis and scope

RepoPilot is a local-first, human-in-the-loop coding-agent platform. Given a GitHub repository or uploaded archive and an issue, it will build an AST-aware code index, retrieve relevant code through lexical and vector signals, plan a repair, propose scoped edits, run tests in an isolated sandbox, critique failures, iterate within hard limits, and pause for human approval before exporting a patch.

It is an evaluated developer tool, not a document chatbot, paid-API wrapper, autonomous merge bot, or complete IDE.

RepoPilot will provide repository ingestion; tree-sitter semantic chunks and dependency metadata; hybrid SQLite FTS5 BM25 and Chroma retrieval with Reciprocal Rank Fusion (RRF); a stateful planner/retriever/context-packer/patcher/test-runner/critic workflow; persisted human approvals; Docker-isolated tests; a React review studio; and retrieval, agent, inference, safety, system, and selected SWE-bench Lite evidence.

## Exact stack

| Area | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Agent orchestration | LangGraph with durable state and interrupts |
| Default inference | Ollama, local and API-key-free |
| Optional inference | vLLM for available GPU experiments |
| Model family | Gemma 4 E2B/E4B locally; 12B/26B/31B optional benchmark tiers |
| Embeddings | Local model through Ollama or sentence-transformers |
| Lexical/vector retrieval | SQLite FTS5 BM25 and Chroma persistent client |
| Parsing | tree-sitter Python bindings and language parsers |
| Patch/workspace | Git through a narrow adapter |
| Sandbox | Docker Engine and Docker Compose |
| Evaluation | Selected SWE-bench Lite subset and custom harnesses |
| Frontend | React, Vite, TypeScript, Monaco/diff viewer |
| Observability | Structured traces, OpenTelemetry, Prometheus; Grafana optional |
| CI | GitHub Actions for a public repository |

Lock Python dependencies with `uv.lock`, frontend dependencies with `package-lock.json`, container images with explicit tags, and model configurations in `models.lock.json`.

## Architecture and workflow

1. React Studio submits projects/issues and displays run state.
2. FastAPI owns project, index, run, approval, test, evaluation, and metrics APIs.
3. Ingestion creates an isolated Git workspace and detects languages.
4. tree-sitter creates function, class, method, module-header, test, and configuration chunks.
5. SQLite stores metadata, state, approvals, traces, and BM25 data; Chroma stores embeddings.
6. LangGraph plans, retrieves, packs context, proposes edits, applies approved diffs, runs tests, critiques failures, and stops at approval gates or limits.
7. Ollama serves local Gemma 4; a provider boundary permits optional vLLM later.
8. Docker runs repository tests with isolation and records command, output, exit status, duration, and image identity.

Required state includes run/project IDs, issue text, plan, retrieved chunk IDs, approvals, approved edit scope, patch diff, tests, iteration count, risk flags, and final status.

Initial policy targets: at most four patch-test-critic iterations; approval when more than three files are proposed; model-specific recorded context budgets; and a human-visible repository-specific sandbox timeout.

## Retrieval algorithm

- Index AST chunks with path, language, symbol, type, line range, imports/calls, hash, and provenance.
- Query BM25 and vector search separately, fuse positions using RRF, then add one-hop callers/callees/import neighbors.
- When packing a token budget, preserve tests, signatures, interfaces, and human-pinned chunks.
- Plans and patches cite the chunk IDs and source ranges used.
- Fixed-size chunks exist only as an evaluation baseline.

## APIs and data model

Planned endpoints are listed in `docs/api.md`; none is implemented yet.

Planned entities are `projects`, `chunks`, `fts_chunks`, a Chroma chunk collection, `runs`, `agent_events`, `approvals`, `patches`, `test_results`, and `benchmarks`. Approval records bind decisions to immutable payload or diff hashes.

## Security

- Separate untrusted repository context from system instructions.
- Normalize paths and reject traversal or edits outside the repository root and approved scope.
- No arbitrary host shell; allowlisted test commands run only inside Docker.
- Disable sandbox networking by default and enforce CPU, memory, process, token, iteration, and time limits.
- Detect/redact likely secrets before prompts or trace persistence.
- Dry-run patches and reject nonexistent or unapproved paths.

## Testing plan

- Unit: chunk extraction, path safety, RRF, context packing, patch parsing.
- Integration: index a toy repo, retrieve an expected file/symbol, dry-run a patch.
- Sandbox: known pass/fail, timeout, cleanup, resources, disabled network.
- Approval: interrupt/resume persistence and immutable approved scope.
- Regression/evaluation: known issues and SWE-bench artifact persistence.
- Security: prompt injection, traversal, forbidden commands, redaction, hallucinated paths.

## Benchmark plan

1. Compare fixed-size, AST, and AST-plus-graph retrieval using relevant-file hit@5, relevant-symbol hit@10, MRR, token use/waste, and graph-expansion gain.
2. Compare feasible Gemma 4 tiers using patch success, tokens/sec, TTFT, p50/p95 latency, peak RAM/VRAM, average iterations, context tokens, and rollback/rejection rate.
3. Develop on five SWE-bench Lite tasks, then target an explicit 20-50 task subset if feasible. Never imply full-leaderboard equivalence.

Every result records hardware, dataset and size, model/quantization/backend/context, prompt version, software versions, run count, method, and limitations. All results remain `Not measured` until executed.

## Proof artifacts

- Reproducible README/setup path and architecture diagram.
- Retrieval ablation and model benchmark reports.
- Selected SWE-bench task list, results, logs, patches, and failures.
- Trace archive containing state transitions, prompt hashes, chunk IDs, tool calls, approvals, diffs, and tests.
- Demo from issue through approval, sandbox tests, and final diff.
- Explicit limitations and failure analyses.

## Non-goals

- Perfect parsing for every language or generic document chat.
- Paid-provider-only operation or arbitrary host execution.
- Fully autonomous production merges or a full IDE.
- Claims of commercial-tool or leaderboard parity without the same protocol.
