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

## 2026-09-13 - M8 real dense and hybrid retrieval were blocked

### Expected behavior

The frozen M8 run should use production Chroma and the locked already-local
`embeddinggemma:latest` provider. It must not download a model or replace a
missing real embedding with a deterministic fake result.

### Observed behavior

The production embedding boundary returned `EmbeddingUnavailableError` during
dense index setup. Consequently `ast_dense`, `ast_hybrid_rrf`, and their normal
hybrid-dependent structure/ContextPack rows were recorded as blocked in the
initial M8 artifacts. BM25 completed normally. A separately labeled lexical-only degraded
probe exercised production fallback, one-hop expansion, and packing without
using or claiming vector evidence.

### Safe outcome and remaining limitation

No download, retry loop, parameter change, fake benchmark vector, or arbitrary
provider diagnostic was introduced. Real dense/hybrid retrieval quality remains
unmeasured in this run and must be rerun only when the locked model is already
available. The blocked result does not invalidate the offline deterministic
safety scorecard.

### Follow-up resolution

Task 018B retained this initial failure record, then successfully reran the same
frozen production path after the exact already-local model became reachable.
The current M8 artifacts contain real dense/hybrid measurements and the model
digest; no model download, retrieval tuning, Docker, or Gemma generation was
used.

## 2026-09-13 - M9 real repair evaluation blocked at Docker preflight

### Context and expected behavior

The frozen M9 set requires the existing M5 sandbox and already-local
`repopilot-python-test:3.11-pytest9` image before any case can count as an
attempted repair.

### Observed behavior

The explicit materializer and fixture checker verified three pinned public
repositories and six controlled-defect fixtures. Ollama HTTP exposed both
locked models and exact digests. The installed Docker CLI could not reach its
daemon, so local image identity could not be inspected. The canonical M9
artifact records 0 attempted repairs, 0 completed repairs, and 6 infrastructure-
blocked cases; every rate and latency for an unexecuted stage remains null.

### Safe outcome and remaining risk

No image pull/build, Docker configuration change, host test, Gemma generation,
workflow approval, patch, export, or fake repair result occurred. The M9
production executor and offline harness exist, but real two-checkpoint repair
behavior remains unmeasured until a running daemon and exact local image are
provided through a separately authorized setup action.

## 2026-09-13 - External more-itertools ingestion terminated the process

### Context and expected behavior

With Docker repair already blocked but Ollama available, M9 permits a separately
labeled partial ingestion/retrieval diagnostic. `build_repository_chunks`
should return a complete chunk set or a typed Python exception.

### Observed behavior

The first more-itertools case terminated the Python process with exit code 1
inside `build_repository_chunks`, before the post-chunking progress boundary and
without stderr or a Python traceback. The behavior repeated after replacing the
full checkout with a pinned minimal fixture containing the license, package,
and upstream test file. BM25, embeddings, retrieval, ContextPack, planning, and
all repair stages were not reached.

### Why existing controls missed it

The current M1 pipeline is in-process and fail-fast. Automated fixtures cover
typed malformed-Python failures but not a native/process-level parser exit on
an unfamiliar larger source set. The evaluation runner cannot classify an
exit that terminates its own process.

### Safe outcome and remaining risk

Diagnostic reruns stopped after localization, no retrieval metric was recorded,
and at that point the canonical artifact remained Docker-blocked rather than
partially fabricated. Robust per-case subprocess isolation and identification
of the specific parser input were left for follow-up. M9 parser, chunking,
retrieval, or context policies were not tuned around the case.

### Task 019B resolution

After Docker was started and the local image build was explicitly approved,
per-file subprocess isolation reproduced Windows access violation
`0xC0000005`. The failing inputs included `more_itertools/more.py`,
`tests/test_recipes.py`, and several large toolz files. Faulthandler localized
the corruption to node/line metadata access during construct creation.

The parser read `span.start_point.row` and `span.end_point.row` from temporary
native Tree-sitter `Point` wrappers. Repeated reads on large Windows trees
corrupted later node/Python-object state. Computing the same 1-based line
ranges from stable node byte offsets removed the native failure. A 500-function
regression and the focused M1 suite pass; all six external cases now complete
chunk construction independently. No retrieval behavior or ranking parameter
changed.

## 2026-09-13 - One frozen M9 selector was not a genuine failing test

### Observed behavior

The controlled mutation for `boltons-floor-upper-choice` was present and its
fixture fingerprint matched, but the configured
`tests/test_mathutils.py::test_floor_sorted` selector passed. The test compares
the mutated function on unsorted and sorted versions of the same values, so the
wrong upper-choice behavior remains equal on both sides.

### Safe outcome

The frozen case and gold labels were not rewritten. The case is recorded as
`benchmark_fixture_invalid` and was not sent to retrieval or generation. M9 v2
now replaces it under a new case identity; this v1 result remains intact.

## 2026-09-13 - Real M9 attempts stopped at planning and exposed an evidence gap

### Observed behavior

Five valid frozen cases completed ingestion and retrieval, then failed at the
planner boundary before approval #1. Four larger cases also reached the normal
lexical-only fallback after the unchanged 60-second embedding setup timeout.
The initial M9 observation kept the failure stage but failed to copy the
workflow's typed planner error record, so output parsing versus grounding
failure cannot be distinguished post-hoc without impermissibly rerunning cases.

### Safe outcome

No cases were rerun, no generated output was manually repaired, and no M9
parameter was tuned. Subsequent observations now retain the workflow error
type, safe message, and provider classification. The canonical artifact states
the missing detail explicitly. All five attempts remain terminal planner
failures with zero repair success.

### Task 019C corrected interpretation

The retained Ollama log closes the evidence gap: each of the five original
generation calls was preceded by `ggml_vulkan: device lost on Vulkan0` and
returned HTTP 500. Those attempts are infrastructure-invalid, not valid planner
or repair-quality failures. The old JSON remains preserved as the output of its
then-incomplete observation schema; `m9-task-019c-diagnosis.json` records the
post-hoc classification and hashes the source artifacts.

The representative initial diagnostic reproduced the same provider/runtime
failure once. The one justified confirmation then received model output, parsed
it as a `RepairPlan`, and rejected it during deterministic grounding because
step 1 cited unknown chunk `N/A`. That confirmation exposes one genuine
model/system weakness but cannot retroactively turn the original five failed
HTTP requests into valid benchmark samples. No prompt, schema, grounding,
retrieval, context, model, or retry behavior changed.

## 2026-09-13 - M9 v1 floor selector compared wrong behavior with itself

### Root cause

`test_floor_sorted` checks `floor(x, OPTIONS) == floor(x, OPTIONS_SORTED)`.
Production `floor` sorts either input internally, so replacing
`return options[i - 1]` with `return options[i]` returns the same incorrect
upper choice on both sides. The selector therefore tests order invariance, not
the claimed floor value, and cannot discriminate this mutation.

### Benchmark-data repair

M9 v1, case `boltons-floor-upper-choice`, its passing pre-repair result, and its
fingerprint remain intact. The new v2 manifest uses case identity
`boltons-floor-exact-option` and existing upstream selector `test_floor_basic`,
whose literal expectations detect the upper-choice defect. Mutation and fixture
bytes are unchanged, so the fixture fingerprint remains the same while schema,
benchmark ID, case ID, selector, provenance, and overall manifest fingerprint
change.

### Verification

The corrected case materialized from the existing pinned cache, matched its
fingerprint, contained the controlled defect, and failed before repair in the
locked M5 Docker sandbox with exit code 1 and
`pytest_assertion_failure`. The fixture hash was unchanged after execution.
This is benchmark-data correction, not tuning of RepoPilot or exposure of gold
repair data to production workflow services.

## 2026-09-13 - Clean M9 v2 exposed planner and patch-output weaknesses

### Observed behavior

The CPU-only frozen v2 run avoided the previously proven Vulkan failure and
recorded zero provider/infrastructure failures. Three of six planner responses
could not be parsed as `RepairPlan`; two parsed responses cited unknown chunks
(`Snippet 1` and `12`) and failed grounding. The only valid grounded plan
reached patch generation, but its proposal failed deterministic validation.
The workflow retained typed errors and bounded messages and stopped before any
unsafe application or repair-test execution.

### Safe outcome

No prompt, schema, grounding rule, model, retrieval, context budget, or retry
policy was changed. No output was regenerated or manually repaired. The final
repair score is honestly 0/6. There were no scope, stale/hash, canonical-
mutation, retry-limit, or export-order violations. These measured failures are
M10 candidates; deterministic validation and grounding must not be weakened to
improve the score.

## 2026-09-14 - Explicit citation lists exhausted the runtime context

### Observed behavior

Native JSON Schema produced 3/3 valid grounded development plans. Appending a
separate list of every allowed chunk ID/path regressed the medium case to a
15-token truncated JSON response.

### Root cause and safe outcome

The added list raised prompt evaluation from 3,467 to 4,081 tokens against the
loaded model's 4,096-token context. The list change was reverted. Native schema
was kept because it achieved 3/3 without removing Pydantic parsing or grounding;
invented identifiers are still rejected, never mapped.

## 2026-09-14 - Indented methods triggered false stale-evidence failures

### Observed behavior

M9-v3 safely rejected two approved plans as `StaleApprovalError`. A deterministic
scan reproduced mismatches for method chunks whose Tree-sitter source begins at
`def` while the declared line begins with indentation.

### Root cause and fix

Freshness validation assumed source text began at column zero. It now requires
one exact source match within the declared line range while preserving the
content hash, line bounds, and all exact-edit checks. A regression covers an
indented method. M9-v3 was not rerun, so both safe failures remain in evidence.

## 2026-09-14 - Dense setup changed from timeout to transient HTTP 400

Bounded batches removed the prior single 60-second request. Four M9-v3 larger
cases instead degraded after `EmbeddingResponseError` / HTTP 400. An embedding-
only replay of all fifteen 32-item batches for the 474-chunk repository then
succeeded, including an 8,681-byte chunk, so no deterministic size limit was
proven. Retry policy, timeout, and fallback were left unchanged. Future work
should retain a bounded allowlisted Ollama error code/body classification and
investigate model-residency pressure.
