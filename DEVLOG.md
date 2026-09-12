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
