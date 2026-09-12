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

**Decision:** For Python repositories, use tree-sitter semantic chunks, SQLite
FTS5 BM25, Chroma vectors, RRF, and one-hop import, parent-child, and
directly-related-test expansion.

**Why:** Exact identifiers and stack traces favor lexical search; issue semantics favor embeddings; code relationships require structural context.

**Alternatives considered:** Fixed-size chunks; vector-only; BM25-only; opaque managed search.

**Tradeoffs:** More indexing complexity and metadata, offset by explainable provenance and an ablation-friendly design.

**Testing/benchmark impact:** Compare fixed-size, AST, and AST-plus-graph variants on identical issues and token budgets.

## ADR-003 - Stateful graph with persisted human interrupts

**Status:** Accepted from source specification

**Decision:** In M3+, use LangGraph as the state-machine layer for one bounded
repair workflow. It owns shared run state, stage transitions, a conditional
test-failure branch, maximum-one-retry control, pause/resume, and persistence
where needed. V1 has exactly two human checkpoints: approval of the
evidence-grounded plan and file scope before patching, then approval of the
final diff before patch export.

**Why:** Coding runs are long-lived, failure-prone, and unsafe without resumable state and auditable control boundaries.

Planner, retriever, context packer, patcher, test runner, and critic are graph
nodes/stages, not an autonomous multi-agent swarm. LangChain is used selectively
inside LLM-backed nodes for prompt templates, message composition, structured
output parsing/schemas, and useful Runnable composition. Custom chunking,
BM25, Chroma retrieval, RRF, structural expansion, and context packing remain
RepoPilot-owned boundaries. LangGraph and LangChain are not installed before M3.

**Alternatives considered:** One-shot prompt; free-running loop; in-memory-only
orchestration; multi-agent swarm; five separate approval checkpoints; replacing
custom retrieval with generic LangChain wrappers.

**Tradeoffs:** Persistence and resumption are more complex, but behavior becomes
bounded, reviewable, and debuggable. Selective framework use adds dependencies
only where their concrete orchestration/composition value justifies them.

**Testing/benchmark impact:** Test both interrupt/resume points, immutable
payload hashes, rejections, restarts, the conditional failure branch, and the
hard two-attempt limit.

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

## ADR-008 - Scoped V1 boundary

**Status:** Accepted

**Decision:** V1 is a local-first, human-controlled coding agent for Python
repositories only. It uses one fixed Ollama generation model for primary
evaluation, two human checkpoints, approved-file-only edits, at most two repair
attempts total, restricted Docker tests, structured traces, and human-approved
patch export. It does not create or merge pull requests.

**Why:** A narrower end-to-end system makes the safety controls, retrieval
quality, workflow state, and evaluation evidence implementable and defensible.
It preserves the project's differentiating code-retrieval and human-control
work without turning completion into a broad platform or infrastructure effort.

**Alternatives considered:** Multi-language parsing; vLLM and a model-size
matrix; many-agent showcase; five approval checkpoints; full
Prometheus/Grafana/OpenTelemetry stack; RAGAS; full IDE; autonomous PR flow;
cloud deployment as a completion gate.

**Tradeoffs:** V1 demonstrates less breadth and does not optimize across model
tiers or deployment environments. In return, each promised capability has a
clear milestone, bounded proof obligation, and zero-cost local default path.

**Testing/benchmark impact:** Evidence and documentation must use the Scoped V1
milestones. Deferred capabilities must not appear as current requirements or
implemented claims.

## ADR-009 - Rank-only RRF, explicit dense degradation, and frozen evaluation

**Status:** Accepted

**Decision:** Hybrid retrieval fetches independently configurable candidate
depths from BM25 and dense retrieval, then scores each chunk as
`sum(1 / (k_rrf + rank))` across lists. Ranks are 1-based, `k_rrf` defaults to
the conventional initial baseline `60`, final ties break by canonical
`chunk_id`, and `top_k` is independent of candidate depth. Raw BM25 scores and
cosine distances remain inspectable metadata and never enter fusion math.

The vector layer translates expected embedding-provider and Chroma count/query
failures into a narrow `VectorRetrievalError`. Hybrid retrieval catches only
that boundary and returns the available BM25 ranking with an explicit
`lexical_only_degraded` mode and useful failure reason. It does not catch
arbitrary programming errors, claim normal hybrid success, or add retries.

Frozen retrieval cases contain a case ID, issue/query text, relative repository
reference, gold file paths, and optional gold symbols. Gold data is passed only
to scoring. The M2B harness independently runs `ast_bm25`, `ast_dense`, and
`ast_hybrid_rrf` and records ranked provenance, file Hit@1/Hit@5, symbol Hit@5
when labels exist, separate file/symbol reciprocal rank, boundary latency, and
degraded status.

**Why:** BM25 and cosine distance have different scales and directions, while
ranks provide a stable explainable fusion boundary. Explicit degradation keeps
the local workflow useful during embedding failure without corrupting evidence.
Frozen cases make evaluation reproducible and prevent labels from improving the
queries they score.

**Alternatives considered:** Normalizing and adding raw scores; a learned
reranker; hiding dense failures; retry infrastructure; leaking gold symbols
into query expansion; introducing fixed-size chunks or structural expansion in
M2B.

**Tradeoffs:** RRF discards score magnitude and the default constant is not
empirically tuned. Small controlled cases validate only implementation and
metrics, not retrieval quality. Dense-only evaluation still surfaces provider
failures rather than silently falling back.

**Testing/benchmark impact:** Unit tests use hand-calculated ranks and
deterministic fake embeddings. Context precision, waste, and token metrics were
deferred to M2C. Controlled fixture outputs are harness-validation evidence,
not benchmark or SWE-bench results.

## ADR-010 - One-hop structural evidence and whole-chunk context budgets

**Status:** Accepted

**Decision:** Build a small in-memory `StructuralIndex` over canonical chunk
IDs using only deterministic current metadata. Supported directed edges are
method-to-parent class, class-to-direct-child method, exact matched local-module
import, and directly-related test backed by a source-module import or exact
source-symbol reference. Expansion traverses only the original hybrid results;
newly added chunks are never seeds.

Direct hybrid results remain first by rank. Structural-only candidates follow
in `parent`, `related_test`, `imported_module`, then `child` priority, with
stable seed/chunk-ID ties. Candidates are deduplicated, all structural causes
are retained, and direct provenance wins when a chunk is both retrieved and
reachable. Structural-only chunks receive no invented retrieval scores.

The immutable `ContextPack` includes complete rendered evidence blocks under a
hard configured budget and propagates retrieval degradation. The default
replaceable counter uses UTF-8 byte length as conservative estimated units, not
exact model tokens. Chunks are never split or silently truncated. Non-fitting
lower-priority chunks are excluded; if the first chunk cannot fit, the pack
returns `oversized_highest_priority` rather than substituting weaker evidence.
Issue and repository source are rendered in explicit untrusted-data regions.

**Why:** One deterministic hop supplies nearby code/tests that rank-only text
retrieval may omit while keeping context growth explainable and bounded. A
single immutable pack makes the future planner input auditable, and whole-chunk
packing preserves exact source provenance.

**Alternatives considered:** Recursive or transitive graph traversal; a graph
database; semantic test linking; a full Python import resolver; score-based
structural reranking; source truncation or secondary splitting; adding a large
tokenizer dependency; allowing evaluation gold labels into expansion/packing.

**Tradeoffs:** Exact import matching misses aliases, relative imports, and more
complex package resolution. Related-test rules may add every test chunk in a
module that explicitly imports the source module. UTF-8 byte estimates can
under-utilize a model's real context window, and whole oversized chunks produce
an explicit empty/error-status pack instead of partial code. These constraints
favor safety and determinism over recall and density in the M2C baseline.

**Testing/benchmark impact:** Offline fixtures prove each edge type, exactly
one hop, deterministic ordering, deduplication, hard budgets, no truncation,
degradation propagation, evidence delimiters, and post-pack gold isolation.
Context coverage, file/symbol precision, token waste, and budget utilization
are now valid harness metrics. Controlled fixture and toy smoke observations
remain non-benchmark evidence.
