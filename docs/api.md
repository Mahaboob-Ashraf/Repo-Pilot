# RepoPilot API

## Implemented M0 endpoints

### `GET /health`

Reports backend process health. It does not perform an Ollama inference call.

Response (`200 OK`):

```json
{
  "status": "ok",
  "service": "repopilot-backend"
}
```

### `POST /api/inference`

This is an M0 connectivity endpoint only, not the future RepoPilot agent API.
It sends a prompt through the provider boundary to the configured local Ollama
HTTP API.

Request:

```json
{
  "prompt": "Reply briefly."
}
```

Response (`200 OK`):

```json
{
  "model": "gemma4:e4b-it-qat",
  "response": "..."
}
```

Blank prompts, whitespace-only prompts, missing prompts, and unexpected request
fields return FastAPI validation errors (`422 Unprocessable Entity`). If Ollama
cannot be reached, the endpoint returns `503 Service Unavailable` with a clear
message containing the configured base URL. An invalid or unsuccessful Ollama
response returns `502 Bad Gateway`.

## Observed Ollama response structure

One real non-streaming `POST /api/generate` call to Ollama 0.32.9 with
`gemma4:e4b-it-qat` returned these top-level fields:

- `model`
- `created_at`
- `response`
- `done`
- `done_reason`
- `context`
- `total_duration`
- `load_duration`
- `prompt_eval_count`
- `prompt_eval_duration`
- `eval_count`
- `eval_duration`

No separate `thinking` field appeared in that observed response. The provider
returns only the `response` text to API callers and deliberately ignores any
separate `thinking` field if a model or Ollama version supplies one.

## Planned APIs (not implemented)

The following remain planning targets and are outside M0 Task 002:

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/projects` | Create a project from a GitHub URL or uploaded archive |
| POST | `/api/projects/{id}/index` | Build the tree-sitter and retrieval indexes |
| POST | `/api/runs` | Start a coding-agent run for issue text |
| WS | `/api/runs/{id}/events` | Stream steps, logs, tokens, and approval interrupts |
| POST | `/api/runs/{id}/approve` | Submit a decision and resume an interrupt |
| GET | `/api/runs/{id}/context` | Return retrieved chunks, scores, and provenance |
| GET | `/api/runs/{id}/diff` | Return the current patch diff and scope |
| POST | `/api/runs/{id}/tests` | Run or rerun approved sandboxed tests |
| POST | `/api/eval/swebench` | Run a configured selected SWE-bench Lite evaluation |
| POST | `/api/bench/models` | Run a configured model comparison |
| GET | `/api/metrics` | Expose Prometheus/OpenMetrics data |

Their schemas, status codes, authentication, idempotency, pagination, and
versioning will be specified only when those capabilities are implemented.
