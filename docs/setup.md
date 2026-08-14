# RepoPilot Setup

## Current status

The M0 backend foundation is implemented. It provides FastAPI health and local
Ollama connectivity endpoints; no frontend, agent, retrieval, ingestion, or
sandbox functionality exists yet.

## Prerequisites

- Git
- `uv`
- Python 3.11+ (a compatible interpreter can be installed with `uv`)
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

These commands were executed successfully on 2026-08-14:

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
