# RepoPilot Setup

## Current status

The M0 browser-to-local-inference product skeleton is implemented. It provides
a React/Vite prompt screen, FastAPI health and inference endpoints, and a local
Ollama provider. No agent, retrieval, ingestion, or sandbox functionality
exists yet.

## Prerequisites

- Git
- `uv`
- Python 3.11+ (a compatible interpreter can be installed with `uv`)
- Node.js and npm
- Ollama running locally with `gemma4:e4b-it-qat` installed

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

Example override for the current PowerShell session:

```powershell
$env:REPOPILOT_OLLAMA_TIMEOUT_SECONDS = "180"
```

## Test

Tests use a mocked Ollama HTTP transport and do not download or invoke a real
model:

```powershell
Set-Location backend
uv run --locked --offline pytest -q
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

The required real browser-to-Ollama smoke test was not completed because no
browser surface was available to the automation session. This is an explicit
verification blocker, not a reported pass.
