# RepoPilot Setup

## Current status

The Scoped V1 foundation includes a React/Vite prompt screen, FastAPI health
and inference endpoints, deterministic Python discovery/tree-sitter chunks,
SQLite FTS5/BM25 retrieval, local-embedding Chroma retrieval, RRF hybrid
fusion, one-hop structural expansion, hard-budget ContextPacks, and frozen-case
retrieval/context evaluation. LangGraph orchestration, patching, Docker
execution, critic retry, and review workflow are not yet implemented.

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
