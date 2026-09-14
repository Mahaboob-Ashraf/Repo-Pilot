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
RepoPilot-generated unified diffs/hashes. M5 adds patch-bound, restricted
Docker pytest through disposable execution snapshots and bounded structured
results. M6 adds the bounded critic, one clean-baseline retry maximum, the
second hash-bound approval, and exact patch export. M7 adds the typed workflow
API and focused React evidence/plan/diff/test/final-review workspace. The
backend remains authoritative; the UI is not an IDE or workflow engine.

## Prerequisites

- Git
- `uv`
- Python 3.11+ (a compatible interpreter can be installed with `uv`)
- Node.js and npm
- Ollama running locally with `gemma4:e4b-it-qat` installed for generation
- Ollama `embeddinggemma` installed only when running real embedding/hybrid
  functional smokes; automated tests do not require it
- Docker with a running Linux-container daemon and the configured test image
  already present locally only for real M5 execution; automated tests use fakes
- A Gemini API key only when explicitly selecting the optional hosted Gemini
  generation provider

The default path is local and requires no API key or paid service. Ollama mode
uses local generation. Gemini mode sends bounded generation context to Google's
Gemini API.

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
The optional hosted generation adapter uses the direct pins
`google-genai==2.23.0` and `python-dotenv==1.2.3`.

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
| `REPOPILOT_GENERATION_PROVIDER` | `ollama` | Server-side generation provider: `ollama` or `gemini` |
| `REPOPILOT_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama HTTP server |
| `REPOPILOT_OLLAMA_MODEL` | `gemma4:e4b-it-qat` | Exact locally installed model tag |
| `REPOPILOT_OLLAMA_TIMEOUT_SECONDS` | `120` | Per-request HTTP timeout |
| `REPOPILOT_OLLAMA_EMBEDDING_BASE_URL` | `http://127.0.0.1:11434` | Separate embedding HTTP server |
| `REPOPILOT_OLLAMA_EMBEDDING_MODEL` | `embeddinggemma` | Local embedding model identity |
| `REPOPILOT_OLLAMA_EMBEDDING_TIMEOUT_SECONDS` | `60` | Per-embedding-request timeout |
| `REPOPILOT_GEMINI_API_KEY` | no default | Required secret only when provider is `gemini` |
| `REPOPILOT_GEMINI_MODEL` | `gemini-3.1-flash-lite` | Exact hosted generation model; no fallback |
| `REPOPILOT_GEMINI_TIMEOUT_SECONDS` | `120` | Per-request Gemini timeout |
| `REPOPILOT_DATA_DIR` | `%LOCALAPPDATA%\RepoPilot` on Windows | Durable workflow data outside reviewed repositories |

Example override for the current PowerShell session:

```powershell
$env:REPOPILOT_OLLAMA_TIMEOUT_SECONDS = "180"
```

RepoPilot loads the repository-root `.env` only through the settings layer and
never overrides variables already set by the process. Keep the API key only in
the ignored `.env`; `.env.example` contains blank/default-safe placeholders.
The key is never sent to the frontend or written to checkpoints/evaluation
artifacts.

When Gemini is selected, generation requests may contain bounded issue text,
ContextPack repository source, the approved plan, and patch/test evidence used
by later stages. Retrieval and embeddings remain local through Ollama and
EmbeddingGemma. Do not describe Gemini mode as local or private.

## Optional Gemini provider preflight and controlled evaluation

Run from `backend/`. These commands use the ignored root `.env` for the key;
they never print it. Keep the same exact model for preflight, development
calibration, and all six benchmark cases:

```powershell
$env:REPOPILOT_GENERATION_PROVIDER = "gemini"
$env:REPOPILOT_GEMINI_MODEL = "gemini-3.1-flash-lite"
uv run --locked --offline python -m app.evaluation.provider_comparison preflight
uv run --locked --offline python -m app.evaluation.provider_comparison calibration
uv run --locked --offline python -m app.evaluation.m9 real --manifest ../evaluation/fixtures/m9/manifest-v2.json --output-dir ../evaluation/results/m9-gemini-3.1-flash-lite-v1 --docker-executable "C:\Users\Admin\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
uv run --locked --offline python -m app.evaluation.provider_comparison compare --gemini-results ../evaluation/results/m9-gemini-3.1-flash-lite-v1/m9-results.json
```

The preflight verifies exact model access, one tiny plain response, and one tiny
native JSON-schema response. If the configured model is unavailable it reports
safe suitable model names and stops; it never falls back. The calibration uses
only the separate frozen M10 development cases. The M9 command uses each frozen
case exactly once through the production workflow, including normal critic-
guided attempt two only when eligible. Never point this experiment at the
frozen `m9-v2` or `m9-v3` result directories.

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

Focused M5 sandbox/workflow command:

```powershell
uv run --locked --offline pytest -q tests/test_docker_test_runner.py tests/test_test_execution_service.py tests/test_test_workflow.py
```

Focused M6 critic/retry/final/export command:

```powershell
uv run --locked --offline pytest -q tests/test_critic.py tests/test_patcher.py tests/test_patch_export.py tests/test_m6_workflow.py
```

Focused M7 workflow API command:

```powershell
uv run --locked --offline pytest -q tests/test_workflow_api.py tests/test_api.py
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

## M5 Docker test configuration

M5 composes `ApprovedPatchTestService` from the same `WorkspaceManager`, a
`DisposableTestSnapshotManager`, a `DockerTestRunner`, and a durable
`TestResultStore`, then supplies it to `PlanReviewService`. With this service
configured, the approved path continues from `patch_ready` into one test node
and terminates as `tests_passed`, `tests_failed`, or
`test_infrastructure_failed`. M3-only and M4-terminal service construction
remain supported for focused regressions.

The default image reference is `repopilot-python-test:3.11-pytest9`. RepoPilot
does not pull or build it automatically. The runner locally inspects the image,
records its resolved ID, and executes that ID with `--pull never`. General
dependency installation is not implemented; the image must already contain a
Python/pytest environment suitable for the repository.

`DockerTestRunner` accepts an explicit `docker_executable` when the CLI is not
on PATH. The M9 CLI exposes the same narrow setting as `--docker-executable`;
all Docker subprocesses then use that exact argv element without a shell.

The fixed in-container command is:

```text
python -m pytest -q -p no:cacheprovider
```

Targeted mode may append validated selectors such as
`tests/test_pricing.py::test_twenty_percent_discount_reduces_price`. Selectors
are literal argv values, not shell text. Absolute/traversal/nonexistent paths,
control characters, shell-like node text, and non-Python files are rejected.
`RepairPlan.suggested_tests` is never executed as a command.

Default bounds are a 120-second wall timeout, 512 MiB memory, 1 CPU, 128 PIDs,
a 64 MiB `/tmp` tmpfs, and 64 KiB per stdout/stderr stream. Required controls
are network `none`, all capabilities dropped, no-new-privileges, non-root
UID/GID `65532:65532`, read-only container root, and read-only `/workspace`.
Only the disposable patched snapshot is mounted. The canonical repository,
durable M4 workspace, Docker socket, host home, and host credentials are never
mounted.

Safe Docker preflight is read-only:

```powershell
docker version
docker info
docker image ls --no-trunc
```

Do not pull/build an image or change Docker installation/configuration as part
of a repair run. Missing daemon/image state is reported as infrastructure
failure and requires a separate explicitly approved setup action.

The separately approved RepoPilot-controlled image is defined at
`docker/test-runner/Dockerfile`. Its base is pinned to
`python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84`.
It installs only pytest 9.1.1 and its pinned runtime dependencies. Task 019B
used these explicit setup commands; do not run them as part of repair execution:

```powershell
docker pull python:3.11-slim-bookworm
docker build --pull=false --tag repopilot-python-test:3.11-pytest9 --file docker/test-runner/Dockerfile docker/test-runner
```

The resulting local image is never pushed. Runtime remains `--pull never` and
`--network none`.

## M6 critic, final review, and export configuration

Construct `StructuredCritic` with the existing `InferenceProvider`, then wrap
it in `CriticService` with a caller-configured absolute durable
`CriticAssessmentStore` directory. Construct `PatchExporter` with the same
`WorkspaceManager` and an absolute export directory outside the canonical
repository. Pass both to `PlanReviewService` or
`open_sqlite_plan_review_service`; M6 is enabled only when patch, test, critic,
and export services are all present.

After a genuine attempt-one pytest assertion failure, the critic may recommend
one retry. The retry is generated from the unchanged approved plan/hash/scope
and ContextPack plus bounded prior evidence, then applied to a new durable
workspace copied from the approved canonical baseline. Infrastructure and
timeout outcomes never invoke the critic. No path can produce attempt three.

The first passing attempt returns `awaiting_final_approval` and a bounded final
review payload. Resume with `resume_final_review(...)`, the same thread ID, and
`{"decision":"approve"|"reject","patch_hash":"<displayed exact hash>"}`.
Approval re-verifies the workspace and matching successful test result before
writing `<patch_hash>.patch`; rejection writes nothing. The export file is the
exact existing canonical unified diff. RepoPilot never applies it to the
canonical repository and never commits, pushes, merges, or creates a PR.

## M7 workflow API and refresh behavior

The React workspace calls these local FastAPI routes:

- `POST /api/workflows` with `repository_path`, `issue`, and optional stable
  `thread_id`;
- `GET /api/workflows/{thread_id}` to read the checkpoint without running
  planner, patcher, tests, critic, or export;
- `POST /api/workflows/{thread_id}/plan-decision` with `approve|reject` and the
  exact displayed `plan_hash`;
- `POST /api/workflows/{thread_id}/final-decision` with `approve|reject` and
  the exact displayed `patch_hash`.

The browser keeps only the active thread ID in its URL, so reopen/refresh uses
the read-only GET. State-changing requests are never automatically retried.
The create screen supplies that ID before its POST; an ambiguous network
failure retains it for recovery by a later read-only refresh.
Local inference may take minutes; the UI describes the bounded operation
without fake percentages. Repository source, diffs, issues, and logs render as
escaped text only.

`REPOPILOT_DATA_DIR` holds the durable LangGraph checkpoints, a minimal
thread-to-repository locator needed to reconstruct repository-specific
services after restart, and isolated patch/test/critic/export artifacts. These
implementation paths are not returned by the API; export responses expose only
the safe content-addressed `.patch` filename and identifier.

## M8 frozen local evaluation

Run from `backend/`. The runner never downloads a model or container image and
does not require the frontend:

```powershell
uv run --locked --offline python -m app.evaluation.m8 --mode retrieval
uv run --locked --offline python -m app.evaluation.m8 --mode safety
uv run --locked --offline python -m app.evaluation.m8 --mode full
```

All modes write `evaluation/results/m8/m8-results.json` and
`evaluation/results/m8/m8-report.md`. Retrieval uses the frozen synthetic M8
repositories and production SQLite/Chroma/RRF/structure/ContextPack code. The
locked real dense path requests the already-local `embeddinggemma:latest`; if it
is unavailable, dense-dependent variants are recorded as blocked and no fake
embedding is substituted. A blocked real dense variant does not make the
deterministic safety suite fail. Invalid fixtures/configuration or any failed
safety invariant returns a non-zero exit code.

## M9 frozen external/system evaluation

M9 uses an ignored `evaluation/cache/` boundary for pinned external material
and writes canonical artifacts under `evaluation/results/m9/`. Manifest
validation, fixture checks, fake harness tests, report generation, and ordinary
real evaluation do not acquire network data:

```powershell
Set-Location backend
uv run --locked --offline python -m app.evaluation.m9 validate
uv run --locked --offline python -m app.evaluation.m9 check-fixtures
uv run --locked --offline python -m app.evaluation.m9 diagnose-ingestion
uv run --locked --offline python -m app.evaluation.m9 diagnose-planner --case-id boltons-ceil-exact-option --diagnostic-label initial
uv run --locked --offline python -m app.evaluation.m9 verify-fixture-tests
uv run --locked --offline python -m app.evaluation.m9 dry-run
uv run --locked --offline python -m app.evaluation.m9 real
uv run --locked --offline python -m app.evaluation.m9 report
uv run --locked --offline pytest -q tests/test_m9_evaluation.py
```

The corrected M9 v2 fixture can be materialized from already-cached pinned
commits and verified alone without running the rest of M9:

```powershell
uv run --locked --offline python -m app.evaluation.m9 materialize --manifest ../evaluation/fixtures/m9/manifest-v2.json
uv run --locked --offline python -m app.evaluation.m9 verify-fixture-tests --manifest ../evaluation/fixtures/m9/manifest-v2.json --case-id boltons-floor-exact-option --output-dir ../evaluation/results/m9-v2
```

The second command executes external test code only through the existing M5
Docker sandbox. It writes a separate v2 proof and does not overwrite the v1
fixture-test history.

External Git acquisition is a separate explicit operation:

```powershell
uv run --locked --offline python -m app.evaluation.m9 materialize --allow-network
```

That command may clone/fetch only the manifest's HTTPS GitHub repositories at
their full pinned SHAs. It selects the recorded minimal fixture paths, applies
one exact controlled defect per case, and verifies repository/case SHA-256
fingerprints. It never installs dependencies, invokes repository setup scripts,
downloads models/tools, or pulls/builds container images. Remove a mismatched
generated case cache explicitly before rematerializing; the runner never
silently overwrites it.

`real` checks every fixture fingerprint and then performs Docker/Ollama
preflight. Full repair requires both locked models plus an already-running
Docker daemon and already-local `repopilot-python-test:3.11-pytest9`. Missing
daemon/image/model state produces infrastructure-blocked cases before workflow
execution. No alternative provider, host pytest, image pull/build, or model
download is permitted. A CPU-only generation run may use the existing
process-scoped override without changing defaults:

```powershell
$env:REPOPILOT_OLLAMA_TIMEOUT_SECONDS = "600"
$env:REPOPILOT_OLLAMA_EMBEDDING_MODEL = "embeddinggemma:latest"
uv run --locked --offline python -m app.evaluation.m9 real
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

## Task 015 verification

Verified on 2026-09-12 without requiring Docker or Ollama for automated tests:

| Action | Command | Observed result |
|---|---|---|
| M5 command/sandbox/workflow tests | Documented three-file M5 command | 42 passed |
| M4 patch/workspace regressions | Documented three-file M4 command | 32 passed |
| M3 planner/approval regressions | Documented two-file M3 command | 26 passed |
| M1/M2 retrieval/context regressions | Documented parser through ContextPack test files | 132 passed |
| Complete backend suite | `uv run --locked --offline pytest -q` | 240 passed |
| Docker client preflight | `docker version` | Client 29.7.2, API 1.55, `desktop-linux` context |
| Docker daemon/image preflight | `docker info` and local image inventory | Daemon unavailable at `dockerDesktopLinuxEngine`; image inventory unavailable |

No installation, update, daemon start, image pull, build, or machine
configuration change was attempted. Therefore the optional real smoke is
reported as `real Docker smoke blocked — local test image unavailable`; the
daemon also prevented proving whether any suitable image was locally present.

## Task 016 verification

Verified on 2026-09-12 without requiring Docker or Ollama:

| Action | Command | Observed result |
|---|---|---|
| Pre-change complete backend suite | `uv run --locked --offline pytest -q` | 240 passed |
| M6 critic/patcher/export/workflow tests | Documented four-file M6 command | 32 passed |
| Complete backend suite | `uv run --locked --offline pytest -q` | 266 passed in 4.99 seconds |

The optional CPU-only critic smoke was skipped because it was nonessential and
previous `gemma4:e4b-it-qat` CPU generations took minutes. A complete real M6
smoke remains blocked at the already-recorded unavailable Docker daemon/image
boundary. No image pull/build, machine change, source mutation, commit, push,
merge, or PR action occurred.

## Task 017 verification

Verified on 2026-09-13 without requiring Docker or Ollama:

| Action | Command | Observed result |
|---|---|---|
| Pre-change backend baseline | `uv run --locked --offline pytest -q` | 266 passed in 5.81 seconds |
| Pre-change frontend tests | `npm test` | 4 passed |
| Focused workflow API + legacy API | Documented M7 focused command | 17 passed |
| Broader API/M3/M6 focused set | Workflow API, API, plan review, and M6 files | 42 passed |
| Complete backend suite | `uv run --locked --offline pytest -q` | 275 passed in 5.18 seconds |
| Frontend tests | `npm test` | 18 passed |
| Frontend typecheck/build | `npm run build` | TypeScript passed; Vite 7.3.6 built 32 modules |

The optional functional UI smoke did not run because `ollama` and `docker`
were not available on the current command PATH. No installation, daemon start,
image pull/build, model download, or machine configuration change was
attempted. No benchmark claim is made.

## Task 018 verification

Verified on 2026-09-13 without Docker, generation, network downloads, or fake
benchmark embeddings:

| Action | Command | Observed result |
|---|---|---|
| Focused M8 tests | `uv run --locked --offline pytest -q tests/test_m8_evaluation.py` | 12 passed |
| Complete backend suite before real run | `uv run --locked --offline pytest -q` | 285 passed in 5.18 seconds |
| Final complete backend suite | `uv run --locked --offline pytest -q` | 287 passed in 6.26 seconds |
| Full frozen M8 run | `uv run --locked --offline python -m app.evaluation.m8 --mode full` | Exit 0; artifacts written under `evaluation/results/m8/` |
| Frontend regression tests | `npm test` | 18 passed |
| Frontend typecheck/build | `npm run build` | TypeScript passed; Vite 7.3.6 built 32 modules |

This initial Task 018 run measured BM25 on 10 frozen synthetic cases. The locked real
`embeddinggemma:latest` path returned `EmbeddingUnavailableError`, so real
dense/RRF results were blocked in that run. The production lexical-only degraded
fallback was measured separately through one-hop structure and the ContextPack.
No model/image was downloaded, no Docker command ran, and no
retrieval/prompt/budget/retry tuning was performed.

## Task 018B real retrieval verification

Verified on 2026-09-13 after the exact already-local
`embeddinggemma:latest` became reachable:

| Action | Command | Observed result |
|---|---|---|
| Full real M8 retrieval + safety artifact | `uv run --locked --offline python -m app.evaluation.m8 --mode full` | Exit 0; BM25, dense, hybrid, one-hop, and ContextPack measured; 33/33 safety scenarios retained |
| Focused M8 tests | `uv run --locked --offline pytest -q tests/test_m8_evaluation.py` | 12 passed in 2.15 seconds |
| Complete backend suite | `uv run --locked --offline pytest -q` | 287 passed in 6.66 seconds |

The run recorded model digest
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.
It invoked neither Docker nor a generation model, performed no download, and
did not change retrieval parameters, prompts, budget, fixture labels, or policy.

## Task 019 verification

Verified on 2026-09-13 without running external repository code on the host:

| Action | Command | Observed result |
|---|---|---|
| M9 harness tests | `uv run --locked --offline pytest -q tests/test_m9_evaluation.py` | 25 passed in 1.22 seconds |
| Complete backend suite | `uv run --locked --offline pytest -q` | 312 passed in 7.47 seconds |
| Manifest validation | `uv run --locked --offline python -m app.evaluation.m9 validate` | Valid; fingerprint `ed61951d87f38c50f86028346d6f68359c99049f804ced8d1a7417c31ba2c76c` |
| Fixture verification | `uv run --locked --offline python -m app.evaluation.m9 check-fixtures` | 3 source selections and 6 case fixtures matched |
| Real M9 run | `uv run --locked --offline python -m app.evaluation.m9 real` | 6 infrastructure-blocked; Docker daemon unreachable |

Ollama HTTP exposed both exact locked model digests. Docker image inventory was
unavailable because the daemon could not be reached. No image/model/tool pull,
dependency installation, host pytest against external code, generation call,
patch, export, commit, push, or public post occurred.

## Task 019B verification

Verified on 2026-09-13 after the user explicitly approved the one local image
build. External repository tests ran only in restricted Docker containers.

| Action | Command | Observed result |
|---|---|---|
| Image build | `docker build --pull=false --tag repopilot-python-test:3.11-pytest9 --file docker/test-runner/Dockerfile docker/test-runner` | Image `sha256:72b98eae96d168dcdd898cdad6b3c198de5e2b8a0092ee1b80ea8ad1e3d972c7`; 55,741,891 bytes |
| Image versions | Restricted `python --version` and `python -m pytest --version` | Python 3.11.16; pytest 9.1.1 |
| M5 policy smoke | Fixed `docker run` with the production security flags | 1 passed; non-root/read-only/network/capability/tmpfs/resource assertions verified |
| Ingestion diagnosis | `uv run --locked --offline python -m app.evaluation.m9 diagnose-ingestion` | 6/6 cases succeeded after the byte-offset line-range fix |
| Pre-repair fixture tests | `uv run --locked --offline python -m app.evaluation.m9 verify-fixture-tests` | 5 expected failures; 1 invalid passing selector |
| Frozen real M9 | `uv run --locked --offline python -m app.evaluation.m9 real` | 5 attempts; 0 repairs; 5 planner failures; 1 fixture-invalid; 0 infrastructure failures |
| M1 regressions | Focused parser/discovery/chunk/pipeline files | 36 passed in 0.43 seconds |
| M8 regressions | `uv run --locked --offline pytest -q tests/test_m8_evaluation.py` | 12 passed in 2.44 seconds |
| M9 regressions | `uv run --locked --offline pytest -q tests/test_m9_evaluation.py` | 27 passed in 1.17 seconds |
| M3-M6 regressions | Focused planning, patching, Docker, critic, and export files | 126 passed in 3.87 seconds |
| Complete backend suite | `uv run --locked --offline pytest -q` | 315 passed in 6.99 seconds |

The real run was executed once. No LLM case was regenerated, no repair was
manually edited, and no retrieval/model/prompt/budget/approval/retry parameter
was tuned.

## Task 019C verification

Task 019C preserved the historical v1 result and ran only the permitted
representative initial/confirmation planner diagnostics. The current Ollama
API was reachable at preflight on version 0.34.0 and exposed the locked
`gemma4:e4b-it-qat` digest. `/api/ps` was empty, so current processor placement
was unavailable; the active server was configured for Vulkan0, and its new
active log had no device-loss line. The rotated log retains the earlier device
loss evidence.

The initial `boltons-ceil-exact-option` diagnostic failed once as HTTP 500 with
Vulkan device loss. The one justified confirmation parsed a plan, then failed
grounding on unknown chunk `N/A`. No patch/retry executed. Retained logs also
show all five original v1 generation calls failed the same Vulkan/HTTP-500 way,
so those attempts are infrastructure-invalid and a clean full rerun is
scientifically justified but was not performed.

M9 v2 has manifest fingerprint
`e08a819fbdc6dd3b8bd164a1b27fee63f495f55d0d350117a2b60556fe2e973b`.
The one-case Docker proof for `boltons-floor-exact-option` failed before repair
with exit code 1 / `pytest_assertion_failure`, using image
`sha256:72b98eae96d168dcdd898cdad6b3c198de5e2b8a0092ee1b80ea8ad1e3d972c7`.
Focused planner/Python-parser regressions passed 18/18, M9 passed 30/30, M8
passed 12/12, and the complete backend suite passed 318/318 in 8.26 seconds.
The first sandboxed test attempt could not access the user temp root; repository-
local base-temp then correctly failed three checkpoint tests because durable
checkpoints must live outside source. The final unchanged suite used approved
external temp access and passed. No frontend run was required.

## Task 019D final M9 v2 verification

The final benchmark command used
`REPOPILOT_OLLAMA_TIMEOUT_SECONDS=600` and
`REPOPILOT_OLLAMA_EMBEDDING_MODEL=embeddinggemma:latest` with the existing
documented `real --manifest ../evaluation/fixtures/m9/manifest-v2.json
--output-dir ../evaluation/results/m9-v2` entry point. It ran once. Ollama's CLI
was not on this shell's PATH, so HTTP `/api/ps` was used as the equivalent; it
reported Gemma and EmbeddingGemma with `size_vram=0` during execution.

| Action | Observed result |
|---|---|
| Docker preflight | Server 29.7.2; locked image ID `sha256:72b98eae96d168dcdd898cdad6b3c198de5e2b8a0092ee1b80ea8ad1e3d972c7` |
| Ollama preflight | API 0.34.0; both locked model digests present; 100% CPU placement |
| M9 v2 fixture proof | 6/6 selectors failed before repair; 6/6 canonical fixtures unchanged |
| Final M9 v2 | 6 attempted, 0 repaired, 0 provider/infrastructure failures, 0 critical safety failures |
| M9 regressions | 31 passed in 1.35 seconds |
| M8 regressions | 12 passed in 2.37 seconds |
| Parser/chunking regressions | 35 passed, 1 skipped in 0.16 seconds |
| M3-M6 safety/workflow regressions | 126 passed in 4.59 seconds |
| Complete backend suite | 319 passed in 8.18 seconds |

No frontend run was needed because no shared API or UI contract changed.

## Task 020 M10 calibration and final artifacts

Run development-only experiments from `backend/`; they write only under the
new M10 result directory:

```powershell
uv run --locked --offline python -m app.evaluation.m10 context
uv run --locked --offline python -m app.evaluation.m10 embedding
uv run --locked --offline python -m app.evaluation.m10 embedding_index
$env:REPOPILOT_OLLAMA_TIMEOUT_SECONDS = "600"
uv run --locked --offline python -m app.evaluation.m10 planner --phase plain
uv run --locked --offline python -m app.evaluation.m10 planner --phase native_schema
uv run --locked --offline python -m app.evaluation.m10 patcher --phase native_schema
uv run --locked --offline python -m app.evaluation.m10_report
```

The completed post-optimization runs used fresh output directories:

```powershell
uv run --locked --offline python -m app.evaluation.m8 --mode full --output-dir ../evaluation/results/m8-v2
uv run --locked --offline python -m app.evaluation.m9 real --manifest ../evaluation/fixtures/m9/manifest-v2.json --output-dir ../evaluation/results/m9-v3
```

M9-v3 is a completed one-shot measurement and must not be casually rerun or
overwritten. It used Docker 29.7.2, image
`sha256:72b98eae96d168dcdd898cdad6b3c198de5e2b8a0092ee1b80ea8ad1e3d972c7`,
the locked model digests, a 600-second generation timeout, and Gemma with
`size_vram=0`. Use a new result version for any later experiment.

## Task 021B Gemini 3.1 Flash-Lite measurement

The exact Docker Desktop executable was used because `docker` was absent from
PATH. Docker client/server 29.7.2 was reachable and the local
`repopilot-python-test:3.11-pytest9` image matched
`sha256:72b98eae96d168dcdd898cdad6b3c198de5e2b8a0092ee1b80ea8ad1e3d972c7`.
Ollama 0.34.0 exposed `embeddinggemma:latest` at digest
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`;
`/api/ps` reported zero VRAM bytes.

The exact `gemini-3.1-flash-lite` preflight passed model access, plain output,
small native-schema output, and `RepairPlan` schema output. The unchanged M10
development calibration then passed all three planner parse/citation/grounding
checks and its one patcher parse/exact-replacement check. The suite has no
separate critic fixture; critic schema and grounding behavior remains covered
by focused automated tests.

The untouched `m9-external-controlled-v2` experiment ran each of six cases
once. It repaired 6/6 on attempt one, with 6 grounded plans, 6 valid patches,
6 restricted-Docker passes, zero critic calls, zero retry recoveries, zero
provider/API failures, and no critical safety failure. Retrieval stayed at
Hit@1/Hit@5/MRR 0.8333/1.0000/0.9167 with full gold file and symbol ContextPack
coverage. Four larger cases followed the existing explicit lexical fallback
after local embedding response failures; both boltons cases used hybrid
retrieval.

These are six controlled defects across three public repositories, not
SWE-bench, production accuracy, or a general model ranking. Gemini generation
is hosted and network-dependent: bounded issue text, source context, approved
plan/patch evidence, and test output can leave the machine. The default
Ollama/Gemma path and EmbeddingGemma retrieval remain local and zero-cost apart
from user hardware and electricity.

Final verification on the completed worktree passed 17 Gemini/provider tests,
14 planner tests, 36 patcher/workspace/workflow tests, 34
critic/retry/export tests, 12 M8 harness tests (including all 33 deterministic
safety scenarios), 32 M9 harness tests, and all 350 backend tests. Frontend
Vitest passed 18/18; the `tsc --noEmit` check and Vite 7.3.6 production build
also passed.
