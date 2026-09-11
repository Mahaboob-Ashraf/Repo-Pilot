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

Language detection is a centralized extension mapping for Python, JavaScript,
and TypeScript. Only Python is currently parser-supported. Unsupported or
non-source extensions are not inferred from content.

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
persistence, dependency edges, vector retrieval, fusion, and reranking remain
unimplemented.

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
No BM25/vector fusion or RRF exists yet.

## Planned later system boundary

```text
React Studio
    -> FastAPI API and event stream
        -> persisted LangGraph run
            -> tree-sitter semantic chunks (implemented)
            -> SQLite FTS5 + Chroma (implemented separately) + dependency graph
            -> Ollama (default) / vLLM adapter (optional)
            -> approved Git workspace edits
            -> Docker test sandbox
        -> SQLite state, approvals, events, patches, tests, benchmarks
```

These later agent, hybrid fusion, dependency expansion, broader persistence,
Git-editing, and sandbox components are not implemented.

## End-to-end flow

1. A user supplies a repository and issue.
2. The backend creates a project/run and an isolated workspace.
3. Ingestion detects languages and extracts AST-level chunks and dependency edges.
4. Chunks enter the SQLite lexical index and Chroma vector collection.
5. The planner proposes steps, risks, target areas, and a test strategy.
6. The user approves, edits, or rejects the plan.
7. Retrieval runs BM25 and vector search, fuses ranks, expands dependencies, and packs cited context.
8. The user may pin/unpin context and approve the proposed edit scope.
9. The patcher produces a structured edit/unified diff limited to existing approved paths.
10. The patch applier dry-runs and applies the approved diff to the Git workspace.
11. The test runner executes approved commands in Docker and captures results.
12. On failure, the critic diagnoses the result and the loop may continue within hard limits.
13. The user reviews the final diff and evidence before patch export.

## Agent nodes and failure behavior

| Node | Output | Key failure behavior |
|---|---|---|
| Planner | Steps, target areas, risk, tests | Ask for clarification on underspecified issues |
| Retriever | Ranked cited chunks | Widen query/fall back to lexical/graph neighbors |
| Context packer | Token-budgeted context | Drop low-ranked context; preserve tests/signatures |
| Patcher | Structured edit or diff | Reject hallucinated/unapproved paths |
| Patch applier | Modified workspace | Dry-run first; do not partially apply invalid patches |
| Test runner | Exit status, logs, duration | Timeout, capture evidence, clean up sandbox |
| Critic | Diagnosis and next-edit hints | Stop on repetition or safety limit |
| Human review | Immutable decision record | Persist decision and resume the same run |

## Trust boundaries

- Repository content and issue text are untrusted inputs, not instructions.
- Model output is a proposal and cannot bypass validators or approvals.
- Git edits stay under the normalized repository root and approved file set.
- Repository commands execute only in the network-disabled sandbox by default.
- Approval records bind the reviewer decision to a hash of exactly what was reviewed.

## Proof obligations

- Retrieval provenance and fixed-size-vs-AST ablation.
- Approval interrupt/resume and approved-scope enforcement.
- Patch dry-run, rollback behavior, and test isolation.
- Reproducible traces and benchmark configuration.
