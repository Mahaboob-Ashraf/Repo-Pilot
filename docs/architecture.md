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
persistence, one-hop relationships, context packing, and reranking remain
unimplemented. Dense retrieval and rank fusion are described below.

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
remain scoring data. Implemented variants are `ast_bm25`, `ast_dense`, and
`ast_hybrid_rrf`. Later `fixed_bm25` and `hybrid_structure` variants have named
extension points but are not implemented.

Per-case metrics are relevant-file Hit@1, relevant-file Hit@5,
relevant-symbol Hit@5 when symbol gold exists, file reciprocal rank, symbol
reciprocal rank when symbol gold exists, wall-clock retrieval latency, ranked
chunk provenance, and degradation status. Missing symbol gold yields `None`
and is excluded from symbol aggregates. Aggregate p50/p95 latency uses the
deterministic nearest-rank method only with at least five cases. The four
controlled toy cases validate harness behavior only; they are not benchmark or
SWE-bench results.

## Scoped V1 planned system boundary

```text
React Studio
    -> FastAPI API and event stream
        -> one persisted LangGraph repair workflow (M3+)
            -> tree-sitter Python semantic chunks
            -> SQLite FTS5 + Chroma + RRF
            -> one-hop structure + bounded context pack
            -> fixed local Ollama generation model
            -> plan/file-scope human checkpoint
            -> approved-file-only Git workspace edits
            -> restricted Docker test sandbox
            -> optional critic-assisted one retry
            -> final human checkpoint and patch export
        -> structured local state, approvals, traces, patches, and tests
```

LangGraph will own shared state, stage transitions, the conditional test-failure
branch, the hard maximum-one-retry control, pause/resume, and checkpoint
persistence where needed. Selective LangChain use is limited to useful prompt,
message, structured-output, and Runnable composition inside LLM-backed nodes.
Neither framework replaces RepoPilot's custom retrieval stack, and neither is
installed before M3.

Structural expansion, context packing, orchestration, broader persistence,
Git editing, Docker execution, critic retry, and final export are not yet
implemented.

## End-to-end flow

1. A user supplies a Python repository and issue.
2. Tree-sitter builds cited AST-aware chunks.
3. BM25 and dense retrieval run independently; RRF fuses their ranks.
4. One-hop import/parent-child/related-test evidence is added and packed under a fixed token budget.
5. The planner creates an evidence-grounded plan, risks, approved-file proposal, and test strategy.
6. Human checkpoint one approves, edits, or rejects the plan and file scope.
7. The patcher proposes and applies a dry-run-validated edit only to approved files.
8. The test runner executes allowlisted commands in restricted Docker and captures evidence.
9. On failure, an optional critic may guide one retry; there are at most two repair attempts total.
10. Human checkpoint two reviews the final diff/test evidence and may approve patch export.

## One-workflow stages and failure behavior

These are nodes/stages of one bounded LangGraph workflow, not independent
autonomous agents or a multi-agent swarm.

| Node | Output | Key failure behavior |
|---|---|---|
| Planner | Steps, approved-file proposal, risk, tests | Pause at checkpoint one; clarify underspecified issues |
| Retriever | Ranked cited chunks + mode | Mark dense provider failure as lexical-only degraded |
| Context packer | Token-budgeted context | Drop low-ranked context; preserve tests/signatures |
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
- One-hop/context-pack evaluation only after M2C; fixed-size comparison later.
- Approval interrupt/resume and approved-scope enforcement.
- Patch dry-run, rollback behavior, and test isolation.
- Reproducible traces and benchmark configuration.
