# RepoPilot Architecture Decisions

Decisions are recorded before implementation claims. Status may be Proposed, Accepted, Superseded, or Rejected.

## ADR-001 - Local-first, zero-cost default

**Status:** Accepted from source specification

**Decision:** The default path uses local Ollama, local SQLite/Chroma, and local Docker without a paid API key.

**Why:** The project must be reproducible at zero spend and demonstrate ownership of inference, retrieval, and evaluation.

**Alternatives considered:** Paid hosted LLM/vector services; cloud-only deployment.

**Tradeoffs:** Local models may be weaker and hardware-constrained; setup is heavier but behavior and cost are inspectable.

**Testing/benchmark impact:** Record local hardware and model configuration. Optional providers cannot define the core proof path.

## ADR-002 - AST-aware hybrid retrieval

**Status:** Accepted from source specification

**Decision:** Use tree-sitter semantic chunks, SQLite FTS5 BM25, Chroma vectors, RRF, and dependency-neighbor expansion.

**Why:** Exact identifiers and stack traces favor lexical search; issue semantics favor embeddings; code relationships require structural context.

**Alternatives considered:** Fixed-size chunks; vector-only; BM25-only; opaque managed search.

**Tradeoffs:** More indexing complexity and metadata, offset by explainable provenance and an ablation-friendly design.

**Testing/benchmark impact:** Compare fixed-size, AST, and AST-plus-graph variants on identical issues and token budgets.

## ADR-003 - Stateful graph with persisted human interrupts

**Status:** Accepted from source specification

**Decision:** Use a LangGraph-style workflow with persisted plan, context, edit-scope, patch, and export approvals.

**Why:** Coding runs are long-lived, failure-prone, and unsafe without resumable state and auditable control boundaries.

**Alternatives considered:** One-shot prompt; free-running loop; in-memory-only orchestration.

**Tradeoffs:** Persistence and resumption are more complex, but behavior becomes bounded, reviewable, and debuggable.

**Testing/benchmark impact:** Test interrupt/resume, immutable payload hashes, rejections, restarts, and stop limits.

## ADR-004 - Docker-only execution for ingested repository tests

**Status:** Accepted from source specification

**Decision:** Test commands for ingested repositories run in isolated Docker containers with networking disabled by default and explicit resource/time limits.

**Why:** Repository code and commands are untrusted.

**Alternatives considered:** Host subprocesses; language virtual environments; remote sandboxes.

**Tradeoffs:** Docker startup and dependency setup add latency and platform constraints, but materially reduce host risk.

**Testing/benchmark impact:** Prove timeout, network isolation, resource controls, log capture, cleanup, and image identity.
