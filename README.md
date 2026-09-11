# RepoPilot

**A local-first, human-controlled coding agent for Python repositories, built
to understand evidence before changing code.**

RepoPilot is an experimental developer tool that takes a software repository and an issue, builds a structure-aware representation of the codebase, retrieves the most relevant code, and is being developed toward a bounded repair workflow with human approval before changes are exported.

The project is designed around a simple principle:

> **A coding agent should understand repository structure, show its evidence, and remain bounded by explicit human authority.**

## Current Status

RepoPilot is **actively under development**.

The current implementation focuses on the retrieval/evaluation foundation
required before the bounded repair workflow:

* repository discovery and source-file ingestion;
* Python structure-aware parsing;
* function, class, method, and test code chunks;
* source provenance including file paths and line ranges;
* lexical BM25 and local-embedding Chroma retrieval;
* deterministic Reciprocal Rank Fusion with explicit dense-failure degradation;
* frozen-case BM25/dense/hybrid evaluation harness and pre-context metrics;
* local Ollama model integration through a provider boundary;
* FastAPI application foundation;
* automated tests for repository discovery, parsing, chunking, retrieval, and API behavior.

The complete planning → patching → sandbox testing → critique → approval workflow is **not yet complete**.

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
Relevant Files / Symbols
```

The current milestone concentrates on making this retrieval foundation
measurable before adding one-hop evidence and the bounded repair workflow.

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

The next retrieval milestone adds:

```text
Fused BM25 + Dense Ranking
        +
One-Hop Import / Parent-Child / Related-Test Evidence
        |
        v
Bounded Context Pack
```

Structural expansion and context packing are not yet implemented.

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
* frozen retrieval cases and pre-context evaluation metrics.

As additional subsystems are implemented, the test surface will expand to cover agent state, approvals, patch safety, sandbox execution, and evaluation.

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

Planned components include:

* dependency-aware context expansion;
* one bounded LangGraph repair workflow with selective LangChain utilities;
* bounded patch generation;
* immutable human approval boundaries;
* Docker-isolated repository testing;
* structured execution traces;
* retrieval benchmarks;
* feasible frozen external/system evaluation;
* a React review interface.

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
| Local inference          | Ollama            |
| Dependency management    | uv                |
| Evaluation harness       | Frozen BM25/dense/hybrid cases |
| Planned orchestration    | LangGraph + selective LangChain |
| Planned sandbox          | Docker            |
| Planned frontend         | React, TypeScript |

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
* [x] Ollama provider boundary
* [x] Automated tests for the implemented foundation

### Next

* [ ] Dependency-aware context expansion
* [ ] Context packing
* [ ] One bounded LangGraph repair workflow
* [ ] Two-checkpoint human approval persistence
* [ ] Scoped patch generation
* [ ] Docker-isolated testing
* [ ] Optional critic / maximum-one-retry branch
* [ ] Retrieval and safety evaluation
* [ ] External and system evaluation
* [ ] React review studio

## Project Direction

RepoPilot is not intended to become another repository chatbot, unrestricted
autonomous coding bot, multi-agent swarm, or autonomous PR/merge service.

The goal is a coding agent whose behavior can be inspected:

**what it retrieved → why it planned a change → what it changed → what tests ran → what failed → what the human approved.**

That end-to-end loop is the target the project is being built toward.
