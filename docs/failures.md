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

## 2026-09-12 - Line ranges alone produced false stale-evidence failures

### Context and expected behavior

M4 must prove that approved Tree-sitter evidence is unchanged before patch
generation and application. The first validator combined a chunk content hash
with its inclusive start/end line numbers and re-hashed those physical lines.

### Observed behavior

The initial focused M4 run rejected fresh canonical evidence in 19 tests as
`StaleApprovalError`. Separately, the clean pre-task backend baseline had two
failures because one toy Python fixture was checked out as CRLF while its
committed exact-source expectations were LF.

### Reproduction

Tree-sitter chunk end bytes stop at the syntax node and exclude the physical
line terminator. Reconstructing an inclusive final line added that terminator,
so its digest differed from the chunk digest. Git also reported `i/lf w/crlf`
for `fixtures/toy-repo/tests/test_pricing.py` before an EOL policy existed.

### Root cause

Line provenance identifies a review location but is not an exact byte span.
The checkpoint lacked the chunk source needed to pair the digest with the exact
approved text. The repository also relied on platform Git defaults for Python
line endings despite hashing exact UTF-8 source.

### Why existing controls missed it

M3 used evidence for citation/path membership but did not yet compare a later
workspace snapshot to the exact approved source. Existing tests had previously
run against LF working-tree bytes.

### Fix and alternatives

`PlanningEvidence` now carries both exact bounded chunk source and its SHA-256
hash. M4 verifies their internal consistency and exact source occurrence at the
recorded start line in both canonical and workspace copies. A root
`.gitattributes` enforces LF for Python files, and the toy fixture was restored
to its committed LF content. Hashing normalized source or accepting a full
physical line was rejected because either would weaken exact-source identity.

### Verification and regression test

After the fix, 32 focused M4 tests and the combined 58-test M3/M4 set passed.
The parser/pipeline regression set returned to 12/12 passing. The complete
backend result is recorded in `CONTEXT.md` after final verification.

### Remaining risk

Older durable M3 checkpoints do not contain exact source fingerprints. They can
still be inspected or rejected, but M4 must fail them as stale rather than patch
under incomplete evidence.

### Interview/public lesson

Line numbers are human provenance, not byte identity. Stale-approval checks need
the exact reviewed bytes and an explicit cross-platform EOL policy.
