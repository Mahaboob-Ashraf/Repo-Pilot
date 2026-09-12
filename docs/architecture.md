# RepoPilot Architecture

## Implemented M0 boundary

```text
Browser
    -> React prompt screen
        -> frontend inference API client
            -> FastAPI POST /api/inference (restricted local CORS)
                -> InferenceProvider protocol
                    -> OllamaProvider (async local HTTP)
                        -> Ollama / gemma4:e4b-it-qat
```

The browser never calls Ollama directly. `VITE_API_BASE_URL` selects the
FastAPI development origin, while the backend allows only the expected local
Vite origins. The UI handles blank input, loading, generated response, returned
model identifier, and readable API/network errors.

The code path and automated frontend/backend tests are implemented. The user
manually verified the real browser-to-Ollama path after Task 003.

## Implemented M1 parsing foundation

```text
Supplied local repository root
    -> root validation
        -> deterministic source-file discovery
            -> extension-based language inventory
                -> parser-supported Python paths
                    -> resolved path-containment validation
                        -> Tree-sitter Python parser
                            -> PythonConstruct + module import metadata
                                -> deterministic semantic CodeChunk records
                                    -> RepositoryChunkingResult summary
```

`backend/app/ingestion/discovery.py` is a read-only local discovery layer. It
returns provisional repository/file records with resolved repository root,
POSIX-relative source paths, detected language, parser-support status, byte
size, and language counts. Discovery is globally sorted by relative path.

Scoped V1 accepts Python repositories only. The current discovery inventory
still recognizes JavaScript and TypeScript extensions as unsupported legacy
metadata, but no V1 parser, retrieval, or repair support is planned for them.
Unsupported or non-source extensions are not inferred from content.

Discovery prunes `.git`, virtual environments, dependency/build outputs, and
common tool caches. It does not implement `.gitignore`. Directory traversal
does not follow symlinks, and symlinked files are omitted.

`backend/app/chunking/python_parser.py` currently supports Python source only.
It extracts top-level functions, classes, direct class methods, and pytest-style
top-level functions whose names start with `test_`. Results use POSIX-style
repository-relative paths, 1-based inclusive line numbers, exact source bytes
decoded as UTF-8, and parent-class context for methods. The same Tree-sitter
parse also extracts a sorted, deduplicated tuple of top-level imported module
names. Function-local imports and call relationships are intentionally absent.

`PythonConstruct` remains the parser-facing extraction result.
`backend/app/chunking/code_chunks.py` maps those constructs into provisional
immutable `CodeChunk` records for functions, classes, methods, and tests. Each
chunk contains exact source, repository-relative provenance, semantic identity,
module imports, and a lowercase SHA-256 hash of the exact UTF-8 source text.

Chunk IDs use this machine-independent format:

```text
{path}::{chunk_type}::{qualified_symbol}::{start_line}-{end_line}
```

For example, `pricing.py::function::apply_discount::4-7`. A method uses its
class-qualified symbol, such as `Greeter.greet`. The content hash is separate
from this stable semantic/location identity, so a same-range implementation
change can be detected without changing the chunk ID.

Class chunks intentionally overlap their separately emitted method chunks in
M1. This preserves both class context and directly retrievable methods; later
retrieval and context-packing evaluation will determine whether both should be
returned together. The builder emits each parsed construct once and sorts
chunks by path, source range, type, and qualified symbol.

`backend/app/chunking/pipeline.py` is the single repository-level M1 entry
point. `build_repository_chunks(root)` reuses discovery, the registered Python
parser, and chunk conversion, returning a `RepositoryChunkingResult` with the
resolved root for internal use, discovered file metadata and count, language
counts, parser-supported relative paths and count, semantic chunks, and chunk
count. An unchanged repository produces an equal result on repeated runs.
The earlier `build_code_chunks(root)` helper remains as a compatibility wrapper
that returns only the result's chunk tuple.

A valid repository with no recognized files returns a successful empty result.
A repository containing only recognized JavaScript/TypeScript files retains
its discovery and language summary but returns no parser-supported paths or
chunks. Invalid roots retain the discovery layer's explicit error behavior.

Python parsing is fail-fast for malformed syntax. If Tree-sitter marks the
syntax tree as erroneous, the parser locates the first `ERROR` or missing node
and raises `PythonSyntaxError` with its repository-relative path and 1-based
line range. The repository build aborts rather than returning a partial result
that could appear complete. Partial recovery is deferred until it has explicit
representation and evaluation requirements.

Git/URL/archive ingestion, module-header/configuration chunks, project-level
persistence, and reranking remain unimplemented. Dense retrieval, rank fusion,
one-hop relationships, and context packing are described below.

## Implemented M2 lexical retrieval foundation

```text
RepositoryChunkingResult.chunks
    -> SQLiteLexicalIndex.rebuild
        -> canonical lexical_chunks rows
        -> searchable lexical_chunks_fts projection
            -> safe tokenized MATCH query
                -> FTS5 bm25()
                    -> canonical CodeChunk + rank + raw BM25 score
```

`backend/app/retrieval/lexical.py` owns the bounded local lexical index. The
normal `lexical_chunks` table stores enough canonical metadata to reconstruct
each immutable `CodeChunk`. The separate FTS5 virtual table stores searchable
copies of source text, symbol, qualified symbol, path, chunk type, and imports;
`chunk_id` is unindexed and joins results back to canonical provenance.

FTS5 uses its default `unicode61` tokenizer. User input is reduced to
case-folded word tokens, each token is quoted, and tokens are joined with `OR`.
Both the MATCH expression and top-k limit are SQL parameters, so callers cannot
inject SQL or raw FTS operators. Blank queries and nonblank queries without a
searchable token are rejected explicitly.

The FTS projection applies fixed BM25 column weights of `1` for source, `6`
for symbol, `6` for qualified symbol, `3` for path, `1` for chunk type, and `2`
for imports. SQLite FTS5's raw `bm25()` convention is preserved: smaller, more
negative values are better. SQL orders scores ascending and then orders equal
scores by `chunk_id`; the returned rank is 1-based. Scores are retrieval
metadata and never mutate `CodeChunk`.

Rebuilds sort input by `chunk_id` and replace both tables in one transaction.
Duplicate IDs in one input collection are rejected before mutation. The index
can be in-memory or backed by one explicitly supplied local SQLite file; no
global machine state or broader project database schema is introduced.

Token overlap can outweigh apparent filename intent. In the toy repository,
`pricing.py` matches the function path but also matches test paths and their
`pricing` import metadata, so raw BM25 ranks the test chunks first for that
query. Exact symbol and test-name queries rank their intended chunks first.
This is retained as baseline behavior for later retrieval evaluation rather
than hidden behind an unmeasured heuristic boost.

## Implemented M2.2 vector retrieval foundation

```text
RepositoryChunkingResult.chunks
    -> exact source_text embedding documents
        -> EmbeddingProvider.embed_batch
            -> OllamaEmbeddingProvider POST /api/embed
                -> RepoPilot-supplied vectors
                    -> Chroma cosine collection
                        -> query embedding from the same provider/model
                            -> canonical CodeChunk + rank + cosine distance
```

Embedding is a separate provider responsibility from text generation.
`EmbeddingProvider` exposes provider/model identity plus single and batch
operations. `OllamaEmbeddingProvider` uses the local HTTP API and defaults to
`embeddinggemma`, independently of the configured `gemma4:e4b-it-qat`
generation model. Its batch response validation rejects unreachable/HTTP
failures, invalid JSON or objects, missing vectors, cardinality mismatches,
empty/non-finite vectors, and inconsistent dimensions without hardcoding a
model dimension.

The baseline embedding document is exactly `CodeChunk.source_text`. Paths,
prompts, instructions, timestamps, and other metadata are not concatenated
into model input. Repository code therefore remains data, while Chroma stores
canonical metadata separately for provenance reconstruction.

`ChromaVectorIndex` accepts an injected Chroma client for isolated tests or an
explicit persistence directory for the local product path. It creates the
collection with `embedding_function=None`, receives precomputed document and
query vectors from RepoPilot, and configures only the HNSW `space` as `cosine`.
No implicit Chroma model/download or custom ANN tuning is allowed.

The collection ID is the canonical `chunk_id`. Documents store exact source;
metadata stores relative path, language, chunk type, symbol, qualified symbol,
optional parent class, 1-based range, content hash, and imports. Collection
metadata binds the provider, embedding model, source-document format, and
distance space. Opening/querying with a mismatched identity fails explicitly.

Rebuild embeds chunks in sorted chunk-ID order, deletes only the bounded
collection, recreates it, and inserts exactly the supplied set. Duplicate
input IDs are rejected before embedding or mutation, and stale records cannot
survive. Incremental updates are intentionally deferred.

Vector results keep the canonical `CodeChunk` immutable and add a 1-based rank
and raw Chroma cosine distance. Smaller distance means closer. Chroma may
return a tiny negative epsilon for an exact match because of floating-point
precision; the raw value is preserved rather than mislabeled as similarity.
Equal returned distances are secondarily ordered by chunk ID where practical.

## Implemented M2B hybrid retrieval and evaluation foundation

```text
issue query
    -> SQLiteLexicalIndex.search_lexical(candidate_k)
    -> ChromaVectorIndex.search_vector(candidate_k)
        -> 1-based lexical/vector ranks
            -> score(d) = sum(1 / (k_rrf + rank(d)))
                -> deterministic HybridSearchResult top_k
```

`backend/app/retrieval/hybrid.py` coordinates the existing retrievers without
changing their score semantics. `candidate_k` controls how many items each
modality supplies; `top_k` independently controls the fused output size. Both
are positive integers and need not be equal. The conventional initial
`k_rrf=60` baseline is configurable and is not a measured optimum.

`HybridSearchResult` wraps the unchanged canonical `CodeChunk` with fused rank,
RRF score, optional lexical/vector ranks, optional raw BM25/cosine values, and
explicit source membership. RRF uses ranks only. Raw BM25 and cosine distance
have incompatible scales and directions, so they remain diagnostic metadata
and are never normalized or added. Equal fused scores break by `chunk_id`.

`ChromaVectorIndex.search_vector()` translates expected embedding-provider and
Chroma count/query failures into the narrow `VectorRetrievalError` boundary.
The hybrid layer catches only that boundary and produces a
`HybridSearchResponse` in explicit `lexical_only_degraded` mode with unchanged
BM25 results and a useful reason. A successful dense call produces `hybrid`
mode. This is a fallback, not a retry system; query validation and unexpected
programming errors propagate normally.

`backend/app/evaluation/` defines immutable JSON-friendly retrieval cases,
variant adapters, per-case results, and aggregates. The harness accepts only
the case query at the retriever boundary; gold file paths and optional symbols
remain scoring data. Implemented retrieval variants are `ast_bm25`,
`ast_dense`, and `ast_hybrid_rrf`. Fixed-size chunk evaluation remains
deferred; M2C adds a separate post-pack `hybrid_structure` context variant.

Per-case metrics are relevant-file Hit@1, relevant-file Hit@5,
relevant-symbol Hit@5 when symbol gold exists, file reciprocal rank, symbol
reciprocal rank when symbol gold exists, wall-clock retrieval latency, ranked
chunk provenance, and degradation status. Missing symbol gold yields `None`
and is excluded from symbol aggregates. Aggregate p50/p95 latency uses the
deterministic nearest-rank method only with at least five cases. The four
controlled toy cases validate harness behavior only; they are not benchmark or
SWE-bench results.

## Implemented M2C one-hop structure and bounded context

```text
HybridSearchResponse
    -> StructuralIndex over canonical chunk IDs
        -> expand only original hybrid seeds by one hop
            -> deterministic, deduplicated expanded candidates
                -> ContextPacker whole-chunk budget enforcement
                    -> immutable ContextPack
```

`backend/app/retrieval/structural.py` derives a small in-memory adjacency index
from existing `CodeChunk` metadata; it is not a graph database. Supported
directed relationships are method-to-parent class, class-to-direct-child
methods, importing chunk-to-chunks in an exactly matched local module, and
source chunk-to-directly-related test. A related test requires its module to
import the source module or its exact source to reference the source symbol.
Imports are resolved only when a normalized repository `.py` path maps
unambiguously to the exact recorded import name. Standard-library and
third-party imports therefore add nothing unless a same-named local module is
actually present; this is deliberately not a full Python import resolver.

Only original hybrid results are expansion seeds. Newly added chunks are never
traversed, so a local import reached from a seed cannot lead to that module's
own imports. Candidate order is all directly retrieved chunks by hybrid rank,
then structural-only chunks by relation priority: `parent`, `related_test`,
`imported_module`, `child`. Ties use seed rank, seed chunk ID, then target chunk
ID. A chunk reached from multiple seeds appears once with all causes; if it was
also directly retrieved, its direct origin and retrieval rank take precedence
while structural causes remain inspectable. No BM25, cosine, or RRF values are
invented for structural-only evidence.

`backend/app/context_packing/` converts this expansion result into an immutable
`ContextPack`. It records issue text, whole included canonical chunks and
provenance, evidence origin and structural causes, source retrieval ranks,
per-item counted cost, total/base cost, configured budget, exclusions, packing
status, and propagated hybrid degradation state. Packing keeps all direct
retrieval results ahead of structural-only additions and preserves the
expander's deterministic order within each group. Duplicate IDs are removed
defensively and direct provenance wins.

`TokenCounter` is replaceable. The dependency-free production baseline counts
UTF-8 bytes as deterministic conservative estimated units; it does not claim
exact Gemma tokens. Tests inject an exact deterministic fake counter. The
budget includes issue/evidence framing and each complete rendered evidence
block. Source is never split or truncated: a non-fitting candidate is excluded,
and when the highest-priority chunk cannot fit, the pack reports
`oversized_highest_priority` with no lower-priority substitution. A future
model-exact local tokenizer can replace the estimator without changing packing
policy.

Rendering labels issue text and repository source as untrusted data, delimits
each verbatim source block, and keeps instructions outside repository evidence.
This is the exact bounded evidence object M3 places into the planner prompt;
the planner does not receive the complete repository.

Post-pack evaluation is a separate gold-aware scoring step. The
`hybrid_structure` context variant records included order/provenance, pipeline
latency, pack/degradation status, file/symbol coverage, explicit file/symbol
chunk precision, explicit file/symbol token waste, and budget utilization.
Gold labels never cross the retrieval/expansion/packing boundary.

## Implemented M3 evidence-grounded plan and first approval

```text
ContextPack
    -> deterministic PlanningContextSnapshot
        -> LangChain PromptTemplate
            -> existing RepoPilot InferenceProvider
                -> LangChain PydanticOutputParser[RepairPlan]
                    -> deterministic evidence/path grounding validator
                        -> canonical JSON SHA-256 plan hash
                            -> LangGraph approval interrupt
                                -> approved_for_patch OR rejected -> END
```

`backend/app/planning/` defines strict frozen Pydantic models for
`RepairPlan`, ordered `RepairStep` records, and a JSON-friendly evidence
snapshot derived from the immutable ContextPack. The planner prompt repeats
that workflow instructions and human authority are authoritative while issue
text and repository source/comments/docstrings are untrusted data. LangChain
is used concretely for f-string `PromptTemplate` rendering and
`PydanticOutputParser`; RepoPilot still calls its own async
`InferenceProvider`. There is no generic agent executor, LangChain retriever,
vector-store wrapper, or hidden retry.

Parsing is followed by first-party grounding validation. Every cited chunk ID
must occur in the exact packed evidence, every proposed or affected file must
be a canonical repository-relative POSIX path represented by that evidence,
each step must cite evidence, and at least one concrete step must exist.
Unknown citations and paths are errors; they are never repaired silently.
Validated plans are hashed from compact canonical JSON with sorted object keys
and SHA-256. No timestamp, machine path, or random value enters plan identity.

`backend/app/workflow/` contains one `StateGraph`, not a multi-agent system.
The M3 segment is `START -> planner -> approval -> approved|rejected`; typed
planner failures terminate before approval, rejection ends, and M4 can continue
from `approved`. Checkpoint-friendly
state stores issue text, rendered context, chunk/path provenance, context and
retrieval/degradation status, validated plan/hash, workflow status, explicit
approval decision, reviewer comment, and approved file scope. Provider and
checkpoint service objects are graph-construction dependencies and are not
persisted in state.

Expected inference-provider failures preserve Python exception chaining in the
planner process and become a bounded JSON checkpoint diagnostic: top-level
planner type/message, allowlisted provider type/classification/message, and
model name. Only known safe Ollama response messages such as an HTTP status are
retained verbatim. Availability and unknown provider text become generic safe
messages, so credentials, headers, request bodies, arbitrary exception objects,
and other request internals do not enter graph state.

The approval node constructs a JSON payload containing the complete plan, plan
hash, proposed file scope, cited evidence provenance, and the review question,
then calls LangGraph `interrupt()`. All work before the interrupt is pure and
deterministic because LangGraph restarts the node on resume. Resume accepts
only `{decision: approve|reject, plan_hash, comment?}`. The service prevalidates
the object and current checkpoint hash without consuming an invalid/stale
decision; the node validates them again when resumed.

Approval records the exact hash and freezes the validated proposed file list as
`approved_file_scope` with status `approved_for_patch`. Rejection has terminal
status `rejected` and no approved scope. With the M4 patch service configured,
the approved state continues into the patch node; the M3-only construction
still terminates there for focused compatibility tests.

Tests use `InMemorySaver`. The durable local boundary uses
`AsyncSqliteSaver` from `langgraph-checkpoint-sqlite` so the async provider and
graph remain nonblocking. Callers supply the stable `thread_id`; the same ID is
required to resume the corresponding interrupt. Checkpoint database paths are
absolute and enforced outside the source repository. Reconstructing the
workflow/service over the same SQLite file resumes the paused checkpoint.

## Implemented M4 approved-scope patch workspace

```text
approved_for_patch
    -> exact plan/hash/scope and evidence-freshness validation
        -> durable isolated workspace snapshot outside source repository
            -> LangChain PromptTemplate
                -> existing RepoPilot InferenceProvider
                    -> PydanticOutputParser[PatchProposal]
                        -> whole-proposal deterministic validation
                            -> transactional exact replacements in workspace only
                                -> RepoPilot canonical unified diff
                                    -> SHA-256 patch hash
                                        -> patch_ready -> END
```

`backend/app/patching/` defines frozen, extra-forbidden `PatchProposal` and
`PatchEdit` schemas. A proposal contains only a summary and exact replacements;
it has no approval or scope field. The patch prompt includes the exact approved
plan, plan hash, frozen scope, issue, and ContextPack evidence. It labels the
issue and repository content as untrusted data, denies comments/docstrings any
authority, prohibits path invention and file creation/deletion/rename, and
requires same-file citations. LangChain is limited to prompt rendering and
Pydantic parsing. The existing async provider receives plain text and no tools.

The patch service revalidates the plan hash, approval-decision hash, workflow
status, exact frozen scope, and M3 plan grounding. `PlanningEvidence` now
retains the bounded chunk's exact source and SHA-256 content hash. Before patch
generation and immediately before application, each approved-scope evidence
slice must still match both the canonical repository and the workspace. Missing
legacy fingerprints or changed code fail as `StaleApprovalError`; an old
approval is never interpreted against new source.

`WorkspaceManager` creates a durable directory beneath a caller-configured
absolute root that must be outside the canonical repository. An opaque
workspace ID binds repository identity, thread ID, and approved plan hash. The
snapshot copies regular-file bytes with relative layout, prunes the same VCS,
environment, dependency, cache, build, and generated directories as discovery,
and never follows or copies symlinks. Workspace metadata is adjacent to a
nested `repository/` snapshot, so metadata cannot enter the generated diff.
The canonical source is read only.

Validation completes for every edit before any write. Each path must be a
normalized repository-relative POSIX path in the frozen approved set and must
resolve to an existing UTF-8, non-NUL, regular, non-symlink workspace file.
Every citation must belong to the exact ContextPack, with at least one cited
chunk from the edited file. `expected_old_text` must occur once in the original
file and its range must be contained by cited same-file evidence. Fuzzy matching
is absent. Ranges are sorted, overlaps are rejected, and validated replacements
apply from the end of a file toward its beginning.

All intended file bytes and the complete diff are computed before mutation.
Original bytes are retained for every changed file; an application or metadata
failure restores them before returning a typed error. RepoPilot generates a
sorted unified diff using only `a/<relative path>` and `b/<relative path>`
headers and hashes the exact canonical UTF-8 diff with SHA-256. State stores
only workspace ID, source plan hash, changed files, diff, patch hash, status,
and bounded error data—never paths, handles, services, or exception objects.

The M4 graph continuation is `approved -> patch -> patch_ready -> END`; patch
failure terminates as `patch_failed`. Rejection never invokes the patcher or
creates a workspace snapshot. A durable completion record returns the existing
artifact if LangGraph replays after application; a changed or half-completed
workspace fails as `PatchConflictError` instead of applying twice.

## Scoped V1 system boundary

```text
React Studio
    -> FastAPI API and event stream
        -> one persisted LangGraph repair workflow (M3+)
            -> tree-sitter Python semantic chunks
            -> SQLite FTS5 + Chroma + RRF
            -> one-hop structure + bounded context pack
            -> fixed local Ollama generation model
            -> plan/file-scope human checkpoint
            -> approved-file-only isolated workspace edits
            -> restricted Docker test sandbox
            -> optional critic-assisted one retry
            -> final human checkpoint and patch export
        -> structured local state, approvals, traces, patches, and tests
```

LangGraph now owns M3 planner/approval state and the M4 approved patch
continuation. Later milestones extend the same bounded graph with
test/critic/final-review transitions and the hard maximum-one-retry control.
Selective LangChain use is limited to planner/patcher prompt templating and
Pydantic output parsing. Neither framework replaces RepoPilot's custom
retrieval or patch-validation boundaries.

Docker execution, critic retry, the second/final approval, patch export, and
frontend review UI are not yet implemented.

## End-to-end flow

1. A user supplies a Python repository and issue.
2. Tree-sitter builds cited AST-aware chunks.
3. BM25 and dense retrieval run independently; RRF fuses their ranks.
4. One-hop import/parent-child/related-test evidence is added and packed under a fixed token budget.
5. The planner creates an evidence-grounded plan, risks, approved-file proposal, and test strategy.
6. Human checkpoint one approves or rejects the plan and file scope.
7. The patcher proposes and applies a dry-run-validated edit only to approved files.
8. The test runner executes allowlisted commands in restricted Docker and captures evidence.
9. On failure, an optional critic may guide one retry; there are at most two repair attempts total.
10. Human checkpoint two reviews the final diff/test evidence and may approve patch export.

## One-workflow stages and failure behavior

These are nodes/stages of one bounded LangGraph workflow, not independent
autonomous agents or a multi-agent swarm.

| Node | Output | Key failure behavior |
|---|---|---|
| Planner | Steps, approved-file proposal, diagnosis, tests | Fail on malformed or ungrounded output; pause at checkpoint one on success |
| Retriever | Ranked cited chunks + mode | Mark dense provider failure as lexical-only degraded |
| Context packer | Token-budgeted context | Exclude whole lower-priority chunks; report an oversized first chunk |
| Patcher | Structured edit or diff | Reject hallucinated/unapproved paths |
| Patch applier | Modified workspace | Dry-run first; do not partially apply invalid patches |
| Test runner | Exit status, logs, duration | Timeout, capture evidence, clean up sandbox |
| Critic | Optional diagnosis and retry hints | Permit at most one retry, then stop |
| Human checkpoints | Two immutable decision records | Persist decisions and resume the same run |

## Trust boundaries

- Repository content and issue text are untrusted inputs, not instructions.
- Model output is a proposal and cannot bypass validators or approvals.
- Git edits stay under the normalized repository root and approved file set.
- Repository commands execute only in the network-disabled sandbox by default.
- The first approval binds the plan and editable file set; the second binds the
  final diff and export decision to exactly what was reviewed.
- RepoPilot exports a patch only. It never autonomously creates or merges a PR.

## Proof obligations

- Retrieval provenance and frozen BM25/dense/RRF evaluation.
- One-hop/context-pack validation is implemented; meaningful comparative and
  fixed-size evaluation remains later work.
- Approval interrupt/resume and approved-scope enforcement.
- Patch dry-run, rollback behavior, and test isolation.
- Reproducible traces and benchmark configuration.
