# RepoPilot Devlog

Record meaningful engineering events, not routine progress. Initialization is not presented as a technical lesson.

<!--
## YYYY-MM-DD - Short title

### What we were trying to do

### What happened

### Why it happened

### Approaches considered

### Final solution

### How it was verified

### Metrics / evidence

### Remaining limitations

### Public-content angle
-->

## 2026-09-12 - Approval became a content-addressed safety boundary

### What we were trying to do

Turn a bounded ContextPack into a structured repair plan and pause one bounded
workflow for human approval without allowing any repository mutation.

### What happened

The model boundary could produce typed JSON, but type validity alone could not
prove that cited chunks or proposed edit paths came from the reviewed evidence.
Approval also needed to survive a restart without authorizing a changed plan.

### Why it happened

Schema validation answers whether output has the expected shape. It does not
establish evidence membership or approval identity; those are application
invariants that require deterministic checks outside the model.

### Approaches considered

Free-form parsing, silently replacing invented citations, accepting a bare
approve/reject string, keeping product checkpoints only in memory, and placing
provider objects in graph state were rejected.

### Final solution

LangChain renders the trust-separated prompt and parses a frozen Pydantic
RepairPlan through the existing RepoPilot provider. First-party validation
restricts every citation and path to the exact ContextPack. Canonical JSON plus
SHA-256 identifies the validated plan. LangGraph then pauses at a real
interrupt; an explicit decision must carry that same hash. JSON-friendly state
uses a stable thread ID and can be stored in local SQLite outside the source
checkout.

### How it was verified

Offline tests covered malformed output, invented paths/citations, deterministic
hashing, pause/resume, stale hashes, thread isolation, both terminal branches,
no planner rerun, repository non-mutation, and service reconstruction over the
same SQLite database.

### Metrics / evidence

The M3-focused tests passed 24/24 and the complete backend suite passed 164/164
on 2026-09-12. These are functional and safety checks, not repair-quality or
performance benchmark results.

### Remaining limitations

M3 stops before patch generation. There is no Docker execution, critic/retry,
second approval, or workflow API/UI. A later single real-model smoke reached
normal hybrid ContextPack construction but ended at `PlannerInferenceError`
after 51.015 seconds, before a plan or approval interrupt; it was not retried.
The bounded diagnostic follow-up preserved safe provider type/classification,
message, and model fields without exception objects or request internals. Its
single rerun failed after 52.784 seconds with Ollama HTTP 500; newly appended
server logs exposed a Vulkan device loss on the GeForce GT 730. No RepoPilot
planner/grounding/graph behavior was changed to obtain a pass.

### Public-content angle

Human approval is meaningful only when it is bound to an immutable artifact:
validate evidence membership first, hash the exact plan, and make stale
decisions fail closed.

## 2026-09-12 - Approved scope became executable without touching source

### What we were trying to do

Extend the first human checkpoint into bounded patch generation while keeping
the canonical repository read-only and stopping before any test execution.

### What happened

A valid patch schema alone was insufficient. M4 also needed to prove that the
approval still referred to current evidence, validate all replacements before
one write, recover from a multi-file failure, generate its own review diff, and
avoid applying again when LangGraph replays a completed node.

### Why it happened

Model output is untrusted intent, not edit authority or diff syntax. Tree-sitter
line provenance also did not reproduce exact node end bytes, and a Windows CRLF
checkout exposed that source fingerprints require explicit EOL policy.

### Approaches considered

Model-authored diffs, fuzzy matching, direct source-checkout edits, partial
application, model-selected paths, mandatory Git commits/worktrees, ephemeral-
only workspaces, and automatic patch retries were rejected.

### Final solution

LangChain templates and parses strict exact-replacement proposals through the
existing provider. RepoPilot rechecks the approval hash/scope and exact chunk
source/hash, creates a durable external snapshot, validates every path,
citation, old-text occurrence, and range against the original snapshot, then
applies non-overlapping edits from the end of each file. Original bytes support
rollback. RepoPilot creates and hashes the canonical relative unified diff.
Opaque repository/thread/plan-bound workspace IDs plus durable completion
records make successful replay idempotent and conflicting state explicit.

### How it was verified

Offline tests cover prompt authority, strict parsing, unsafe paths, new-file and
symlink attempts, unapproved scope, invented/unrelated evidence, stale source,
missing/ambiguous/overlapping old text, deterministic multi-edits, whole-patch
rejection, rollback, workspace persistence, diff/hash identity, graph routing,
bounded state, replay, and thread isolation.

### Metrics / evidence

The 32 focused M4 tests, 58 combined M3/M4 tests, and complete 198-test backend
suite passed on 2026-09-12. In the one optional CPU-only functional smoke, the
single planner request took 183.976 seconds and the single patcher request took
161.725 seconds. The exact in-run plan was approved normally, the graph reached
`patch_ready`, and both canonical toy source hashes remained unchanged. These
are functional safety results, not benchmark measurements.

### Remaining limitations

M4 modifies existing UTF-8 regular files only. It cannot create, delete, or
rename files, fuzzy-match source, execute tests, invoke a critic, retry, perform
final approval, export a patch, or create a PR.

### Public-content angle

None queued. The user explicitly requested no public post.

## 2026-09-13 - M8 real dense and hybrid evidence completed

### What we were trying to do

Replace only the previously blocked real retrieval rows after the locked local
`embeddinggemma:latest` service became available, without tuning the frozen
benchmark or invoking Docker or generation.

### Final solution

The existing M8 production path ran Tree-sitter chunks through the Ollama
embedding provider, Chroma, BM25, RRF, one-hop structure, and ContextPack. The
artifact now records the exact local model digest and measured pack-status
distribution; report prose selects measured or blocked conclusions from the
artifact instead of retaining stale text.

### Metrics / evidence

Across 10 frozen cases, BM25 and dense each measured file Hit@1 0.90 and file
MRR 0.95; hybrid RRF measured 1.00 for file and symbol Hit@1, Hit@5, and MRR.
Dense query p50/p95 was 135.6953/221.1889 ms and hybrid was
136.7950/216.8195 ms. One-hop expansion added no chunks. Final packs covered all
labeled gold files and symbols, with mean file precision 0.3750 and file token
waste 0.6195. The deterministic safety rerun remained 33/33 passing.

### Remaining limitations

This is a small synthetic controlled evaluation, not external repair or
production evidence. At returned depth 10 the small repositories exposed no
measurable structural-expansion effect. No Docker, Gemma generation, download,
fixture change, or retrieval/prompt/budget/policy tuning occurred.

### Public-content angle

None queued. The user explicitly requested no public post.

## 2026-09-13 - Task 018 frozen retrieval and safety evaluation

### Problem

The existing evaluation code proved retrieval and ContextPack metric behavior
against one toy repository, but it did not provide a frozen multi-repository
M8 dataset, structural-effect accounting, context-budget cases, formal safety
scorecard, reproducible CLI, or durable reports.

### Final solution

Added 10 synthetic issue cases across four evaluation-only Python repositories,
symbol Hit@1 and full gold coverage/exclusion fields, explicit one-hop causes and
noise/help accounting, and four fixed 16,384-unit ContextPack policy scenarios.
The M8 CLI runs retrieval, safety, or both and writes stable JSON plus Markdown.

The 33-scenario safety suite keeps eight categories separate and exercises real
RepoPilot validators plus deterministic approval, patch workspace, critic,
selector, retry, and export probes. A failed invariant makes the command fail.
Repository/issue/test prompt injection is evaluated as inability to grant
deterministic authority, not as universal LLM immunity.

### Metrics / evidence

The initial 10-case BM25 run measured file Hit@1 0.90, Hit@5 1.00, and file
MRR 0.95. `embeddinggemma:latest` was unavailable, so real dense and hybrid rows
were explicitly blocked in that initial artifact. A separately labeled lexical-only degraded run found
structure helped two cases, added only non-gold evidence in five, and produced
mean file token waste 0.535 while retaining full file coverage in these small
cases. The budget competition case excluded relevant evidence and retained 0.50
gold coverage. All 33 safety scenarios passed.

The pre-run complete backend suite passed 285 tests in 5.18 seconds; focused M8
tests passed 12. Frontend regressions remained 18 passing tests plus a successful
TypeScript/Vite build. After artifact completion, the final backend suite passed
287 tests in 6.26 seconds.

### Limitations

This is controlled local evidence, not SWE-bench, external repair success,
production reliability, or a statistically representative sample. No model,
image, or dependency was downloaded; no retrieval/prompt/budget/retry parameter
was tuned; no Docker or real generation smoke ran. M9 owns external/system
evaluation and M10 owns evidence-driven optimization.

## 2026-09-12 - Bounded repair loop completed without autonomous authority

### What we were trying to do

Complete the core workflow after M5 while preserving the first approved file
scope, exact patch/test identity, and a strict maximum of two patch attempts.

### Final solution

RepoPilot now parses a strict evidence-grounded critic assessment only after a
genuine attempt-one assertion failure. A deterministic acyclic controller may
launch one retry in a fresh workspace copied from the original approved
baseline. The first passing candidate pauses at a second real LangGraph human
interrupt. Exact hash approval re-verifies the workspace and successful test
evidence, then exports the existing canonical diff outside the repository.
Rejection, stale hashes, tampering, infrastructure errors, malformed critic
output, and second-attempt failure all terminate without further generation or
export.

### How it was verified

Offline deterministic tests exercise critic security and parsing, clean retry
identity, the two-attempt ceiling, pass/failure routing, durable final checkpoint
restart, export bytes/hash/conflicts, stale workspace rejection, JSON state,
replay, and thread isolation. The focused set passed 32/32 and the complete
backend suite passed 266/266; neither required Docker nor Ollama.

### Remaining limitations

The React review workspace is not connected. The fixed Docker image and daemon
must already exist for real tests, dependency provisioning remains out of
scope, and RepoPilot exports a patch only—never apply/commit/push/merge/PR.

### Public-content angle

None queued. The user explicitly requested no public post.

## 2026-09-12 - Exact patch identity crossed a restricted Docker boundary

### What we were trying to do

Extend the approved M4 path through one bounded pytest execution without
mounting or mutating the canonical repository or durable review workspace.

### What happened

The hard part was not invoking Docker; it was preserving identity across the
boundary. A trustworthy result needs to prove which plan-bound patch, workspace
bytes, selectors, image ID, and resource policy produced it, while preventing
repository or model text from becoming shell syntax.

### Why it happened

Docker isolation alone does not make an unbounded command safe, and testing the
durable review copy would allow pytest or repository code to contaminate the
artifact later shown at final approval.

### Final solution

RepoPilot verifies every M4 workspace file against trusted patch metadata,
copies exact bytes into a disposable snapshot, validates optional pytest node
selectors, and passes fixed literal argv to a restricted Docker container with
no network, dropped capabilities, no-new-privileges, non-root execution,
read-only root/source filesystems, tmpfs, and explicit resource/time limits.
Output is bounded and classified. Durable test evidence is keyed by thread,
patch, request, image reference, and policy for replay safety.

### How it was verified

Deterministic fakes cover command safety, missing daemon/image behavior,
timeout cleanup, output truncation, workspace tampering, snapshot disposal,
canonical/durable preservation, result persistence, graph terminals, and
thread isolation. No automated test requires Docker or Ollama.

### Metrics / evidence

The focused M5 set passed 42/42 and the complete backend suite passed 240/240
on 2026-09-12. The optional real smoke was blocked because the installed Docker
client could not reach its Linux daemon, so no local image or runtime claim was
made. These are functional safety results, not benchmarks.

### Remaining limitations

No dependency provisioning, networked install, critic, retry, final approval,
patch export, frontend integration, or real Docker smoke is included. The fixed
test image must already exist locally and contain the repository's test
environment.

### Public-content angle

None queued. The user explicitly requested no public post.

## 2026-09-13 - The bounded workflow gained a human review surface

### What we were trying to do

Expose the completed M3–M6 workflow to a local human without turning React into
an IDE, workflow engine, or source of approval authority.

### Final solution

FastAPI now projects the existing workflow through typed create/read/decision
routes. The GET path only reconstructs checkpoint state. Both POST decisions
carry the exact displayed content hash and call the existing service checks.
The React workspace shows repository evidence, plan diagnosis and scope,
canonical diff, patch-bound test evidence, optional critic/one-retry history,
the final export checkpoint, bounded failures, and export-only completion.

The active thread ID lives in the URL for refresh/reopen. A minimal durable
locator maps that ID to the canonical repository so M4–M6 services can be
reconstructed after restart; LangGraph remains the workflow-state authority.
Repository content and model/test output render as text only, and the client
does not automatically retry state-changing requests.

### How it was verified

Deterministic API tests cover invalid input, unknown workflows, exact plan and
patch hashes, terminal rejection, final export, safe internal errors, omitted
runtime details, and read-only GET behavior. Frontend tests cover forms,
evidence/plan/diff/test/critic/final/completion rendering, XSS-safe text,
status distinctions, exact-hash submissions, terminal action removal, refresh,
and pending-button guards.

### Metrics / evidence

The complete backend suite passed 275/275 in 5.18 seconds. The frontend passed
18/18 tests; TypeScript and the Vite 7.3.6 production build also succeeded.
These are functional verification results, not performance or repair-quality
benchmarks.

### Remaining limitations

Requests that invoke local inference/tests remain synchronous and may take
minutes. There is no editor, terminal, arbitrary command/file browser, model
switcher, Git operation, PR creation, background job system, or WebSocket
stream. M8 evaluation remains separate. A real functional smoke was not run
because Ollama and Docker executables were unavailable on this session's PATH.

### Public-content angle

None queued. The user explicitly requested no public post.
