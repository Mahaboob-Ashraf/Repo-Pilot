# RepoPilot API Plan

This is a planning contract, not an implemented API. Schemas, status codes, auth, idempotency, pagination, and versioning will be specified alongside implementation.

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

## Cross-cutting requirements

- Use opaque project/run IDs and validate ownership at every lookup.
- Make mutating retry semantics explicit; approval submissions must be idempotent for the same decision payload.
- Reject stale approval hashes and scope changes not separately reviewed.
- Redact secrets from errors, events, context, and logs.
- Bound upload size, repository size, event buffers, prompt budgets, and run duration.
- Preserve machine-readable error codes and correlation/run IDs.
