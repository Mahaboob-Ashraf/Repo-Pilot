# RepoPilot Failure Analyses

Record serious bugs, unsafe behavior, incorrect assumptions, and benchmark/evaluation failures. Do not log hypothetical failures as observed incidents.

<!--
## YYYY-MM-DD - Short failure title

### Context and expected behavior

### Observed behavior

### Reproduction

### Root cause

### Why existing controls missed it

### Fix and alternatives

### Verification and regression test

### Remaining risk

### Interview/public lesson
-->

## 2026-09-12 - Real Gemma planner request lost its Vulkan device

### Context and expected behavior

The canonical discount ContextPack was sent once to the accepted Task 013
planner using local `gemma4:e4b-it-qat`. A successful response should parse and
ground before LangGraph pauses at the first approval interrupt.

### Observed behavior

Retrieval and the 1,805/2,000-unit ContextPack completed in normal hybrid mode.
The diagnostic rerun's sole generation request took 52.784 seconds and returned
Ollama HTTP 500, so the graph terminated `planner_failed` before output parsing,
grounding, hashing, or approval. The toy repository hashes were unchanged.

### Reproduction

One local run used the canonical toy repository, `embeddinggemma`, BM25,
Chroma, RRF with `candidate_k=3`, structural `top_k=1`, the 2,000-unit pack,
the unchanged Task 013 prompt, and `gemma4:e4b-it-qat` through Ollama 0.32.15.
It was not retried.

### Root cause

RepoPilot retained `InferenceResponseError`, classification `response_error`,
and safe message `Ollama returned HTTP 500`. Only log bytes appended after the
preflight offset showed `ggml_vulkan: device lost on Vulkan0` for the GeForce
GT 730 immediately before Ollama logged the 500 response.

### Why existing controls missed it

The original workflow stored only the wrapping `PlannerInferenceError`, which
correctly failed closed but discarded the safe provider classification needed
to distinguish availability, response, parse, and grounding failures.

### Fix and alternatives

Known provider failures now retain bounded type, classification, allowlisted
message, and model fields in JSON state while keeping exception chaining
in-process. Arbitrary exception text, headers, credentials, bodies, and live
exception objects are excluded. Planner behavior, prompt, model, validation,
graph topology, and approval semantics were unchanged.

### Verification and regression test

Focused planner/workflow tests passed 26/26 and the backend suite passed
166/166. Tests cover availability and response classification, fail-closed
workflow state, no approval, no repository mutation, exception chaining, and
absence of injected secret/header/body text from the persisted checkpoint.

### Remaining risk

The selected local model cannot complete this smoke on the observed Vulkan
runtime/hardware configuration. The model still appeared loaded immediately
after failure, so loaded status alone does not prove successful inference.

### Interview/public lesson

Failing closed is necessary but insufficient for diagnosis: preserve only the
small, explicitly safe error fields needed to distinguish infrastructure
failure from model-output and validation failure.
