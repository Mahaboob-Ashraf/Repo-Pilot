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
