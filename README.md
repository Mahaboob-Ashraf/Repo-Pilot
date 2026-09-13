# RepoPilot

**A local-first, human-controlled coding agent for Python repositories, built
to understand evidence before changing code.**

RepoPilot is an experimental developer tool that takes a software repository and an issue, builds a structure-aware representation of the codebase, retrieves the most relevant code, and runs a bounded repair workflow with human approval before changes are exported.

The project is designed around a simple principle:

> **A coding agent should understand repository structure, show its evidence, and remain bounded by explicit human authority.**

## Current Status

RepoPilot is **actively under development**.

The current implementation includes the retrieval/evaluation foundation and
the first bounded planning/approval segment:

* repository discovery and source-file ingestion;
* Python structure-aware parsing;
* function, class, method, and test code chunks;
* source provenance including file paths and line ranges;
* lexical BM25 and local-embedding Chroma retrieval;
* deterministic Reciprocal Rank Fusion with explicit dense-failure degradation;
* deterministic one-hop parent/child, local-import, and related-test evidence;
* immutable whole-chunk ContextPacks with hard estimated-token budgets;
* frozen-case retrieval and post-pack context evaluation metrics;
* evidence-grounded structured repair plans with exact chunk citations;
* a hash-bound LangGraph pause at the first human plan/file-scope approval;
* restart-safe local SQLite checkpoints behind a start/resume service boundary;
* strict structured exact-replacement patch proposals grounded in approved evidence;
* durable isolated workspaces with all-or-nothing approved-scope application;
* RepoPilot-generated repository-relative unified diffs and deterministic patch hashes;
* patch-hash-bound pytest execution through a restricted Docker runner;
* disposable test snapshots that preserve the durable M4 review workspace;
* bounded structured test evidence with distinct test/infrastructure outcomes;
* a structured evidence-grounded critic after genuine attempt-one failures only;
* a deterministic maximum of two clean-baseline patch attempts;
* a second durable human interrupt bound to exact passing patch/test evidence;
* idempotent export of the exact canonical diff after final approval only;
* local Ollama model integration through a provider boundary;
* a typed FastAPI workflow API with read-only refresh and exact-hash decisions;
* a focused React review workspace for evidence, plans, diffs, tests, retry history, final approval, and export;
* automated tests for repository discovery, parsing, chunking, retrieval, workflow safety, API behavior, and the review UI.

The core bounded workflow and M7 review/control surface are implemented. The
backend remains authoritative for state, scope, approvals, retries, testing,
and export; browser refresh uses read-only checkpoint retrieval and does not
repeat expensive stages. A real Docker-backed end-to-end smoke still requires
an already-running daemon and suitable local image; RepoPilot never pulls one
automatically.

## Why RepoPilot?

Many coding assistants can generate code from a prompt, but repository-level software engineering requires more than generation.

A useful coding agent needs to answer questions such as:

* Which files actually matter for this issue?
* Which function or class owns the relevant behavior?
* Which nearby tests and interfaces constrain a change?
* Is the retrieved context structurally meaningful or just textually similar?
* Can a proposed edit be restricted to an approved scope?
* Can the resulting patch be tested without exposing the host machine?
* Can a human inspect the evidence before allowing the agent to proceed?

RepoPilot is being built around those questions.

## Current Pipeline

```text
Repository
    |
    v
Repository Discovery
    |
    v
Structure-Aware Parsing
    |
    v
Semantic Code Chunks
    |
    v
BM25 + Dense Retrieval
    |
    v
Reciprocal Rank Fusion
    |
    v
One-Hop Structural Evidence
    |
    v
Bounded ContextPack
    |
    v
Evidence-Grounded RepairPlan
    |
    v
Human Approval Interrupt
    |
    +--> Approved
    |       |
    |       v
    |   Isolated Approved-Scope Patch
    |       |
    |       v
    |   Canonical Diff + Patch Hash (`patch_ready`)
    |       |
    |       v
    |   Verified Disposable Test Snapshot
    |       |
    |       v
    |   Restricted Docker Pytest
    |       |
    |       +--> `tests_passed` --> Final Hash-Bound Approval --> Patch Export
    |       +--> `tests_failed` --> Grounded Critic --> One Clean Retry Maximum
    |       +--> `test_infrastructure_failed`
    |
    +--> Rejected / terminal
```

The current foundation produces bounded cited evidence, a validated plan, two
durable human checkpoints, approved-scope isolated patches, patch-bound test
evidence, one optional clean-baseline retry, and exact patch export without
mounting, executing, or modifying the canonical repository.

## Structure-Aware Code Indexing

RepoPilot avoids treating a repository as a collection of arbitrary fixed-size text blocks.

The current Python parser extracts meaningful code structures such as:

* functions;
* classes;
* methods;
* tests;

Chunks retain source metadata so retrieved evidence can be traced back to the repository location from which it originated.

This foundation is intended to make later planning and patch generation operate on code structures rather than disconnected text fragments.

## Retrieval

The implemented retrieval layer provides separate lexical and dense search over
the same canonical chunks, followed by rank-only RRF.

Repository chunks are searchable using SQLite FTS5/BM25 for exact terms and
identifiers and Chroma cosine retrieval with RepoPilot-supplied local
embeddings for semantic evidence. RRF combines 1-based ranks without adding raw
BM25 scores to cosine distances. If the embedding provider is unavailable,
hybrid retrieval returns BM25 evidence with an explicit degraded status.

The implemented structural/context path adds:

```text
Fused BM25 + Dense Ranking
        +
One-Hop Import / Parent-Child / Related-Test Evidence
        |
        v
Bounded Context Pack
```

Expansion is exactly one hop and uses deterministic repository metadata. The
packer includes only whole chunks, never silently exceeds its configured
budget, and labels repository source as untrusted evidence rather than
instructions.

## Local-First Inference

RepoPilot uses an explicit model-provider boundary with **Ollama** as the local inference path.

The long-term goal is for the core workflow to remain usable without requiring a paid model API and to make model choice measurable rather than tightly coupled to the application.

## Testing

The repository currently includes automated coverage for:

* API behavior;
* code-chunk representation;
* Python parsing;
* repository discovery;
* repository-to-chunk pipeline behavior;
* lexical, dense, and hybrid retrieval;
* one-hop structural expansion and bounded context packing;
* frozen retrieval cases and context evaluation metrics;
* structured planner grounding, plan identity, and approval state;
* in-memory and durable SQLite pause/resume behavior;
* patch schema/prompt boundaries, scope and evidence enforcement, stale approval,
  exact matching, rollback, diff/hash identity, and replay isolation.
* Docker argv construction, selector validation, sandbox restrictions,
  disposable snapshots, bounded output, exit classification, and M5 routing.
* critic parsing/grounding, two-attempt enforcement, clean retry workspaces,
  final hash-bound pause/resume, exact export, and replay isolation.

Automated sandbox tests use deterministic process/runner fakes and do not
require a Docker daemon. Optional real Docker integration remains a separately
reported functional smoke.

## Target Architecture

RepoPilot is being developed toward the following workflow:

```text
Repository + Issue
        |
        v
AST-Aware Index
        |
        v
Hybrid Retrieval
        |
        v
Context Packing
        |
        v
Repair Plan
        |
        v
Human Review
        |
        v
Scoped Patch
        |
        v
Isolated Tests
        |
        v
Critique / Bounded Retry
        |
        v
Human-Approved Patch Export
```

The implemented path now includes the core bounded LangGraph workflow through
final human-approved patch export. Remaining planned components include:

* structured execution traces;
* retrieval benchmarks;
* feasible frozen external/system evaluation;

These are roadmap items rather than claims about the current implementation.

## Engineering Principles

### Local first

The core system is designed around locally runnable inference and infrastructure where practical.

### Human authority

RepoPilot is not intended to silently merge autonomous model changes. Material edits should remain visible and explicitly approved.

### Bounded execution

Agent iterations, editable paths, test commands, resources, and execution time are intended to have explicit limits.

### Evidence before generation

Retrieval and source provenance come before patch generation. The agent should be able to show which repository evidence informed a decision.

### Evaluation over demos

The eventual system will be evaluated on retrieval quality and repair behavior rather than relying only on successful demo examples.

## Tech Stack

| Area                     | Technology        |
| ------------------------ | ----------------- |
| Backend                  | Python, FastAPI   |
| Parsing                  | tree-sitter       |
| Current retrieval        | BM25 + Chroma + RRF |
| Current context          | One-hop structural index + bounded ContextPack |
| Local inference          | Ollama            |
| Dependency management    | uv                |
| Evaluation harness       | Frozen BM25/dense/hybrid cases |
| Current orchestration    | LangGraph + selective LangChain |
| Current sandbox boundary | Restricted Docker pytest |
| Current frontend         | React, Vite, TypeScript review workspace |

## Roadmap

### Implemented

* [x] FastAPI backend foundation
* [x] Repository discovery
* [x] Python structure-aware parsing
* [x] Semantic code chunks with provenance
* [x] Repository chunking pipeline
* [x] Lexical code retrieval
* [x] Local embedding and Chroma dense retrieval
* [x] Reciprocal Rank Fusion and dense-failure fallback
* [x] Frozen-case retrieval evaluation harness
* [x] One-hop structural expansion
* [x] Whole-chunk bounded context packing and context metrics
* [x] Evidence-grounded structured repair plan
* [x] First hash-bound LangGraph human approval checkpoint
* [x] In-memory and durable local SQLite workflow checkpoints
* [x] Approved-scope structured patch generation
* [x] Durable isolated workspace application and rollback
* [x] Canonical unified diff and deterministic patch hash
* [x] Patch-bound restricted Docker test runner and structured evidence
* [x] Typed workflow API and read-only durable refresh
* [x] React evidence/plan/diff/test/final review workspace
* [x] Ollama provider boundary
* [x] Automated tests for the implemented foundation

### Next

* [x] Optional critic / maximum-one-retry branch
* [x] Second/final approval and patch export
* [ ] Retrieval and safety evaluation
* [ ] External and system evaluation

## Project Direction

RepoPilot is not intended to become another repository chatbot, unrestricted
autonomous coding bot, multi-agent swarm, or autonomous PR/merge service.

The goal is a coding agent whose behavior can be inspected:

**what it retrieved → why it planned a change → what it changed → what tests ran → what failed → what the human approved.**

That end-to-end loop is the target the project is being built toward.
