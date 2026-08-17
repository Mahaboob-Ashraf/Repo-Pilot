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

## ADR-005 - Separate semantic chunk identity from source-content identity

**Status:** Accepted

**Decision:** M1 code chunks use deterministic, human-readable IDs in the form
`{repository-relative path}::{chunk type}::{qualified symbol}::{start
line}-{end line}`. They separately store the lowercase SHA-256 digest of the
exact UTF-8 source text. Class chunks and their method chunks are both retained,
even though their source ranges overlap.

**Why:** Paths, construct types, qualified symbols, and ranges provide stable,
inspectable provenance for citations and later indexes. Absolute paths would
make identity machine-specific, while random UUIDs would prevent reproducible
rebuilds and complicate evaluation comparisons. A separate content digest
detects implementation changes that preserve semantic location and therefore
do not change the chunk ID.

**Alternatives considered:** Random UUIDs; absolute-path IDs; content hashes as
the sole chunk identity; suppressing method chunks when a class chunk already
contains their text.

**Tradeoffs:** Identical relative constructs in different repositories require
a future stable repository namespace when persisted together. Line movement
changes semantic IDs, and class/method overlap can consume retrieval context.
Keeping both representations preserves useful context until retrieval and
context-packing measurements justify deduplication.

**Testing/benchmark impact:** Repeated builds must produce identical IDs and
hashes; source-only changes must alter the hash; IDs must not expose absolute
paths. Later indexing and retrieval evaluation must measure duplicate-result
and token-budget effects from class/method overlap.
