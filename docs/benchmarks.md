# RepoPilot Evaluation Plan

M8 has run as a small frozen local controlled evaluation. It is not SWE-bench,
production evidence, external-repository evaluation, or statistically
representative of Python repositories. Earlier Task 011/012 toy cases remain
harness validation only. The canonical artifacts are
`evaluation/results/m8/m8-results.json` and `m8-report.md`.

## Evidence record required for every future measured run

- Date and commit SHA.
- Hardware: CPU, RAM, GPU/VRAM, operating system.
- Frozen dataset name/version, exact cases, labels, and count.
- Fixed generation model, quantization, Ollama version, context window, and
  prompt/template version when generation is involved.
- Embedding model tag/digest/dimension, document format, Chroma version, and
  cosine configuration.
- SQLite version, FTS tokenizer/weights, RRF constant, candidate depth, and
  returned depth.
- Software/container versions.
- Warm-up, run count, aggregation method, and timer boundaries.
- Failures, degraded cases, exclusions, uncertainty, and limitations.

## Implemented M2B retrieval-evaluation harness

### Frozen case schema

Each immutable serializable case contains:

- `case_id`: unique stable identifier;
- `query`: issue/query text passed unchanged to retrieval;
- `repository_ref`: normalized relative POSIX fixture/root reference;
- `relevant_files`: one or more gold repository-relative file paths;
- `relevant_symbols`: one or more gold symbols when known, otherwise `null`.

Gold files and symbols are evaluation-only labels. Retriever adapters accept
only `query` and `top_k`, so labels cannot be added to the query being scored.

### Implemented variants

| Variant | Definition | Status |
|---|---|---|
| `ast_bm25` | Tree-sitter `CodeChunk` + SQLite FTS5/BM25 | Implemented |
| `ast_dense` | Tree-sitter `CodeChunk` + precomputed Chroma cosine vectors | Implemented |
| `ast_hybrid_rrf` | Independent BM25/dense candidates fused by RRF | Implemented |
| `fixed_bm25` | Fixed-size chunk baseline | Deferred; not implemented |
| `hybrid_structure` | RRF, one-hop structure, then bounded ContextPack | Implemented for context evaluation |

### RRF baseline

For each document/chunk `d`:

```text
score(d) = sum over retrieval lists of 1 / (k_rrf + rank(d))
```

Ranks are 1-based. `k_rrf` defaults to `60`, a conventional initial baseline,
not a measured optimum. Each modality supplies up to configurable
`candidate_k`; the fused response independently returns `top_k`. Equal fused
scores break by canonical `chunk_id`.

RRF is rank-only because raw SQLite BM25 scores (smaller/more-negative is
better) and raw Chroma cosine distances (smaller is better) are not calibrated
to a common scale. Those raw values remain attached as diagnostic metadata and
are never normalized or added in the fused score.

If the dense path encounters an expected embedding-provider or Chroma
count/query failure, the vector layer exposes `VectorRetrievalError` and
`ast_hybrid_rrf` continues with unchanged BM25 candidates. It records
`lexical_only_degraded` plus a degradation reason and must not report normal
hybrid mode. This fallback is not a retry mechanism. Unexpected programming
errors still propagate, and the standalone `ast_dense` variant surfaces its
own failure.

### Implemented metrics

- **Relevant-file Hit@1:** `1` when a returned chunk from any gold file is at
  rank 1; otherwise `0`.
- **Relevant-file Hit@5:** `1` when a returned chunk from any gold file is at
  rank 1 through 5 inclusive; otherwise `0`.
- **Relevant-symbol Hit@5:** when symbol gold exists, `1` when a returned
  chunk's symbol or qualified symbol matches any gold symbol at rank 1 through
  5; otherwise `0`. When no symbol gold exists the value is `null` and the case
  is excluded from symbol aggregate denominators.
- **File reciprocal rank:** reciprocal of the first rank whose chunk path is a
  gold file; `0` when no gold file is retrieved. The aggregate mean is explicit
  file-level MRR.
- **Symbol reciprocal rank:** reciprocal of the first rank whose symbol or
  qualified symbol matches symbol gold; `0` when labeled but missed, and
  `null` when no symbol gold exists. The aggregate mean excludes unlabeled
  cases and is explicit symbol-level MRR.
- **Retrieval latency:** wall-clock duration around the variant adapter at the
  harness boundary, recorded per case. Aggregate p50/p95 use deterministic
  nearest-rank percentiles only with at least five measured cases; smaller
  groups report `null` rather than overstating percentiles.

Per-case output also records case/variant, ranked chunk IDs and provenance,
gold labels, degradation status, and retrieval mode. Result and aggregate
objects expose JSON-friendly dictionaries suitable for later JSON/CSV writers.

### Controlled harness-validation set

`backend/tests/fixtures/retrieval_cases.json` contains four cases against the
canonical three-chunk discount repository:

1. exact `apply_discount` identifier;
2. semantic percentage-reduction paraphrase;
3. exact zero-percent test identifier;
4. twenty-percent related-test phrasing used to exercise hybrid behavior.

Offline tests use deterministic, explicitly fake embeddings. Separate
hand-ranked tests prove candidates that occur in both lists, BM25 only, and
dense only. The controlled zero-percent case also deliberately gives BM25 and
the fake dense retriever different depth-one candidates, proving lexical-only
and vector-only membership in an end-to-end hybrid harness run. These cases
prove schema, isolation, fusion, metric, and output behavior; their hit rates
and latencies must not be presented as benchmark results.

## Existing lexical and dense functional evidence

The SQLite baseline indexes semantic chunk source, symbol, qualified symbol,
path, type, and imports with safely quoted OR-token queries and fixed BM25
weights. Toy searches validate implementation and provenance, not quality.

The Chroma baseline stores exact-source precomputed local embeddings with no
default Chroma embedding function and cosine distance. Automated tests use a
deterministic fake. A real `embeddinggemma` smoke observed a 768-dimensional
vector and successful three-chunk indexing/querying; that single toy run is
functional smoke evidence, not a latency or retrieval benchmark.

## Implemented M2C context evaluation

M2C adds a separate `hybrid_structure` path: query-only hybrid retrieval,
exactly one structural hop, fixed-budget packing, then evaluation against gold
labels. The retriever, expander, and packer never receive gold files or
symbols. Per-case context records preserve included chunk order, canonical
provenance, origin, counted item cost, pack/degradation status, total cost,
configured budget, and pipeline-boundary wall-clock latency.

- **Relevant-file context coverage:** `1` when at least one included chunk path
  matches any gold file; otherwise `0`.
- **Relevant-symbol context coverage:** when symbol labels exist, `1` when an
  included chunk symbol or qualified symbol matches; otherwise `0`. It is
  `null` when symbol ground truth is absent.
- **File context chunk precision:** included chunks whose paths match gold
  files divided by all included chunks. An empty pack reports `null`.
- **Symbol context chunk precision:** included chunks whose symbol or qualified
  symbol matches symbol gold divided by all included chunks. It is `null` for
  absent symbol labels or an empty pack.
- **File context token waste:** counted evidence-item cost belonging to chunks
  outside gold files divided by total included evidence-item cost. It is
  `null` when the included item-cost denominator is zero.
- **Symbol context token waste:** the corresponding nonmatching-symbol ratio;
  it is also `null` without symbol labels or a nonzero denominator.
- **Budget utilization:** complete rendered pack cost, including issue/evidence
  framing, divided by the configured hard budget.

Token waste is label-relative accounting, not a universal claim that
nonmatching context is useless. Current production counts use the documented
UTF-8-byte estimator and are estimated units, not exact Gemma tokens. Exact
deterministic fake counters validate metric and budget math in automated tests.

`backend/tests/fixtures/structure_repo/` and `structure_cases.json` validate
parent/child, local-import, directly-related-test, third-party exclusion,
one-hop, deduplication, budget exclusion, and gold-isolation behavior. These
controlled fixtures and the canonical toy functional smoke are harness
validation only. No aggregate result from them is a public benchmark claim.

## M3 planner/approval functional evidence

Offline tests use a deterministic fake `InferenceProvider`; they do not invoke
Ollama and do not measure planning quality. They verify prompt trust boundaries,
strict Pydantic parsing, ContextPack-only citations and file paths, canonical
plan hashes, a real LangGraph interrupt, hash-bound approve/reject transitions,
thread isolation, no planner rerun on resume, and no repository mutation.

Persistence tests use isolated temporary SQLite databases. One test closes the
first workflow/service and reconstructs a second over the same database, then
resumes the paused thread with its original plan hash. This proves local
checkpoint durability and thread semantics only; it is not a latency,
throughput, scale, or reliability benchmark.

One later real local smoke used the canonical toy issue and ContextPack with
`gemma4:e4b-it-qat`. Retrieval completed normally, but the single 51.015-second
generation call surfaced `PlannerInferenceError` before model output could be
parsed. No retry occurred. This failed functional smoke is not a planning
latency or quality benchmark.

The one permitted diagnostic rerun took 52.784 seconds and again stopped before
model output. Bounded diagnostics identified an Ollama HTTP 500, and only newly
appended local server-log bytes identified the underlying Vulkan device loss.
This single failed request is environment/runtime diagnostic evidence, not a
generation-latency benchmark.

## M4 patch functional evidence

Offline M4 tests use deterministic fake providers and do not measure model
quality or runtime performance. They validate approved-scope authority,
evidence freshness, all-or-nothing exact replacements, rollback, workspace
isolation, deterministic diff/hash identity, LangGraph routing, and replay.

One later CPU-only functional smoke used the canonical discount issue,
`gemma4:e4b-it-qat`, and the normal 1,805/2,000-unit ContextPack. `ollama ps`
reported `100% CPU`. Exactly one planner generation (183.976 seconds) and one
patcher generation (161.725 seconds) ran. The exact in-run plan/hash was
approved through LangGraph, the isolated workspace reached `patch_ready`, and
the canonical repository stayed byte-identical. No test execution or retry ran.
These single-run observations are functional smoke evidence, not latency,
throughput, quality, or comparative benchmark results.

## M5 sandbox functional evidence

The 42 focused M5 tests use deterministic process and runner fakes. They prove
fixed argv construction, selector rejection, sandbox flags, status mapping,
bounded logs, M4 integrity checks, disposable snapshot cleanup, durable
workspace preservation, replay identity, and LangGraph routing. They do not
measure Docker startup, pytest runtime, resource isolation strength, repair
quality, or host performance.

The optional real Docker smoke did not run. Docker client 29.7.2 was installed,
but the `desktop-linux` daemon endpoint was unavailable, so local image
inventory and the configured image could not be verified. This is environment
preflight evidence and a functional-smoke blocker, not a benchmark result.

## Later scoped evaluation

## M8 frozen local retrieval and safety evaluation

### Setup and provenance

- Frozen set: `m8-frozen-local-v1`, 10 issues across four synthetic local
  Python repositories.
- Fixture fingerprint:
  `0dccc964a8da7a4e0a0988116e54d8e3b2f4d3354a05d35763b39a4c28ec9e7b`.
- Source commit at measurement: `2fe14b4a0f5634b8a0ec187d372736cc89eeb2c8`
  plus the uncommitted Task 018 implementation under evaluation.
- Current configuration: RRF `k=60`, candidate depth `20`, returned depth `10`,
  ContextPack budget `16,384` UTF-8-byte estimated units.
- Locked dense model: `embeddinggemma:latest`; no generation model was used.
  The measured local model digest was
  `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.

Gold paths and symbols are scoring-only values. The retriever and ContextPack
boundaries receive query text plus normal configuration, never labels. Fixture
and artifact identities exclude timestamps and machine paths. Query latency is
separate from repository chunking and indexing timings in JSON.

### Direct retrieval results

| Variant | Status | File Hit@1 | File Hit@5 | File MRR | Symbol Hit@1 | Symbol Hit@5 | Symbol MRR | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ast_bm25` | measured | 0.90 | 1.00 | 0.95 | 1.00 | 1.00 | 1.00 | 0.1807 | 0.4323 |
| `ast_dense` | measured | 0.90 | 1.00 | 0.95 | 0.90 | 1.00 | 0.95 | 135.6953 | 221.1889 |
| `ast_hybrid_rrf` | measured | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 136.7950 | 216.8195 |

The one BM25 Hit@1 miss was the deliberately ambiguous same-name `normalize`
case: the user-name symbol ranked before the gold product file, which appeared
at rank two. Symbol Hit@1 remains 1.00 there because the label is necessarily
ambiguous at the unqualified-symbol level; file metrics expose the miss. Dense
retrieval's one Hit@1 miss was the cross-module email-helper case, where the
related test ranked first and the labeled helper ranked second. Hybrid RRF put
the labeled file and symbol first in all 10 cases.

### Structural expansion and ContextPack

The real hybrid one-hop run added no chunks in all 10 cases: zero cases were
helped, zero received only non-gold additions, and all 10 were unchanged. Mean
additions and estimated source cost were therefore both zero. At returned depth
10, the direct candidate set already contained all chunks selected by the
current one-hop policy in these small repositories, so this run provides no
evidence that structure helped or hurt.

Final bounded ContextPacks covered every labeled gold file and symbol. Mean file
and symbol chunk precision were 0.3750 and 0.2988; mean file and symbol token
waste were 0.6195 and 0.6979. Mean budget utilization was 0.2012, no ordinary
case excluded relevant evidence, and all 10 packs had `complete` status.

The current fixed 16,384-unit policy was also exercised independently: the
all-fit pack used 1,342 units; the useful-evidence competition pack used 14,849
units, retained 0.50 gold coverage, and excluded one relevant candidate; the
near-boundary highest-priority item fit at 15,527 units; and the oversized-first
case returned `oversized_highest_priority`, 0 coverage, and no lower-priority
substitution. These are policy measurements, not tuning inputs.

### Safety scorecard

| Category | Scenarios | Passed | Failed |
|---|---:|---:|---:|
| Scope authority | 5 | 5 | 0 |
| Path isolation | 4 | 4 | 0 |
| Stale-state binding | 5 | 5 | 0 |
| Prompt-injection authority | 4 | 4 | 0 |
| Workspace integrity | 4 | 4 | 0 |
| Test execution | 4 | 4 | 0 |
| Retry bound | 3 | 3 | 0 |
| Final approval/export | 4 | 4 | 0 |

The suite uses deterministic malicious proposals, stale decisions, injected
faults, and real RepoPilot validators/workspaces/export boundaries where
authority is exercised. Its prompt-injection result means untrusted text cannot
grant deterministic authority; it does not prove that an LLM can never be
influenced. A failed safety row is never averaged away and makes the command
return non-zero.

### Limitations and M9 handoff

This dataset is too small and synthetic for broad accuracy claims. The direct
top-10 sets leave structural expansion with no observable effect, and the final
packs retain all gold evidence at the cost of substantial non-gold content.
The separate budget competition case still excludes useful evidence. M9 must
freeze external repositories/tasks and measure complete repair success through
both human checkpoints and the existing two-attempt limit. Optimization remains
M10 work.

## M6 bounded-workflow functional evidence

M6 automated tests use deterministic fake inference providers and fake test
runners. They validate strict critic parsing/grounding, eligible-failure-only
routing, a hard two-attempt maximum, clean-baseline retry workspaces, final
hash/test-bound interrupt persistence, exact export, and replay isolation. They
do not measure critic quality, repair success rate, generation latency, Docker
runtime, throughput, or production reliability.

On 2026-09-12 the focused M6 set passed 32/32 and the complete backend suite
passed 266/266. Those counts are regression evidence only, not benchmark
results.

The optional real critic generation was not run: the automated acceptance path
was complete, while CPU-only `gemma4:e4b-it-qat` calls previously required
minutes and the task explicitly allowed skipping a materially delaying smoke.
A complete real M6 end-to-end smoke remains blocked by the unavailable local
Docker daemon/image prerequisite recorded under M5. This is a functional-smoke
blocker, not benchmark evidence.

## Later scoped evaluation

M8 will freeze a meaningful retrieval and safety case set before reporting
comparative metrics. M9 will evaluate a feasible frozen external task set and
complete-system behavior under the same two-checkpoint, two-attempt workflow.
No selected subset may be described as equivalent to a published full split.

V1 does not require a model-size benchmark matrix, vLLM, RAGAS, rerankers,
HyDE, query rewriting, full observability deployment, or cloud deployment.
Measured optimization belongs to M10 and must follow recorded evidence.

## M9 frozen external/system evaluation

### Frozen set and contamination boundary

`m9-external-controlled-v1` contains six external-repository controlled-defect
cases across three real public repositories: more-itertools at
`9ed3dbb0ae527230cd156d91d0af305478558fba` (MIT), toolz at
`568c2b8393973cd172a466546c9d95779c452438` (BSD-3-Clause), and boltons at
`961dcff3f42e73b245aef65e377fe82763b257bb` (BSD-3-Clause). There are no
historical-bug cases. Minimal selected paths retain the upstream license,
relevant package code, and upstream tests. Both base selections and each
mutated case have frozen SHA-256 content fingerprints.

The checked-in manifest owns acquisition provenance, controlled mutations, and
the scoring-only repair oracle. A separate `ProductionCaseInput` is the only
case object accepted by execution. It contains issue text, fixture root, and
fixed test selectors but no mutation, gold file, gold symbol, or gold repair.
Retriever, ContextPack, planner, patcher, critic, and approval policies never
accept the oracle. Post-hoc scoring alone compares retrieval/context and patch
scope against gold.

Approval #1 accepts a normal grounded `awaiting_approval` artifact only when
its plan hash, payload scope, nonempty proposed files, and evidence membership
agree. Approval #2 accepts only a normal `awaiting_final_approval` artifact
whose current patch hash equals passing test evidence and whose changed files
remain inside approved scope. Neither function accepts a benchmark case or
gold labels.

### Metrics and repair definition

Repair success requires all of: a produced patch, configured Docker tests
passing for that exact patch, final approval completed, exact patch export,
unchanged canonical fixture, no scope violation, and export occurring only
after final approval. Retrieval-only or planning-only results cannot count.
Per-case output retains failure stage, attempt classification/history, changed
versus gold files, extra/missing gold files, diagnostic exact-oracle match,
behavioral test success, approved/actual scope, hash/validation failures,
canonical mutation, and per-stage timings. Tests are primary; textual equality
with the oracle is not required.

Post-hoc retrieval metrics are gold-file Hit@1/Hit@5, file MRR, ContextPack gold
file coverage, and ContextPack gold-symbol coverage. Aggregate repair rates use
attempted repairs as their denominator; infrastructure-blocked cases remain a
separate count. Median latency is emitted when measured, and p95 requires at
least five values.

### Initial blocked run and Task 019B real run on 2026-09-13

The explicit materializer and independent fixture checker verified all three
pinned source selections and all six controlled-defect fixtures. Ollama HTTP
was reachable with `gemma4:e4b-it-qat` digest
`ee665637121887cf3befff38abbb1be4ee117c7db867d97a67e29049ecd7e15f`
and `embeddinggemma:latest` digest
`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`.
No model was loaded at the earlier `api/ps` check.

The initial Task 019 run could not reach the Docker daemon and honestly recorded
six infrastructure blocks. Task 019B later built the repository-controlled,
digest-pinned `repopilot-python-test:3.11-pytest9` image and verified it under
the complete M5 restriction policy. That historical block remains documented;
the canonical artifact now contains the subsequent real run.

Subprocess-isolated file diagnostics localized the earlier access violation to
large more-itertools and toolz syntax trees. Temporary Tree-sitter `Point`
wrapper reads used for line accounting corrupted native state on Windows.
Deriving identical 1-based ranges from stable byte offsets fixed the correctness
bug without changing chunk selection or retrieval. All six cases then ingested:
more-itertools produced 474 chunks from 4 Python files, toolz 357 from 31, and
boltons 38 from 3.

Five selectors produced genuine assertion failures before repair. The frozen
`boltons-floor-upper-choice` selector passed because it compares the same
mutated behavior over sorted and unsorted inputs; that case is retained as
`benchmark_fixture_invalid` and never entered the LLM workflow.

The single frozen run attempted the other five cases. Four larger cases reached
the normal lexical-only fallback after the unchanged 60-second dense setup
timeout; boltons completed hybrid retrieval. Post-hoc gold-file Hit@1/Hit@5/MRR
was 0.80/1.00/0.90. Gold-file and gold-symbol ContextPack coverage were both
1.00. Every valid case then failed at the planner boundary, before approval #1,
patching, repair tests, critic/retry, final approval, or export. Repair success
was 0/5, attempt-1 success 0/5, retries 0/5, terminal failures 5/5, and
infrastructure failures 0. The initial observation schema did not retain the
typed planner error record; this evidence gap was fixed for subsequent runs,
but frozen cases were not rerun.

Median/p95 milliseconds across the five attempts were: indexing 83.9319/
89.4424, embedding setup 60029.0263/60101.6357, retrieval 1.7695/143.7428,
planner generation 54092.1377/54936.6069, and total workflow 114240.2928/
115469.6670. Patch, repair-test, critic, retry, and export latency were not
measured because planning never completed. Canonical fixtures remained
unchanged and no critical authority/scope/hash violation was observed.

Canonical artifacts are `evaluation/results/m9/m9-results.json` and
`m9-report.md`; supporting ingestion and pre-repair records are adjacent. This
six-case controlled set is not SWE-bench, does not contain historical bug
evidence, and provides no production-scale accuracy claim.

### Task 019C post-run diagnosis and v2 data repair

The preceding v1 counts are preserved as historical output, but their repair-
quality interpretation is superseded. The retained Ollama server log records
five consecutive M9 generation calls at 16:49–16:56; every call was preceded
by `ggml_vulkan: device lost on Vulkan0` and ended HTTP 500. Prompt truncation
to 2,051 tokens was also logged on each call. The old observation schema lost
the provider fields, but the independent runtime record makes all five attempts
infrastructure-invalid rather than five model repair failures. Retrieval and
ContextPack observations remain measured; 0/5 is not valid repair-quality
evidence.

The permitted representative diagnostic used `boltons-ceil-exact-option`.
Hybrid retrieval produced a partial-budget ContextPack containing 17 chunks at
16,247/16,384 estimated units. Its first and only initial generation took
50,629.2955 ms and failed `PlannerInferenceError` /
`InferenceResponseError` / `response_error` / `Ollama returned HTTP 500`;
the log again showed Vulkan device loss. The one justified confirmation used
the same frozen path and took 219,060.6776 ms. Its output parsed as a
`RepairPlan` but grounding stopped it as `PlanValidationError` with bounded
message `repair step 1 cites an unknown chunk: N/A`. No approval, patch, or
retry ran. Raw output was not retained because retention is limited to
structured-output parse failures. This is one planner-grounding observation,
not a replacement five-case benchmark.

M9 v1 and its invalid `boltons-floor-upper-choice` result remain unchanged.
M9 v2 (`m9-external-controlled-v2`, manifest fingerprint
`e08a819fbdc6dd3b8bd164a1b27fee63f495f55d0d350117a2b60556fe2e973b`)
replaces it with `boltons-floor-exact-option` and selector
`tests/test_mathutils.py::test_floor_basic`. The controlled mutation and
fixture bytes are unchanged, so the case fingerprint correctly remains
`c1d17a8368d5db8878f302ed70cb665e9f6fa8d84f0898908f60694195d6590a`.
The corrected selector failed before repair with exit code 1 and
`pytest_assertion_failure` in the locked M5 Docker image; the fixture remained
unchanged. This is benchmark-data repair, not RepoPilot tuning, and no gold
data entered the workflow.

A full clean M9 v2 rerun is scientifically justified because the original five
attempts were runtime-invalid. It was not performed in Task 019C. Processor
placement must be recorded and the known Vulkan failure condition avoided
before that separately authorized run; no prompt, retrieval, budget, model, or
retry tuning is justified by this diagnosis.

### Task 019D final clean M9 v2 measurement

The final `m9-external-controlled-v2` run used manifest fingerprint
`e08a819fbdc6dd3b8bd164a1b27fee63f495f55d0d350117a2b60556fe2e973b`.
All six frozen selectors failed before repair in Docker image
`sha256:72b98eae96d168dcdd898cdad6b3c198de5e2b8a0092ee1b80ea8ad1e3d972c7`,
and all canonical fixtures remained unchanged. Ollama 0.34.0 repeatedly
reported `size_vram=0` for both locked models during the run. The known Vulkan
path therefore did not participate. The generation timeout was 600 seconds;
the existing 60-second embedding setup timeout remained unchanged.

Each case ran exactly once through the production workflow with no benchmark-
level retry, manual output repair, or RepoPilot tuning. Six cases were valid and
attempted; none completed repair. Planner outcomes were one valid grounded
plan, three `PlannerOutputError` parse failures, two `PlanValidationError`
grounding failures, and zero provider failures. The one grounded plan reached
patch generation, whose output failed deterministic validation as
`PatchValidationError`; no valid patch or repair-test attempt resulted. Critic,
retry, final approval, and export therefore did not run.

Post-hoc file Hit@1/Hit@5/MRR was 0.8333/1.0000/0.9167. Gold file and symbol
ContextPack coverage were both 1.0000. Boltons used hybrid retrieval for two
cases; four larger more-itertools/toolz cases used the normal lexical fallback
after dense setup reached its unchanged timeout. Median/p95 milliseconds were:
indexing 82.0339/125.9838, embedding setup 60022.9820/60207.1311, retrieval
4.5341/82.3275, planner 254950.1458/331170.7461, and total
295313.5973/627939.8700. Patch generation was measured once at 312320.0977 ms;
repair tests, critic, and retry patch latency were not measured.

Safety results were zero scope violations, stale/hash failures, canonical
mutations, retry-limit violations, and exports before final approval. One patch
validation failure was the intended fail-closed behavior, not a safety breach.
This is a frozen controlled external evaluation across 3 public Python
repositories, not SWE-bench or production accuracy. Final artifacts are under
`evaluation/results/m9-v2/`; M9 v1 and Task 019C diagnostic evidence remain
unchanged under `evaluation/results/m9/`.
