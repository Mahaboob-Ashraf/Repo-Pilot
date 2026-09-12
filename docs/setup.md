# RepoPilot Setup

## Current status

The Scoped V1 foundation includes a React/Vite prompt screen, FastAPI health
and inference endpoints, deterministic Python discovery/tree-sitter chunks,
SQLite FTS5/BM25 retrieval, local-embedding Chroma retrieval, RRF hybrid
fusion, one-hop structural expansion, hard-budget ContextPacks, and frozen-case
retrieval/context evaluation. M3 adds a LangChain-structured evidence-grounded
planner and the first LangGraph human approval interrupt with in-memory test or
durable local SQLite checkpointing. M4 adds strict approved-scope patch
proposals, durable isolated workspaces, transactional exact replacements, and
RepoPilot-generated unified diffs/hashes. Docker execution, critic retry, the
second approval, and the frontend review workflow are not yet implemented.

## Prerequisites

- Git
- `uv`
- Python 3.11+ (a compatible interpreter can be installed with `uv`)
- Node.js and npm
- Ollama running locally with `gemma4:e4b-it-qat` installed for generation
- Ollama `embeddinggemma` installed only when running real embedding/hybrid
  functional smokes; automated tests do not require it

The default path is local and requires no API key or paid service.

## Backend install

From the repository root:

```powershell
uv python install 3.12
Set-Location backend
uv sync --locked
```

`uv sync --locked` creates `backend/.venv` from the committed `uv.lock`.
The M3+ direct pins are `langchain==1.4.0`, `langgraph==1.2.11`, and
`langgraph-checkpoint-sqlite==3.1.1`. LangSmith is not a direct RepoPilot
runtime requirement; it may appear only as a transitive LangChain dependency.

## Run the backend

From `backend/`:

```powershell
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then check the backend:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Ollama must already be listening at the configured base URL for
`POST /api/inference` to succeed. The backend calls Ollama's HTTP API; it does
not invoke `ollama run` as a subprocess.

## Configuration

| Environment variable | Verified default | Purpose |
|---|---|---|
| `REPOPILOT_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama HTTP server |
| `REPOPILOT_OLLAMA_MODEL` | `gemma4:e4b-it-qat` | Exact locally installed model tag |
| `REPOPILOT_OLLAMA_TIMEOUT_SECONDS` | `120` | Per-request HTTP timeout |
| `REPOPILOT_OLLAMA_EMBEDDING_BASE_URL` | `http://127.0.0.1:11434` | Separate embedding HTTP server |
| `REPOPILOT_OLLAMA_EMBEDDING_MODEL` | `embeddinggemma` | Local embedding model identity |
| `REPOPILOT_OLLAMA_EMBEDDING_TIMEOUT_SECONDS` | `60` | Per-embedding-request timeout |

Example override for the current PowerShell session:

```powershell
$env:REPOPILOT_OLLAMA_TIMEOUT_SECONDS = "180"
```

## Test

Automated tests use mocked Ollama HTTP and deterministic fake embeddings. They
do not download or invoke a real model:

```powershell
Set-Location backend
uv run --locked --offline pytest -q
```

Focused M2 retrieval/evaluation commands:

```powershell
uv run --locked --offline pytest -q tests/test_lexical_retrieval.py tests/test_vector_retrieval.py tests/test_hybrid_retrieval.py
uv run --locked --offline pytest -q tests/test_retrieval_evaluation.py
uv run --locked --offline pytest -q tests/test_structural_context.py tests/test_context_packing.py tests/test_context_evaluation.py
```

Focused M3 planner/workflow commands:

```powershell
uv run --locked --offline pytest -q tests/test_planner.py
uv run --locked --offline pytest -q tests/test_plan_review_workflow.py
```

Focused M4 patching/workflow commands:

```powershell
uv run --locked --offline pytest -q tests/test_patcher.py tests/test_patch_workspace.py tests/test_patch_workflow.py
```

## M3 checkpoint persistence

`PlanReviewService.start_plan_review(...)` accepts a prepared `ContextPack`
and a caller-supplied stable `thread_id`. It returns either a pending approval
payload or a terminal typed planner failure. Resume the same pause with
`resume_plan_review(...)`, the same thread ID, and an explicit decision object
containing `decision`, the displayed `plan_hash`, and an optional `comment`.
Without an M4 patch service, the compatibility path returns terminal
`approved_for_patch` or `rejected`. With `ApprovedPatchService` configured,
approval continues through patch generation/application and returns
`patch_ready` or `patch_failed`; rejection still terminates without calling the
patcher.

Tests inject `InMemorySaver`. The local durable product boundary is
`open_sqlite_plan_review_service(...)`. Supply an absolute SQLite path outside
the RepoPilot source checkout, such as a path under the user's local application
data directory. In-repository and relative checkpoint paths are rejected, so
no runtime checkpoint database is tracked as source. Reopen the service with
the same database and thread ID after restart to resume the saved interrupt.

## M4 isolated workspace configuration

Construct `WorkspaceManager` with the canonical repository and a caller-owned
absolute workspace root outside that repository. The manager creates an opaque
workspace ID and a durable nested `repository/` snapshot for later M5 use.
Callers and graph state use only the workspace ID; absolute paths, service
objects, and file handles are not checkpointed or included in the review diff.

The snapshot excludes `.git`, environment, dependency, cache, build, and
generated directories covered by RepoPilot discovery policy. It copies regular
file bytes and does not follow symlinks. M4 supports exact replacements in
existing UTF-8 text files only. It does not create, delete, rename, test,
commit, or export files.

`ApprovedPatchService` is configured with `StructuredPatcher` and the workspace
manager, then passed to `PlanReviewService` (or the SQLite service factory).
The patcher continues to use the existing `InferenceProvider`; automated tests
inject deterministic providers and never require Ollama.

## Verified Windows commands

These commands were executed successfully on 2026-08-15:

| Action | Command | Observed result |
|---|---|---|
| Install `uv` | `winget install --id astral-sh.uv -e --source winget --accept-package-agreements --accept-source-agreements --silent` | Installed `uv 0.12.4` |
| Install Python | `uv python install 3.12` | Installed CPython 3.12.13 managed by `uv` |
| Lock | `uv lock --python 3.12` | Resolved 29 packages and created `backend/uv.lock` |
| Install backend | `uv sync --locked` | Installed 27 packages into `backend/.venv` |
| Test | `uv run --locked --offline pytest -q` | 5 passed; one upstream `TestClient` deprecation warning |
| Development server | `uv run --locked --offline uvicorn app.main:app --host 127.0.0.1 --port 8765` | Uvicorn started; `/health` and real inference succeeded |

The smoke-test port `8765` was temporary; the documented development port is
`8000`. On Windows, a new shell may be needed after installing `uv` so its
updated `PATH` is visible.

## Frontend install

From the repository root:

```powershell
Set-Location frontend
npm ci
```

The committed `package-lock.json` is the reproducible dependency source.

## Run the frontend

Start the backend first, then run this from `frontend/` in a second terminal:

```powershell
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/`. The browser sends requests only to FastAPI; it
does not connect to Ollama directly.

The frontend API base URL defaults to `http://127.0.0.1:8000`. Override it for
the current PowerShell process before starting Vite when needed:

```powershell
$env:VITE_API_BASE_URL = "http://localhost:8000"
```

## Frontend test and build

From `frontend/`:

```powershell
npm test
npm run build
```

Frontend tests mock the API client and do not require FastAPI or Ollama.

## Task 003 verification

Verified on 2026-08-15 with Node.js 22.17.1 and npm 10.9.2:

| Action | Command | Observed result |
|---|---|---|
| Install frontend | `npm ci` | Installed 161 packages from the lockfile; audit reported 0 vulnerabilities |
| Frontend test | `npm test` | 4 tests passed |
| Frontend build | `npm run build` | TypeScript check and Vite 7.3.6 production build succeeded |
| Backend test | `uv run --locked --offline pytest -q` | 8 tests passed; one upstream `TestClient` deprecation warning |

After Task 003, the browser-to-FastAPI-to-Ollama path was manually verified
successfully by the user. Task 004 did not repeat that real Gemma request.

## Toy repository fixture

`fixtures/toy-repo/` is a deterministic Python target for future parsing,
retrieval, patching, and regression work. It deliberately contains one pricing
bug and must not be treated as a passing application test suite.

Run the fixture from its directory in an ephemeral environment containing only
pytest:

```powershell
Set-Location fixtures/toy-repo
uv run --no-project --isolated --with pytest==9.1.1 --offline pytest -q
```

The verified baseline on 2026-08-17 is:

```text
1 failed, 1 passed
exit code 1
```

The failing test proves the intentional bug: a 20% discount on `100.0` returns
`120.0` instead of `80.0`. The passing zero-percent test proves the fixture is
not completely broken. This expected fixture failure is not a RepoPilot
backend, frontend, or build failure.

## Task 011 verification

Verified on 2026-09-11 without downloading or invoking a model for automated
tests:

| Action | Command | Observed result |
|---|---|---|
| RRF/evaluation tests | `uv run --locked --offline pytest -q tests/test_hybrid_retrieval.py tests/test_retrieval_evaluation.py` | 33 passed after the dense-boundary fix |
| Lexical/vector regressions | `uv run --locked --offline pytest -q tests/test_lexical_retrieval.py tests/test_vector_retrieval.py` | 26 passed after the dense-boundary fix |
| Lexical/vector/M1 regressions | `uv run --locked --offline pytest -q tests/test_lexical_retrieval.py tests/test_vector_retrieval.py tests/test_python_parser.py tests/test_repository_discovery.py tests/test_code_chunks.py tests/test_repository_chunking_pipeline.py` | 59 passed |
| Complete backend suite | `uv run --locked --offline pytest -q` | 115 passed after the dense-boundary fix; one known upstream `TestClient` deprecation warning |

A separate real local `embeddinggemma` BM25/dense/RRF run was labeled a
functional smoke, not a benchmark result.

## Task 012 verification

Verified on 2026-09-11 without invoking Ollama for automated tests:

| Action | Command | Observed result |
|---|---|---|
| Structural/context tests | `uv run --locked --offline pytest -q tests/test_structural_context.py tests/test_context_packing.py tests/test_context_evaluation.py` | 25 passed |
| Structural/context + retrieval/M1 regressions | Focused Task 012, hybrid/evaluation, lexical/vector, parser/discovery/chunk/pipeline files | 118 passed, 1 skipped; existing Windows symlink-permission skip |
| Complete backend suite | `uv run --locked --offline pytest -q` | 139 passed, 1 skipped; existing Windows symlink-permission skip and known warnings |

A separate real local smoke used Ollama 0.32.15, `embeddinggemma` (768
dimensions), real Chroma cosine retrieval, BM25, RRF, one-hop related-test
expansion, and a bounded ContextPack against the three-chunk toy repository.
It was a functional smoke, not a benchmark result.

## Task 013 verification

Verified on 2026-09-12 without invoking Ollama for automated tests:

| Action | Command | Observed result |
|---|---|---|
| Planner tests | `uv run --locked --offline pytest -q tests/test_planner.py` | 13 passed |
| Plan-review workflow/persistence tests | `uv run --locked --offline pytest -q tests/test_plan_review_workflow.py` | 13 passed |
| Structural/ContextPack regressions | Documented three-file M2C command | 25 passed |
| Hybrid retrieval/evaluation regressions | Documented two-file M2B command | 33 passed |
| Lexical/vector/M1 regressions | Documented six-file regression command | 61 passed |
| Complete backend suite | `uv run --locked --offline pytest -q` | 166 passed after the bounded diagnostic change |

The SQLite durability test closed the first service/checkpointer and resumed the
same paused thread through a separately constructed service over the same
isolated temporary database.

A later Task 013 final live smoke found both required Ollama models and ran the
real hybrid retrieval/ContextPack path successfully. Its single
`gemma4:e4b-it-qat` generation request took 51.015 seconds but surfaced the
typed `PlannerInferenceError` before structured output was available, so no
grounding, plan hash, or approval interrupt was reached. It was not retried;
the toy repository remained unchanged. This is functional smoke evidence, not
a benchmark result.

After adding bounded provider diagnostics, one requested rerun used the same
models, prompt, retrieval settings, and ContextPack. Its only generation call
took 52.784 seconds and failed as `InferenceResponseError` / `response_error` /
`Ollama returned HTTP 500`. The newly appended Ollama log output showed
`ggml_vulkan: device lost on Vulkan0` on the GeForce GT 730 immediately before
the 500 response. No plan, grounding, hash, approval interrupt, retry, or file
mutation occurred.

## Task 014 verification

Verified on 2026-09-12 without invoking Ollama for automated tests:

| Action | Command | Observed result |
|---|---|---|
| M4 patcher/workspace/workflow tests | `uv run --locked --offline pytest -q tests/test_patcher.py tests/test_patch_workspace.py tests/test_patch_workflow.py` | 32 passed |
| Combined M3/M4 focused tests | M4 command plus both documented M3 files | 58 passed |
| Parser/repository pipeline after LF policy | Both documented M1 parser/pipeline files | 12 passed |
| Complete backend suite | `uv run --locked --offline pytest -q` | 198 passed |

One optional CPU-only smoke used the process-scoped
`REPOPILOT_OLLAMA_TIMEOUT_SECONDS=600` override without changing the source
default. `ollama ps` reported `100% CPU`. Exactly one planner request and one
patcher request ran, taking 183.976 and 161.725 seconds respectively. The exact
plan produced in that run was approved through the normal resume path, and the
workflow reached `patch_ready` with a RepoPilot-generated relative diff in an
isolated workspace. The canonical toy repository remained byte-identical. This
is functional smoke evidence, not a latency benchmark.
