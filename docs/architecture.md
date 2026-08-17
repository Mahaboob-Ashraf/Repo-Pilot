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

Git/URL/archive ingestion, module-header/configuration chunks, persistent
indexing, dependency edges, retrieval, embeddings, and ranking remain
unimplemented.

## Planned later system boundary

```text
React Studio
    -> FastAPI API and event stream
        -> persisted LangGraph run
            -> tree-sitter parser and indexer (parser foundation implemented)
            -> SQLite FTS5 + Chroma + dependency graph
            -> Ollama (default) / vLLM adapter (optional)
            -> approved Git workspace edits
            -> Docker test sandbox
        -> SQLite state, approvals, events, patches, tests, benchmarks
```

These later agent, retrieval, persistence, Git-editing, and sandbox components
are not implemented.

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
