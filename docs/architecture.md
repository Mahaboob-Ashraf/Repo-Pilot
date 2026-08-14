# RepoPilot Architecture

## Planned system boundary

```text
React Studio
    -> FastAPI API and event stream
        -> persisted LangGraph run
            -> tree-sitter indexer
            -> SQLite FTS5 + Chroma + dependency graph
            -> Ollama (default) / vLLM adapter (optional)
            -> approved Git workspace edits
            -> Docker test sandbox
        -> SQLite state, approvals, events, patches, tests, benchmarks
```

No component above is implemented yet.

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
