# RepoPilot

**A local-first, human-in-the-loop coding agent built to understand repositories before changing them.**

RepoPilot is an experimental developer tool that takes a software repository and an issue, builds a structure-aware representation of the codebase, retrieves the most relevant code, and is being developed toward a bounded repair workflow with human approval before changes are exported.

The project is designed around a simple principle:

> **A coding agent should understand repository structure, show its evidence, and remain bounded by explicit human authority.**

## Current Status

RepoPilot is **actively under development**.

The current implementation focuses on the foundation required before autonomous repair:

* repository discovery and source-file ingestion;
* Python structure-aware parsing;
* function, class, method, module, test, and configuration code chunks;
* source provenance including file paths and line ranges;
* lexical code retrieval;
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
Lexical Retrieval
    |
    v
Relevant Files / Symbols
```

The current milestone concentrates on making this retrieval foundation reliable before adding broader agent autonomy.

## Structure-Aware Code Indexing

RepoPilot avoids treating a repository as a collection of arbitrary fixed-size text blocks.

The current Python parser extracts meaningful code structures such as:

* functions;
* classes;
* methods;
* module-level context;
* tests;
* configuration-related chunks.

Chunks retain source metadata so retrieved evidence can be traced back to the repository location from which it originated.

This foundation is intended to make later planning and patch generation operate on code structures rather than disconnected text fragments.

## Retrieval

The implemented retrieval layer provides lexical search over indexed code.

Repository chunks are searchable using BM25-style lexical relevance, allowing issue terms, identifiers, symbols, and implementation vocabulary to surface relevant portions of the codebase.

The longer-term retrieval design will combine:

```text
Lexical Retrieval
        +
Vector Retrieval
        +
Dependency Context
        |
        v
Reciprocal Rank Fusion
        |
        v
Bounded Context Pack
```

Vector retrieval, fusion, and dependency expansion are part of the planned system and should not yet be considered complete.

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
* lexical retrieval.

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

* hybrid lexical + vector retrieval;
* dependency-aware context expansion;
* stateful agent orchestration;
* bounded patch generation;
* immutable human approval boundaries;
* Docker-isolated repository testing;
* structured execution traces;
* retrieval benchmarks;
* selected SWE-bench Lite evaluation;
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
| Current retrieval        | Lexical / BM25    |
| Local inference          | Ollama            |
| Dependency management    | uv                |
| Planned vector retrieval | Chroma            |
| Planned orchestration    | LangGraph         |
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
* [x] Ollama provider boundary
* [x] Automated tests for the implemented foundation

### Next

* [ ] Vector retrieval
* [ ] Lexical + vector fusion
* [ ] Dependency-aware context expansion
* [ ] Context packing
* [ ] Stateful repair planning
* [ ] Human approval persistence
* [ ] Scoped patch generation
* [ ] Docker-isolated testing
* [ ] Critic / bounded repair loop
* [ ] Retrieval benchmark
* [ ] Selected SWE-bench Lite evaluation
* [ ] React review studio

## Project Direction

RepoPilot is not intended to become another repository chatbot or an unrestricted autonomous coding bot.

The goal is a coding agent whose behavior can be inspected:

**what it retrieved → why it planned a change → what it changed → what tests ran → what failed → what the human approved.**

That end-to-end loop is the target the project is being built toward.
