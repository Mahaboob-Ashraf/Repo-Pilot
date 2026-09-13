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

## 2026-09-12 - Real M5 Docker smoke blocked at daemon preflight

### Context and expected behavior

After the offline M5 runner, workspace, and graph tests passed, the optional
canonical smoke required both a running Docker daemon and a suitable
RepoPilot-controlled Python test image already available locally.

### Observed behavior

`docker version` reported client 29.7.2 and the `desktop-linux` context, but its
server query and `docker info` could not open the
`dockerDesktopLinuxEngine` named pipe. Local image enumeration failed at the
same daemon boundary, so no image availability claim or container execution
was possible.

### Reproduction

Run the read-only `docker version`, `docker info`, and `docker image ls
--no-trunc` preflight with Docker Desktop's Linux context selected. The client
is installed, but the daemon endpoint is absent.

### Root cause

The local Docker Linux daemon was not running or otherwise available. Because
the daemon could not answer, whether the configured
`repopilot-python-test:3.11-pytest9` image exists locally is unknown.

### Why existing controls missed it

Automated M5 tests deliberately inject deterministic process/runner fakes so
the backend suite remains portable and cannot require Docker. A real daemon is
checked only by the optional functional smoke preflight.

### Fix and alternatives

No machine change was authorized or attempted. RepoPilot fails this condition
as distinct infrastructure evidence and never pulls automatically. Starting or
installing Docker and pulling/building an image were explicitly outside Task
015 authority; a later setup action requires explicit user approval.

### Verification and regression test

The 42 focused M5 tests cover daemon/image unavailability, verify that missing
images never reach `docker run` or a pull, and keep the full 240-test backend
suite independent of Docker. The real smoke did not run.

### Remaining risk

The concrete Windows-to-Docker bind mount and selected local image environment
remain unverified on this machine until the daemon and image are available.

### Interview/public lesson

Separate sandbox-policy correctness from environment availability: deterministic
tests can prove command construction and fail-closed behavior without claiming
that an unavailable local container runtime executed code.

## 2026-09-12 - Complete real M6 smoke remained blocked by Docker prerequisite

### Context and expected behavior

Task 016 completed the post-test critic/retry/final-review/export workflow. A
real end-to-end smoke would still need the M5 Docker stage to execute an exact
patched workspace before final review.

### Observed behavior

The existing read-only M5 preflight had already established that the installed
Docker client could not reach the `desktop-linux` daemon and could not enumerate
the required local image. No new Docker execution was attempted, no image was
pulled or built, and no machine configuration was changed.

### Root cause and safe outcome

The external daemon/image prerequisite remains unavailable. M6 automated tests
therefore used deterministic providers and runner fakes. The workflow's real
infrastructure branch remains distinct and cannot trigger critic inference or a
repair retry. The optional standalone CPU-only critic smoke was also skipped
because it was optional and prior model calls took minutes; no benchmark claim
is made.

### Remaining risk

The combined real Docker test-to-final-review path remains unverified on this
machine until an already-local compatible image and running daemon are
available through a separately authorized setup action.

## 2026-09-13 - Task 017 real UI smoke prerequisites were unavailable

### Context and expected behavior

After automated M7 API/UI verification, an optional functional smoke could run
only if the existing local Ollama and Docker prerequisites were already
available. No installation, daemon start, model download, image pull/build, or
machine change was authorized.

### Observed behavior

The established read-only `ollama ps`, `docker version`, `docker info`, and
`docker image ls --no-trunc` preflight commands could not resolve either
executable on the current command PATH. The functional UI smoke did not start.

### Safe outcome and remaining risk

No real inference, container, workflow POST, repository mutation, or export was
attempted. The 275-test backend suite, 18 frontend tests, TypeScript check, and
production build passed with deterministic boundaries, but the real M7
browser-to-Gemma path and Docker continuation remain unverified in this
session. This is an environment limitation, not benchmark evidence.
