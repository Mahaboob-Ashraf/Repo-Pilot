# RepoPilot Architecture Decisions

Decisions are recorded before implementation claims. Status may be Proposed, Accepted, Superseded, or Rejected.

## ADR-001 - Local-first, zero-cost default

**Status:** Accepted from source specification

**Decision:** The default path uses local Ollama, local SQLite/Chroma, and local Docker without a paid API key.

**Why:** The project must be reproducible at zero spend and demonstrate ownership of inference, retrieval, and evaluation.

**Alternatives considered:** Paid hosted LLM/vector services; cloud-only deployment.

**Tradeoffs:** Local models may be weaker and hardware-constrained; setup is heavier but behavior and cost are inspectable.

**Testing/benchmark impact:** Record local hardware and model configuration. Optional providers cannot define the core proof path.

## ADR-002 - AST-aware hybrid retrieval

**Status:** Accepted from source specification

**Decision:** For Python repositories, use tree-sitter semantic chunks, SQLite
FTS5 BM25, Chroma vectors, RRF, and one-hop import, parent-child, and
directly-related-test expansion.

**Why:** Exact identifiers and stack traces favor lexical search; issue semantics favor embeddings; code relationships require structural context.

**Alternatives considered:** Fixed-size chunks; vector-only; BM25-only; opaque managed search.

**Tradeoffs:** More indexing complexity and metadata, offset by explainable provenance and an ablation-friendly design.

**Testing/benchmark impact:** Compare fixed-size, AST, and AST-plus-graph variants on identical issues and token budgets.

## ADR-003 - Stateful graph with persisted human interrupts

**Status:** Accepted from source specification

**Decision:** In M3+, use LangGraph as the state-machine layer for one bounded
repair workflow. It owns shared run state, stage transitions, a conditional
test-failure branch, maximum-one-retry control, pause/resume, and persistence
where needed. V1 has exactly two human checkpoints: approval of the
evidence-grounded plan and file scope before patching, then approval of the
final diff before patch export.

**Why:** Coding runs are long-lived, failure-prone, and unsafe without resumable state and auditable control boundaries.

Planner, retriever, context packer, patcher, test runner, and critic are graph
nodes/stages, not an autonomous multi-agent swarm. LangChain is used selectively
inside LLM-backed nodes for prompt templates, message composition, structured
output parsing/schemas, and useful Runnable composition. Custom chunking,
BM25, Chroma retrieval, RRF, structural expansion, and context packing remain
RepoPilot-owned boundaries. LangGraph and LangChain entered the runtime in M3.

**Alternatives considered:** One-shot prompt; free-running loop; in-memory-only
orchestration; multi-agent swarm; five separate approval checkpoints; replacing
custom retrieval with generic LangChain wrappers.

**Tradeoffs:** Persistence and resumption are more complex, but behavior becomes
bounded, reviewable, and debuggable. Selective framework use adds dependencies
only where their concrete orchestration/composition value justifies them.

**Testing/benchmark impact:** Test both interrupt/resume points, immutable
payload hashes, rejections, restarts, the conditional failure branch, and the
hard two-attempt limit.

## ADR-004 - Docker-only execution for ingested repository tests

**Status:** Accepted from source specification

**Decision:** Test commands for ingested repositories run in isolated Docker containers with networking disabled by default and explicit resource/time limits.

**Why:** Repository code and commands are untrusted.

**Alternatives considered:** Host subprocesses; language virtual environments; remote sandboxes.

**Tradeoffs:** Docker startup and dependency setup add latency and platform constraints, but materially reduce host risk.

**Testing/benchmark impact:** Prove timeout, network isolation, resource controls, log capture, cleanup, and image identity.

## ADR-005 - Separate semantic chunk identity from source-content identity

**Status:** Accepted

**Decision:** M1 code chunks use deterministic, human-readable IDs in the form
`{repository-relative path}::{chunk type}::{qualified symbol}::{start
line}-{end line}`. They separately store the lowercase SHA-256 digest of the
exact UTF-8 source text. Class chunks and their method chunks are both retained,
even though their source ranges overlap.

**Why:** Paths, construct types, qualified symbols, and ranges provide stable,
inspectable provenance for citations and later indexes. Absolute paths would
make identity machine-specific, while random UUIDs would prevent reproducible
rebuilds and complicate evaluation comparisons. A separate content digest
detects implementation changes that preserve semantic location and therefore
do not change the chunk ID.

**Alternatives considered:** Random UUIDs; absolute-path IDs; content hashes as
the sole chunk identity; suppressing method chunks when a class chunk already
contains their text.

**Tradeoffs:** Identical relative constructs in different repositories require
a future stable repository namespace when persisted together. Line movement
changes semantic IDs, and class/method overlap can consume retrieval context.
Keeping both representations preserves useful context until retrieval and
context-packing measurements justify deduplication.

**Testing/benchmark impact:** Repeated builds must produce identical IDs and
hashes; source-only changes must alter the hash; IDs must not expose absolute
paths. Later indexing and retrieval evaluation must measure duplicate-result
and token-budget effects from class/method overlap.

## ADR-006 - Reject malformed Python during repository chunking

**Status:** Accepted

**Decision:** Python parsing rejects a file whenever Tree-sitter reports an
erroneous tree. The parser raises a typed error containing the
repository-relative file path, first relevant `ERROR` or missing node kind, and
its 1-based source range. Repository chunking is fail-fast and returns no
partial result when any supported Python file is malformed.

**Why:** Silently extracting constructs from an uncertain syntax tree would
make the repository summary and later index look complete when their provenance
is not trustworthy. A single explicit failure is the smallest correct M1
policy and keeps malformed input distinguishable from a valid repository that
simply contains no supported constructs.

**Alternatives considered:** Index all recoverable constructs silently; return
partial chunks plus warnings; skip malformed files and continue.

**Tradeoffs:** One malformed Python file prevents chunking otherwise valid
files. Partial recovery could improve coverage for real repositories, but it
requires result-level diagnostics and evaluation that are outside M1.

**Testing/benchmark impact:** Parser and full-pipeline tests must prove malformed
input raises the typed error with relative provenance. Future partial-indexing
work must make incompleteness explicit and compare coverage against fail-fast
behavior before superseding this decision.

## ADR-007 - Explicit local embedding boundary and precomputed Chroma vectors

**Status:** Accepted

**Decision:** Embeddings use a provider boundary separate from generation. The
M2.2 baseline uses local Ollama `embeddinggemma`, embeds exact chunk source text
in deterministic batches, and supplies precomputed document/query vectors to a
Chroma collection with no Chroma embedding function. The collection uses
cosine distance and records provider, model, document-format, and distance
identity. Query results carry raw distance/rank separately from canonical
`CodeChunk` data.

**Why:** Generation and embedding models have different contracts and should
not be interchangeable. Explicit vector generation prevents Chroma from
silently loading a default model, preserves the zero-cost local path, and makes
the same-model indexing/query invariant auditable. Exact source text is the
smallest reproducible semantic document and avoids mixing repository data with
instructions or machine-specific paths.

**Alternatives considered:** Chroma's default embedding function;
sentence-transformers; cloud embedding APIs; using the Gemma generation model
for embeddings; embedding arbitrary metadata/prompts with source; treating
cosine distance as mutable chunk state.

**Tradeoffs:** Rebuilds recompute every vector, one model identity is bound to a
collection, and source-only documents may omit useful symbol/path signals.
Chroma adds a substantial transitive dependency set. These are acceptable for
the bounded baseline; incremental indexing and alternate document formats need
separate evaluation.

**Testing/benchmark impact:** Mock Ollama responses validate the HTTP contract;
deterministic fake embeddings validate Chroma behavior offline. Evaluation must
record model/digest, dimension, document format, distance space, Chroma version,
and corpus, and must compare ranks rather than directly mixing cosine distance
with BM25 scores.

## ADR-008 - Scoped V1 boundary

**Status:** Accepted

**Decision:** V1 is a local-first, human-controlled coding agent for Python
repositories only. It uses one fixed Ollama generation model for primary
evaluation, two human checkpoints, approved-file-only edits, at most two repair
attempts total, restricted Docker tests, structured traces, and human-approved
patch export. It does not create or merge pull requests.

**Why:** A narrower end-to-end system makes the safety controls, retrieval
quality, workflow state, and evaluation evidence implementable and defensible.
It preserves the project's differentiating code-retrieval and human-control
work without turning completion into a broad platform or infrastructure effort.

**Alternatives considered:** Multi-language parsing; vLLM and a model-size
matrix; many-agent showcase; five approval checkpoints; full
Prometheus/Grafana/OpenTelemetry stack; RAGAS; full IDE; autonomous PR flow;
cloud deployment as a completion gate.

**Tradeoffs:** V1 demonstrates less breadth and does not optimize across model
tiers or deployment environments. In return, each promised capability has a
clear milestone, bounded proof obligation, and zero-cost local default path.

**Testing/benchmark impact:** Evidence and documentation must use the Scoped V1
milestones. Deferred capabilities must not appear as current requirements or
implemented claims.

## ADR-009 - Rank-only RRF, explicit dense degradation, and frozen evaluation

**Status:** Accepted

**Decision:** Hybrid retrieval fetches independently configurable candidate
depths from BM25 and dense retrieval, then scores each chunk as
`sum(1 / (k_rrf + rank))` across lists. Ranks are 1-based, `k_rrf` defaults to
the conventional initial baseline `60`, final ties break by canonical
`chunk_id`, and `top_k` is independent of candidate depth. Raw BM25 scores and
cosine distances remain inspectable metadata and never enter fusion math.

The vector layer translates expected embedding-provider and Chroma count/query
failures into a narrow `VectorRetrievalError`. Hybrid retrieval catches only
that boundary and returns the available BM25 ranking with an explicit
`lexical_only_degraded` mode and useful failure reason. It does not catch
arbitrary programming errors, claim normal hybrid success, or add retries.

Frozen retrieval cases contain a case ID, issue/query text, relative repository
reference, gold file paths, and optional gold symbols. Gold data is passed only
to scoring. The M2B harness independently runs `ast_bm25`, `ast_dense`, and
`ast_hybrid_rrf` and records ranked provenance, file Hit@1/Hit@5, symbol Hit@5
when labels exist, separate file/symbol reciprocal rank, boundary latency, and
degraded status.

**Why:** BM25 and cosine distance have different scales and directions, while
ranks provide a stable explainable fusion boundary. Explicit degradation keeps
the local workflow useful during embedding failure without corrupting evidence.
Frozen cases make evaluation reproducible and prevent labels from improving the
queries they score.

**Alternatives considered:** Normalizing and adding raw scores; a learned
reranker; hiding dense failures; retry infrastructure; leaking gold symbols
into query expansion; introducing fixed-size chunks or structural expansion in
M2B.

**Tradeoffs:** RRF discards score magnitude and the default constant is not
empirically tuned. Small controlled cases validate only implementation and
metrics, not retrieval quality. Dense-only evaluation still surfaces provider
failures rather than silently falling back.

**Testing/benchmark impact:** Unit tests use hand-calculated ranks and
deterministic fake embeddings. Context precision, waste, and token metrics were
deferred to M2C. Controlled fixture outputs are harness-validation evidence,
not benchmark or SWE-bench results.

## ADR-010 - One-hop structural evidence and whole-chunk context budgets

**Status:** Accepted

**Decision:** Build a small in-memory `StructuralIndex` over canonical chunk
IDs using only deterministic current metadata. Supported directed edges are
method-to-parent class, class-to-direct-child method, exact matched local-module
import, and directly-related test backed by a source-module import or exact
source-symbol reference. Expansion traverses only the original hybrid results;
newly added chunks are never seeds.

Direct hybrid results remain first by rank. Structural-only candidates follow
in `parent`, `related_test`, `imported_module`, then `child` priority, with
stable seed/chunk-ID ties. Candidates are deduplicated, all structural causes
are retained, and direct provenance wins when a chunk is both retrieved and
reachable. Structural-only chunks receive no invented retrieval scores.

The immutable `ContextPack` includes complete rendered evidence blocks under a
hard configured budget and propagates retrieval degradation. The default
replaceable counter uses UTF-8 byte length as conservative estimated units, not
exact model tokens. Chunks are never split or silently truncated. Non-fitting
lower-priority chunks are excluded; if the first chunk cannot fit, the pack
returns `oversized_highest_priority` rather than substituting weaker evidence.
Issue and repository source are rendered in explicit untrusted-data regions.

**Why:** One deterministic hop supplies nearby code/tests that rank-only text
retrieval may omit while keeping context growth explainable and bounded. A
single immutable pack makes the future planner input auditable, and whole-chunk
packing preserves exact source provenance.

**Alternatives considered:** Recursive or transitive graph traversal; a graph
database; semantic test linking; a full Python import resolver; score-based
structural reranking; source truncation or secondary splitting; adding a large
tokenizer dependency; allowing evaluation gold labels into expansion/packing.

**Tradeoffs:** Exact import matching misses aliases, relative imports, and more
complex package resolution. Related-test rules may add every test chunk in a
module that explicitly imports the source module. UTF-8 byte estimates can
under-utilize a model's real context window, and whole oversized chunks produce
an explicit empty/error-status pack instead of partial code. These constraints
favor safety and determinism over recall and density in the M2C baseline.

**Testing/benchmark impact:** Offline fixtures prove each edge type, exactly
one hop, deterministic ordering, deduplication, hard budgets, no truncation,
degradation propagation, evidence delimiters, and post-pack gold isolation.
Context coverage, file/symbol precision, token waste, and budget utilization
are now valid harness metrics. Controlled fixture and toy smoke observations
remain non-benchmark evidence.

## ADR-011 - Evidence-grounded plans and hash-bound LangGraph approval

**Status:** Accepted

**Decision:** M3 represents repair plans as strict frozen Pydantic models. Each
ordered repair step names affected repository-relative files and cites one or
more ContextPack chunk IDs. After LangChain's `PromptTemplate` renders the
authoritative workflow/trust boundary and `PydanticOutputParser` parses model
JSON, a first-party validator rejects citations and paths absent from the exact
ContextPack. The existing async RepoPilot `InferenceProvider` remains the only
generation boundary and no automatic planner retry is added.

A validated plan is serialized as canonical UTF-8 JSON with sorted object keys
and compact separators, then bound to approval by a lowercase SHA-256 digest.
One LangGraph `StateGraph` owns planner, real `interrupt()`, approve, reject,
and terminal transitions. JSON-friendly checkpoint state contains the rendered
context snapshot and evidence provenance, retrieval degradation, plan/hash,
decision, reviewer comment, status, and approved file scope; providers and
checkpointers remain outside state. Approval freezes the validated proposed
files for M4, while rejection creates no approved scope. Both paths terminate
without editing the repository.

Tests use `InMemorySaver`. The local durable path uses `AsyncSqliteSaver` from
the separately pinned `langgraph-checkpoint-sqlite` package because RepoPilot's
provider and graph invocation are async. A caller-supplied stable `thread_id`
selects the checkpoint, and the service validates the decision object and plan
hash before consuming the interrupt. SQLite checkpoint paths must be absolute
and outside the source repository.

**Why:** Evidence membership prevents a model from expanding edit authority,
and the plan hash prevents approval of one proposal from authorizing a changed
proposal. A narrow service keeps future API/UI callers independent of raw
LangGraph invocation details while durable local checkpoints preserve the
zero-cost, restart-safe first human control point.

**Alternatives considered:** Free-form plans; silent citation repair; approval
by an unbound string; in-memory-only product state; storing provider objects in
graph state; LangChain agents or retriever/vector-store wrappers; PostgreSQL or
cloud persistence.

**Tradeoffs:** SQLite is intentionally a lightweight local persistence choice,
not a horizontally scaled service. A stale decision must be resubmitted with
the current hash. Plans can mention only files represented by the bounded pack,
so insufficient retrieval evidence stops planning instead of broadening scope.

**Testing/benchmark impact:** Offline fakes prove prompt boundaries, structured
parsing, grounding failures, deterministic hashes, interrupt/pause behavior,
thread isolation, approve/reject outcomes, no planner rerun on resume, and no
repository mutation. A second service instance must resume a paused thread from
the same isolated SQLite database. These are functional safety tests, not model
quality benchmarks.

## ADR-012 - Exact structured edits in durable isolated workspaces

**Status:** Accepted

**Decision:** M4 accepts only strict frozen `PatchProposal` objects containing
existing-file exact replacements. LangChain supplies patch prompt templating and
Pydantic parsing, while the existing `InferenceProvider` remains the only model
boundary and receives no filesystem or shell tools. The human-approved plan
hash and frozen file scope are authoritative; the model cannot define or widen
them.

Before generation and again before application, exact approved chunk text and
its SHA-256 fingerprint must still match the canonical repository and isolated
snapshot. The whole proposal is validated against the original workspace text:
paths are normalized and contained, targets are existing UTF-8 regular files,
symlinks and unapproved paths are rejected, citations must exist and include
same-file evidence, old text must occur exactly once inside cited evidence, and
edit ranges must not overlap. Valid ranges apply from the end of each file
toward the beginning only after every edit passes.

Each run uses an opaque workspace ID bound to repository identity, thread ID,
and approved plan hash. The durable snapshot lives under a caller-configured
root outside the canonical repository, excludes VCS/environment/cache/build
directories, copies regular-file bytes, and keeps metadata outside the copied
repository tree. Multi-file writes capture originals and roll back on failure.
RepoPilot—not model output—creates a sorted, repository-relative unified diff;
SHA-256 of its exact UTF-8 representation is the patch hash. A completed patch
record makes replay return the existing artifact, while inconsistent workspace
state fails explicitly.

**Why:** Human approval is meaningful only if later generation cannot expand
scope or reinterpret changed evidence. Exact replacements avoid fuzzy guesses,
an external workspace protects the source repository, and a first-party diff
provides one deterministic artifact for later test and final-approval binding.

**Alternatives considered:** Applying model-authored diffs directly; fuzzy
matching; editing the canonical checkout; Git commits/worktrees as a mandatory
runtime requirement; model-selected scope; partial application; automatically
deleted temporary directories; unrestricted tools; retrying patch generation.

**Tradeoffs:** V1 cannot create, delete, or rename files and rejects legitimate
edits when old text is duplicated or crosses the exact cited chunk boundary.
Filesystem snapshots cost disk space, and process crashes before the completion
record may leave a conflicting workspace that requires explicit recovery rather
than blind replay. Test execution and a second human checkpoint remain later
milestones.

**Testing/benchmark impact:** Offline fakes cover prompt authority, structured
parsing, unsafe paths, scope expansion, stale evidence, exact matching,
ambiguity, overlaps, multi-file all-or-nothing validation, rollback, canonical
diffs/hashes, replay, thread isolation, and graph routing. These are functional
safety checks, not repair-quality or latency benchmark results.

## ADR-013 - Patch-bound Docker pytest through disposable snapshots

**Status:** Accepted

**Decision:** M5 treats Docker as a fixed execution boundary, never as an LLM
tool. The test stage requires a verified `patch_ready` M4 artifact whose plan
hash, patch hash, changed-file scope, trusted patch record, and complete durable
workspace bytes still agree. It copies those bytes into a disposable execution
snapshot and mounts only that snapshot read-only at `/workspace`; neither the
canonical repository nor the durable M4 review workspace is mounted.

RepoPilot owns the Docker executable, image reference, and in-container command.
The only V1 command is `python -m pytest -q -p no:cacheprovider`, optionally
followed by strictly parsed repository-relative `.py` node selectors as literal
argv elements. Process creation always uses explicit argv and `shell=False`.
Model/repository text cannot supply an executable, shell fragment, install
script, image, mount, or Docker option.

The default sandbox disables networking, drops all capabilities, enables
no-new-privileges, uses a non-root UID/GID, sets a read-only container root and
source mount, provides a bounded `/tmp` tmpfs, disables bytecode writes, and
sets wall-clock, memory, CPU, PID, and output limits. The configured image is
inspected locally and Docker runs its resolved image ID with `--pull never`.
No dependency installation or image pull occurs during repair execution.

Immutable `TestRunResult` evidence binds the exact patch/workspace to mode,
validated selectors, image reference/resolved ID, policy, exit code, duration,
bounded stdout/stderr, truncation, and a classified outcome. Pytest assertion
failure is distinct from timeout, Docker/image failure, and pytest
usage/internal errors. A durable result key includes thread, patch, request,
image reference, and policy so identical replay returns completed evidence
without another container run.

**Why:** Executing untrusted repository code on the host or mounting the source
or review workspace would invalidate RepoPilot's safety and review guarantees.
Patch-hash binding makes every test claim refer to one exact review artifact,
while a disposable snapshot prevents pytest or repository code from
contaminating that artifact.

**Alternatives considered:** Host pytest; free-form plan test commands; shell
wrappers; mounting the canonical or durable workspace; writable source mounts;
networked dependency installation; implicit image pulling; treating every
nonzero exit as an assertion failure; rerunning automatically on replay.

**Tradeoffs:** The fixed image supports only repositories compatible with its
preinstalled environment. Missing dependencies or images fail as
infrastructure rather than being installed automatically. Docker availability
is a host prerequisite, and M5 intentionally does not add critic reasoning,
retry, or final approval.

**Testing/benchmark impact:** Automated tests inject fake process and runner
boundaries, assert exact argv/security flags and status mapping, and verify
snapshot cleanup, workspace preservation, integrity rejection, bounded logs,
durable replay, JSON state, and graph routing without requiring Docker. A real
smoke is optional and may run only with an already-running daemon and suitable
already-local image.

## ADR-014 - Advisory grounded critic, acyclic two-attempt control, and exact export

**Status:** Accepted

**Decision:** M6 keeps criticism inside the same bounded LangGraph workflow but
gives it no tools or authority. A strict `CriticAssessment` may diagnose one
genuine attempt-one pytest assertion failure and recommend bounded actions only
for the first human-approved files. Citations must belong to the approved
ContextPack; requests for shell, network, environment, or new file authority
fail closed. LangChain is limited to prompt templating and structured parsing
through the existing `InferenceProvider`.

The graph is acyclic and has distinct initial and retry patch/test nodes.
`MAX_PATCH_ATTEMPTS = 2` is deterministic application policy. Attempt two, when
recommended, receives the unchanged plan/hash/scope/evidence and bounded prior
diff/test/critic data, but starts from a separate snapshot of the same approved
canonical baseline. Passing tests immediately stop generation. Infrastructure,
timeout, malformed-command, critic, patch, or second-test failures never trigger
another model retry.

A second real LangGraph interrupt is reached only for a passing candidate. The
decision must repeat the exact patch hash and remains bound to the original plan
hash, workspace artifact, and successful `TestRunResult`. Rejection exports
nothing. Approval re-verifies those identities and writes only RepoPilot's
existing canonical diff to an external `<patch_hash>.patch`; it never applies
the patch or invokes Git. Identical export replay reuses exact bytes and a
conflict is never overwritten.

**Why:** Advisory diagnosis can improve one failed attempt without allowing the
model to enlarge human authority or form an autonomous loop. Clean-baseline
retry makes each candidate independently reviewable. Exact patch/test binding
makes the second approval meaningful, and export-only completion preserves the
no-commit/no-PR boundary.

**Alternatives considered:** Critic-authored code; dynamic file scope; retrying
infrastructure failures; applying attempt two over attempt one; a cyclic graph
with a counter guard; more than two attempts; model-generated export diffs;
overwriting conflicting artifacts; automatic apply/commit/push/PR creation.

**Tradeoffs:** The conservative critic action filter can reject useful advice
that mentions operational changes. V1 exports only a unified diff and does not
package dependencies or execute a real end-to-end smoke without the already
available Docker runtime/image. Attempt workspaces and durable evidence consume
local disk until a later lifecycle policy is added.

**Testing/benchmark impact:** Offline fake-provider/runner tests cover critic
parsing and grounding, pass/infra routing, clean retry workspaces, the exact
two-attempt ceiling, second interrupt durability, stale hash/workspace rejection,
export identity/conflicts, replay, and thread isolation. These are functional
safety tests, not repair-quality or performance benchmarks.

## ADR-015 - Backend-authoritative review API with read-only refresh

**Status:** Accepted

**Decision:** M7 exposes the existing M3–M6 `PlanReviewService` through four
typed FastAPI operations: create, read, plan decision, and final decision.
Routes do not reproduce graph transitions. Public response models project only
review-relevant evidence, plan/scope, canonical diff, tests, critic history,
decisions, safe failures, and export identity. Provider/checkpointer objects,
workspace implementation identity, Docker policy internals, host environment,
and arbitrary exceptions remain private.

`GET` reads `aget_state` through `PlanReviewService.get_plan_review()` and can
never execute a graph node. The browser retains only a thread ID in the URL and
derives presentation from backend status. It never automatically retries a
state-changing POST. Both decision routes repeat the exact displayed hash and
delegate validation to the existing approval services.

Because patch/test/export composition depends on the canonical repository,
one minimal SQLite locator stores only thread ID to canonical repository path.
All workflow state remains in the durable LangGraph checkpoint; the locator is
not a second workflow state machine.

**Why:** Refresh and backend restart must preserve human review without
replaying expensive or state-changing work. A narrow API prevents the browser
from becoming an authority or receiving internal runtime capabilities.

**Alternatives considered:** Serializing raw graph state; rebuilding approval
checks in routes; browser-owned state transitions; GET that resumes the graph;
automatic POST retry; an in-memory-only thread map; a second full workflow
database; WebSockets/background jobs; editor, terminal, Git, Docker, or model
controls in the review UI.

**Tradeoffs:** Create and approval requests remain synchronous and may stay open
for minutes during local inference/tests. The locator duplicates only the
minimum repository association needed for restart reconstruction. Lifecycle
management for durable local artifacts remains a later concern.

**Testing/benchmark impact:** Offline API tests inject the application boundary
and cover exact hashes, transitions, refresh, safe failures, and serialization.
Frontend tests mock only the typed API client and cover text-safe rendering,
decisions, test classifications, retry display, completion, and pending-state
guards. These are functional UI/API results, not M8 evaluation evidence.

## ADR-016 - Frozen scoring-only labels and non-averaged safety evidence

**Status:** Accepted

**Decision:** M8 keeps synthetic development/smoke fixtures separate from the
frozen `evaluation/fixtures/m8/` set. Gold paths and symbols are loaded only by
evaluation scoring after a production retrieval/structure/ContextPack boundary
returns. The runner accepts no gold-bearing retriever interface and includes no
download operation.

Real dense and hybrid rows require the locked local `embeddinggemma:latest`.
Provider unavailability is a first-class blocked result, never replaced with a
fake vector. The production lexical-only degradation route may be measured
separately, but its label must not imply normal hybrid retrieval.

Safety results are a category scorecard with every frozen scenario retained.
Any failed safety invariant makes the safety/full command non-zero; critical
failures cannot disappear into one average. Prompt-injection claims are limited
to deterministic authority containment, not universal model robustness.

**Why:** Labels entering execution would invalidate retrieval evidence, fake
embeddings would misstate the locked real stack, and one aggregate safety score
could conceal a critical failure.

**Alternatives considered:** Query enrichment from gold labels; silently using
deterministic embeddings for a real run; dropping blocked variants; averaging
all safety cases into one score; treating small synthetic percentages as broad
repository accuracy.

**Tradeoffs:** Dense/hybrid comparisons may remain incomplete on machines
without the local model. The small frozen suite gives controlled regression
evidence rather than statistical generality. Full external repair evidence is
deferred to M9, and measured optimization remains M10.

**Testing/benchmark impact:** Automated tests cover leakage-resistant query
boundaries, deterministic fixture/artifact identity, malformed labels, metric
math, structural accounting, budget exclusions, provider blocking, safe JSON,
and scorecard failure propagation. The completed real M8 run records measured
BM25, `embeddinggemma:latest` dense/hybrid, structure/ContextPack, and all safety
categories without parameter tuning.

## ADR-017 - Pinned minimal external fixtures and non-oracular M9 approvals

**Status:** Accepted

**Decision:** M9 uses a frozen manifest of six controlled-defect cases derived
from full pinned commits of three real permissively licensed Python
repositories. Acquisition copies only recorded minimal license/package/test
paths into an ignored cache, applies one exact evaluation-only mutation, and
verifies source/case fingerprints. Network access exists only in the explicit
materialization mode.

Gold files, symbols, and reverse-replacement repair oracles remain in the
evaluation manifest but are converted to a gold-free `ProductionCaseInput`
before any production service call. Benchmark approval #1 accepts a normally
validated grounded plan and matching payload scope; approval #2 accepts only a
current in-scope patch bound to passing configured tests. Neither approval
function accepts gold data. Post-hoc scoring alone uses the oracle.

The real executor composes existing M1–M6 components and observes their stage
latencies with wrappers. Repair success requires patch production, passing
configured tests, final approval, exact export, unchanged canonical input, and
no authority breach. Missing Docker/Ollama/image/fixture prerequisites remain
infrastructure-blocked and are never converted into fake repair success.

**Why:** Full upstream checkouts contain substantial unrelated material and may
be impractical for a six-case offline V1 benchmark. Minimal pinned selections
preserve real repository structure and upstream tests while making acquisition
licensing, dependency, and fingerprint boundaries explicit. Procedural
approvals exercise the real checkpoints without making a human click every
case and without turning evaluation labels into repair authority.

**Alternatives considered:** Mutable default branches; committing nested Git
repositories; installing repository dependencies on demand; approving by gold
file or diff similarity; bypassing LangGraph with evaluation-only repair logic;
counting retrieval/planning as repair success; tuning M9 configuration.

**Tradeoffs:** All six initial cases are controlled mutations rather than
historical bugs, and minimal fixtures provide less repository breadth than full
checkouts. Real end-to-end evidence remains unavailable when the fixed Docker
prerequisite is missing. A process-level unfamiliar-repository ingestion exit
also shows that later per-case worker isolation is desirable.

**Testing/benchmark impact:** Offline tests prove manifest validation,
contamination boundaries, non-oracular approvals, classifications, aggregate
and latency math, behavioral success without textual gold equality, critical
scope failure propagation, path-free deterministic artifact identity, and the
absence of model/image/tool download operations. Real results must retain
blocked cases and exact model/fixture provenance.

## ADR-018 - Repository-controlled digest-pinned pytest image

**Status:** Accepted

**Decision:** The M5/M9 runtime image is built from
`docker/test-runner/Dockerfile` and tagged
`repopilot-python-test:3.11-pytest9`. The Python 3.11 slim base is pinned by
digest, and pytest plus each runtime dependency is version-pinned. Image build
and any required base-layer acquisition are explicit setup operations requiring
separate user approval. Production repair execution continues to resolve a
local image ID, use `--pull never`, disable networking, and run under all M5
restrictions.

**Why:** A repository-owned definition makes the formerly external M5 image
prerequisite reproducible and auditable without allowing repair-time dependency
installation or mutable image acquisition.

**Alternatives considered:** Installing dependencies from each evaluated
repository; using an unpinned base tag; silently pulling during repair runs;
adding broad benchmark dependencies to the image.

**Tradeoffs:** Updating Python or pytest requires an intentional image rebuild
and recorded digest change. The image supports only repositories whose selected
tests need the standard library and its controlled pytest runtime.

**Testing/benchmark impact:** Task 019B built image
`sha256:72b98eae96d168dcdd898cdad6b3c198de5e2b8a0092ee1b80ea8ad1e3d972c7`
and passed a real smoke at UID/GID 65532 with read-only root/source, tmpfs,
network none, zero capabilities, no-new-privileges, and fixed CPU/memory/PID
limits. No image is pulled or built by automated backend tests.

## ADR-019 - Version benchmark-data repairs and preserve post-run diagnosis

**Status:** Accepted

**Decision:** A frozen M9 fixture is never silently relabeled or overwritten.
The invalid v1 floor case and its result remain intact. Its unambiguous selector
repair is represented by manifest v2 and a new case identity. Because mutation
and selected repository bytes do not change, their fixture SHA-256 may remain
the same; schema version, benchmark ID, case ID, selector, provenance, and full
manifest fingerprint carry the data-repair identity.

Runtime evidence discovered after an observation is stored in a separate,
source-hashed diagnosis artifact. Report regeneration may present that
addendum, but it does not rewrite historical per-case JSON. A runtime-invalid
attempt remains visible while being excluded from repair-quality interpretation.

**Why:** Changing v1 in place would erase the invalid-fixture and incomplete-
schema history. Retrofitting inferred provider fields into old observations
would blur measured data and later diagnosis. Versioning and a separate
addendum preserve both auditability and truthful interpretation.

**Alternatives considered:** Rewrite the v1 selector/result; change only the
selector without a case/version change; retrofit typed errors into the old case
records; discard the failed run; count five Vulkan HTTP failures as planner
quality failures.

**Testing/benchmark impact:** Automated tests load both manifests and assert
the exact v1/v2 identity boundary. The corrected v2 case was separately proven
to fail before repair in the locked Docker sandbox. A clean full v2 run is
scientifically justified but remains a separate operation.

## ADR-020 - Optional native schemas and measured bounded setup

**Status:** Accepted

**Decision:** Structured generation is an optional `InferenceProvider`
capability. Supporting providers send the strict Pydantic JSON Schema natively;
plain providers remain compatible. Native constraints never replace Pydantic,
grounding, scope, evidence, exact-match, or authority validation.

Dense index documents are embedded in ordered batches of 32 with retained
setup timings. Production retrieval returns five fused candidates before the
existing one-hop expansion and fixed-budget pack. These values were selected
on the separate M10 development suite, then evaluated on frozen M8/M9 data.

Freshness validation accepts an exact uniquely matched chunk within its
declared line range so indented method source remains provable. No fuzzy match,
automatic citation mapping, broader edit scope, extra retry, or autonomous Git
operation is permitted.

**Why:** M9-v2 measured structured-output failure as the dominant weakness,
M8 measured context waste, and larger M9 cases timed out during one oversized
embedding request. Calibration supported native schemas, depth five, and
bounded batches; an explicit allowed-ID list was rejected after truncation.

**Testing/benchmark impact:** M8-v2 retained full retrieval/context coverage
and 33/33 safety scenarios while reducing file-token waste. One-shot M9-v3
repaired 1/6 with zero parse failures and no critical safety failure. The two
false stale failures discovered in that run were fixed afterward and were not
retroactively rescored.

## ADR-021 - Optional hosted generation behind the existing provider boundary

**Status:** Accepted; controlled comparison completed

**Decision:** Keep Ollama/Gemma as the default local generation path and add
Gemini only as an explicit optional `InferenceProvider` implementation selected
centrally by `REPOPILOT_GENERATION_PROVIDER=gemini`. The controlled target is
the exact `gemini-3.1-flash-lite` model with no alias, fallback, or Pro
substitution. Embeddings remain local through Ollama/EmbeddingGemma. Planner,
patcher, and critic use provider-native JSON Schema when available, followed by
the same Pydantic and deterministic RepoPilot validators.

The real key is loaded only by the centralized settings layer from the ignored
root `.env`, is excluded from representations, and must not enter checkpoints,
API responses, evaluation artifacts, logs, or documentation. Hosted context is
not described as local/private: issue text, bounded source chunks, approved
plan/patch evidence, and critic test output can leave the machine when their
stages run.

**Why:** A provider-controlled comparison can isolate generation behavior while
holding retrieval, prompts, schemas, scope, Docker policy, approval authority,
retry limits, and export rules constant. Central construction avoids provider
branches in workflow stages and preserves the zero-cost default path.

**Tradeoffs:** Gemini adds network, service/quota, privacy, and variable token/
API-cost considerations. Its latency is not hardware-comparable to CPU-local
Gemma. A provider or quota failure blocks the experiment and is not scored as a
repair-quality failure.

**Testing/benchmark impact:** Offline fakes cover model/config identity, missing
key safety, secret redaction, plain/native-schema mappings, planner/patcher/
critic integration, deterministic rejection, centralized selection, and
embedding independence. The exact-model preflight and unchanged M10 planner/
patcher calibration passed. The one-shot frozen six-case comparison repaired
6/6 with Gemini versus the frozen 1/6 CPU-local Gemma M9-v3 baseline, with no
provider failure or critical safety failure. This small controlled result is
not generalized beyond its six defects and three repositories.

## ADR-022 - Graphite presentation and read-only stage navigation

**Status:** Implemented; browser visual review and controlled UI smoke pending.

**Decision:** Keep the existing workflow client and backend contract unchanged.
The frontend owns theme preference, viewed stage, source selection, and console
presentation only. The server owns workflow transitions, grounding, scope,
hashes, retries, Docker policy, and export. Selecting a stage never requests a
mutation. Evidence source is rendered as text; a native dialog supplies modal
focus containment on narrow screens. A small unified-diff presentation parser
retains the unmodified canonical diff in a raw view. No split editor, new
endpoint, provider selector, or download control is introduced.

**Why:** Review density and navigation can improve independently of repair
authority. Explicit labels and local identity consistency checks make both
checkpoints clearer without replacing backend validation.

**Testing impact:** Frontend tests cover theme persistence/System updates,
read-only navigation, exact citations, drawer focus return, raw diff integrity,
duplicate decisions, stale recovery, and mismatched final evidence. Native
focus trapping and composed responsive visuals still require a connected
browser; unit tests do not prove those properties.
