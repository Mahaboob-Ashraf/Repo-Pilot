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

## ADR-006 - Reject malformed Python during repository chunking

**Status:** Accepted

**Decision:** Python parsing rejects a file whenever Tree-sitter reports an
erroneous tree. The parser raises a typed error containing the
repository-relative file path, first relevant `ERROR` or missing node kind, and
its 1-based source range. Repository chunking is fail-fast and returns no
partial result when any supported Python file is malformed.

**Why:** Silently extracting constructs from an uncertain syntax tree would
make the repository summary and later index look complete when their provenance
is not trustworthy. A single explicit failure is the smallest correct M1
policy and keeps malformed input distinguishable from a valid repository that
simply contains no supported constructs.

**Alternatives considered:** Index all recoverable constructs silently; return
partial chunks plus warnings; skip malformed files and continue.

**Tradeoffs:** One malformed Python file prevents chunking otherwise valid
files. Partial recovery could improve coverage for real repositories, but it
requires result-level diagnostics and evaluation that are outside M1.

**Testing/benchmark impact:** Parser and full-pipeline tests must prove malformed
input raises the typed error with relative provenance. Future partial-indexing
work must make incompleteness explicit and compare coverage against fail-fast
behavior before superseding this decision.

## ADR-007 - Explicit local embedding boundary and precomputed Chroma vectors

**Status:** Accepted

**Decision:** Embeddings use a provider boundary separate from generation. The
M2.2 baseline uses local Ollama `embeddinggemma`, embeds exact chunk source text
in deterministic batches, and supplies precomputed document/query vectors to a
Chroma collection with no Chroma embedding function. The collection uses
cosine distance and records provider, model, document-format, and distance
identity. Query results carry raw distance/rank separately from canonical
`CodeChunk` data.

**Why:** Generation and embedding models have different contracts and should
not be interchangeable. Explicit vector generation prevents Chroma from
silently loading a default model, preserves the zero-cost local path, and makes
the same-model indexing/query invariant auditable. Exact source text is the
smallest reproducible semantic document and avoids mixing repository data with
instructions or machine-specific paths.

**Alternatives considered:** Chroma's default embedding function;
sentence-transformers; cloud embedding APIs; using the Gemma generation model
for embeddings; embedding arbitrary metadata/prompts with source; treating
cosine distance as mutable chunk state.

**Tradeoffs:** Rebuilds recompute every vector, one model identity is bound to a
collection, and source-only documents may omit useful symbol/path signals.
Chroma adds a substantial transitive dependency set. These are acceptable for
the bounded baseline; incremental indexing and alternate document formats need
separate evaluation.

**Testing/benchmark impact:** Mock Ollama responses validate the HTTP contract;
deterministic fake embeddings validate Chroma behavior offline. Evaluation must
record model/digest, dimension, document format, distance space, Chroma version,
and corpus, and must compare ranks rather than directly mixing cosine distance
with BM25 scores.
