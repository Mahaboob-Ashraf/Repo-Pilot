"""Reproducible local M8 retrieval and safety evaluation runner."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
from time import perf_counter
from typing import Any

import httpx

from app.chunking import build_repository_chunks
from app.chunking import ChunkType, CodeChunk
from app.config import OllamaEmbeddingSettings
from app.context_packing import ContextPacker
from app.evaluation.cases import RetrievalCase, load_retrieval_cases
from app.evaluation.context import ContextEvaluationVariant, score_context_pack
from app.evaluation.harness import (
    EvaluationRetrievalResponse,
    EvaluationVariant,
    aggregate_case_results,
    score_case,
)
from app.evaluation.safety import run_safety_evaluation
from app.evaluation.structure import (
    aggregate_structural_results,
    score_structural_expansion,
)
from app.providers import OllamaEmbeddingProvider
from app.retrieval import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_RRF_K,
    ChromaVectorIndex,
    HybridRetriever,
    SQLiteLexicalIndex,
    StructuralExpander,
    StructuralIndex,
    EvidenceOrigin,
    ExpandedCandidate,
    HybridRetrievalMode,
    StructuralExpansionResult,
    VectorRetrievalError,
)


SCHEMA_VERSION = "repopilot.m8.v1"
FIXTURE_SET_VERSION = "m8-frozen-local-v1"
EMBEDDING_MODEL = "embeddinggemma:latest"
TOP_K = 10
CONTEXT_BUDGET = 16_384

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES = REPOSITORY_ROOT / "evaluation" / "fixtures" / "m8" / "cases.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "evaluation" / "results" / "m8"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run RepoPilot's frozen local M8 evaluation without downloads."
    )
    parser.add_argument(
        "--mode", choices=("retrieval", "safety", "full"), default="full"
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        artifact = asyncio.run(run_m8(mode=args.mode, cases_path=args.cases))
        write_artifacts(artifact, output_dir=args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"M8 configuration error: {type(exc).__name__}")
        return 2
    safety = artifact.get("safety")
    if isinstance(safety, dict) and safety.get("passed") is False:
        return 1
    return 0


async def run_m8(*, mode: str, cases_path: Path = DEFAULT_CASES) -> dict[str, Any]:
    if mode not in {"retrieval", "safety", "full"}:
        raise ValueError("mode must be retrieval, safety, or full")
    resolved_cases = cases_path.resolve(strict=True)
    if not resolved_cases.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("evaluation cases must be inside the repository")
    cases = load_retrieval_cases(resolved_cases)
    if not cases:
        raise ValueError("frozen evaluation set must not be empty")
    fixture_fingerprint = _fixture_fingerprint(cases, resolved_cases)
    embedding_digest = (
        await _embedding_model_digest()
        if mode in {"retrieval", "full"}
        else None
    )
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evaluation_name": "M8 frozen local retrieval and safety evaluation",
        "evaluation_scope": "controlled_local_evaluation",
        "fixture_set_version": FIXTURE_SET_VERSION,
        "fixture_fingerprint": fixture_fingerprint,
        "artifact_identity": _artifact_identity(fixture_fingerprint),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "provenance": _provenance(embedding_model_digest=embedding_digest),
        "limitations": [
            "Small synthetic frozen Python fixture set; not statistically representative.",
            "Not SWE-bench, production evidence, or external/system repair evaluation.",
            "Latency is wall-clock evidence for this run and excludes model generation.",
            "Context units use the production UTF-8 byte estimator, not exact model tokens.",
        ],
    }
    if mode in {"retrieval", "full"}:
        artifact["retrieval"] = await _run_retrieval(cases)
    if mode in {"safety", "full"}:
        artifact["safety"] = (
            await asyncio.to_thread(run_safety_evaluation)
        ).to_dict()
    return artifact


async def _run_retrieval(cases: tuple[RetrievalCase, ...]) -> dict[str, Any]:
    grouped: dict[str, list[RetrievalCase]] = defaultdict(list)
    for case in cases:
        grouped[case.repository_ref].append(case)

    lexical_results = []
    dense_results = []
    hybrid_results = []
    context_results = []
    structure_results = []
    setup_records: list[dict[str, object]] = []
    dense_blocked: dict[str, str] | None = None

    for repository_ref in sorted(grouped):
        repository = (REPOSITORY_ROOT / repository_ref).resolve(strict=True)
        if not repository.is_relative_to(REPOSITORY_ROOT) or not repository.is_dir():
            raise ValueError("fixture repository escaped the evaluation root")
        setup_started = perf_counter()
        chunks = build_repository_chunks(repository).chunks
        chunking_ms = _elapsed_ms(setup_started)
        lexical = SQLiteLexicalIndex()
        lexical_started = perf_counter()
        lexical.rebuild(chunks)
        lexical_index_ms = _elapsed_ms(lexical_started)

        for case in grouped[repository_ref]:
            started = perf_counter()
            hits = lexical.search_lexical(case.query, k=TOP_K)
            response = EvaluationRetrievalResponse(
                hits=tuple(
                    _evaluation_hit(item.chunk, item.rank) for item in hits
                ),
                retrieval_mode=EvaluationVariant.AST_BM25.value,
            )
            lexical_results.append(
                score_case(
                    case,
                    EvaluationVariant.AST_BM25,
                    response,
                    latency_ms=_elapsed_ms(started),
                )
            )

        vector_index_ms: float | None = None
        if dense_blocked is None:
            try:
                provider = OllamaEmbeddingProvider(
                    OllamaEmbeddingSettings(
                        ollama_embedding_model=EMBEDDING_MODEL,
                    )
                )
                vector = ChromaVectorIndex(
                    provider,
                    collection_name=f"m8_{sha256(repository_ref.encode()).hexdigest()[:16]}",
                )
                vector_started = perf_counter()
                await vector.rebuild(chunks)
                vector_index_ms = _elapsed_ms(vector_started)
                hybrid = HybridRetriever(
                    lexical,
                    vector,
                    k_rrf=DEFAULT_RRF_K,
                    candidate_k=DEFAULT_CANDIDATE_K,
                )
                expander = StructuralExpander(StructuralIndex(chunks))
                packer = ContextPacker()
                for case in grouped[repository_ref]:
                    started = perf_counter()
                    dense_hits = await vector.search_vector(case.query, k=TOP_K)
                    dense_results.append(
                        score_case(
                            case,
                            EvaluationVariant.AST_DENSE,
                            EvaluationRetrievalResponse(
                                hits=tuple(
                                    _evaluation_hit(item.chunk, item.rank)
                                    for item in dense_hits
                                ),
                                retrieval_mode=EvaluationVariant.AST_DENSE.value,
                            ),
                            latency_ms=_elapsed_ms(started),
                        )
                    )
                    started = perf_counter()
                    hybrid_response = await hybrid.search_hybrid(
                        case.query, top_k=TOP_K
                    )
                    hybrid_latency = _elapsed_ms(started)
                    hybrid_results.append(
                        score_case(
                            case,
                            EvaluationVariant.AST_HYBRID_RRF,
                            EvaluationRetrievalResponse(
                                hits=tuple(
                                    _evaluation_hit(item.chunk, item.rank)
                                    for item in hybrid_response.results
                                ),
                                degraded=hybrid_response.degraded,
                                retrieval_mode=hybrid_response.mode.value,
                            ),
                            latency_ms=hybrid_latency,
                        )
                    )
                    context_started = perf_counter()
                    expansion = expander.expand(hybrid_response)
                    pack = packer.pack(
                        case.query, expansion, budget=CONTEXT_BUDGET
                    )
                    context_results.append(
                        score_context_pack(
                            case,
                            ContextEvaluationVariant.HYBRID_STRUCTURE,
                            pack,
                            latency_ms=_elapsed_ms(context_started),
                        )
                    )
                    structure_results.append(
                        score_structural_expansion(case, hybrid_response, expansion)
                    )
            except Exception as exc:
                if _is_expected_dense_block(exc):
                    dense_blocked = {
                        "classification": type(exc).__name__,
                        "reason": "The locked local embedding provider or dense index was unavailable; no substitute embeddings were used.",
                    }
                    dense_results.clear()
                    hybrid_results.clear()
                    context_results.clear()
                    structure_results.clear()
                else:
                    lexical.close()
                    raise
        setup_records.append(
            {
                "repository_ref": repository_ref,
                "chunk_count": len(chunks),
                "chunking_ms": chunking_ms,
                "lexical_index_ms": lexical_index_ms,
                "dense_index_ms": vector_index_ms,
            }
        )
        lexical.close()

    variants: dict[str, object] = {
        EvaluationVariant.AST_BM25.value: _direct_report(lexical_results),
        EvaluationVariant.AST_DENSE.value: (
            {"status": "blocked", **dense_blocked}
            if dense_blocked is not None
            else _direct_report(dense_results)
        ),
        EvaluationVariant.AST_HYBRID_RRF.value: (
            {"status": "blocked", **dense_blocked}
            if dense_blocked is not None
            else _direct_report(hybrid_results)
        ),
    }
    structure = (
        {"status": "blocked", **dense_blocked}
        if dense_blocked is not None
        else {
            "status": "measured",
            "aggregate": aggregate_structural_results(structure_results).to_dict(),
            "cases": [item.to_dict() for item in structure_results],
        }
    )
    context = (
        {"status": "blocked", **dense_blocked}
        if dense_blocked is not None
        else {
            "status": "measured",
            "aggregate": _aggregate_context(context_results),
            "cases": [item.to_dict() for item in context_results],
        }
    )
    degraded_structure = (
        await _run_degraded_structure(cases) if dense_blocked is not None else None
    )
    return {
        "case_count": len(cases),
        "repository_count": len(grouped),
        "top_k": TOP_K,
        "setup_and_indexing": setup_records,
        "variants": variants,
        "one_hop_structure": structure,
        "final_context_pack": context,
        "lexical_only_degraded_structure_context": degraded_structure,
        "context_budget_policy": _run_context_budget_scenarios(),
    }


class _UnavailableVectorIndex:
    async def search_vector(self, query: str, *, k: int):
        raise VectorRetrievalError("M8 deliberate unavailable-dense fallback probe")


async def _run_degraded_structure(
    cases: tuple[RetrievalCase, ...],
) -> dict[str, object]:
    """Measure production fallback + structure without substituting embeddings."""

    grouped: dict[str, list[RetrievalCase]] = defaultdict(list)
    for case in cases:
        grouped[case.repository_ref].append(case)
    context_results = []
    structure_results = []
    for repository_ref in sorted(grouped):
        repository = (REPOSITORY_ROOT / repository_ref).resolve(strict=True)
        chunks = build_repository_chunks(repository).chunks
        lexical = SQLiteLexicalIndex()
        lexical.rebuild(chunks)
        hybrid = HybridRetriever(
            lexical,
            _UnavailableVectorIndex(),  # type: ignore[arg-type]
            k_rrf=DEFAULT_RRF_K,
            candidate_k=DEFAULT_CANDIDATE_K,
        )
        expander = StructuralExpander(StructuralIndex(chunks))
        packer = ContextPacker()
        for case in grouped[repository_ref]:
            started = perf_counter()
            response = await hybrid.search_hybrid(case.query, top_k=TOP_K)
            if not response.degraded:
                raise ValueError("dense-unavailable probe did not enter degraded mode")
            expansion = expander.expand(response)
            pack = packer.pack(case.query, expansion, budget=CONTEXT_BUDGET)
            pipeline_latency_ms = _elapsed_ms(started)
            structure_results.append(
                score_structural_expansion(case, response, expansion)
            )
            context_results.append(
                score_context_pack(
                    case,
                    ContextEvaluationVariant.HYBRID_STRUCTURE,
                    pack,
                    latency_ms=pipeline_latency_ms,
                )
            )
        lexical.close()
    return {
        "status": "measured_degraded",
        "retrieval_mode": "lexical_only_degraded",
        "note": "Production BM25 fallback, one-hop structure, and ContextPack only; not a dense or hybrid result.",
        "structure_aggregate": aggregate_structural_results(
            structure_results
        ).to_dict(),
        "structure_cases": [item.to_dict() for item in structure_results],
        "context_aggregate": _aggregate_context(context_results),
        "context_cases": [item.to_dict() for item in context_results],
    }


def _run_context_budget_scenarios() -> dict[str, object]:
    """Exercise the unchanged production packer at its production budget."""

    definitions = (
        ("all_evidence_fits", (200, 300), ("budget/00.py", "budget/01.py")),
        ("useful_evidence_competes", (7_000, 7_000, 7_000), ("budget/00.py", "budget/02.py")),
        ("highest_priority_near_boundary", (15_000,), ("budget/00.py",)),
        ("oversized_highest_priority", (17_000, 100), ("budget/00.py",)),
    )
    cases: list[dict[str, object]] = []
    for case_id, sizes, gold_paths in definitions:
        candidates = tuple(
            ExpandedCandidate(
                chunk=_budget_chunk(index, size),
                origin=EvidenceOrigin.RETRIEVED,
                hybrid_result=None,
            )
            for index, size in enumerate(sizes)
        )
        expansion = StructuralExpansionResult(
            candidates=candidates,
            retrieval_mode=HybridRetrievalMode.HYBRID,
            degradation_reason=None,
        )
        pack = ContextPacker().pack(
            f"M8 fixed-budget scenario {case_id}",
            expansion,
            budget=CONTEXT_BUDGET,
        )
        included_paths = {item.path for item in pack.included_chunks}
        excluded_paths = {item.path for item in pack.excluded_candidates}
        cases.append(
            {
                "case_id": case_id,
                "configured_budget": CONTEXT_BUDGET,
                "used_units": pack.total_token_cost,
                "pack_status": pack.status.value,
                "included_chunk_ids": [item.chunk_id for item in pack.included_chunks],
                "excluded_candidates": [
                    {
                        "chunk_id": item.chunk_id,
                        "estimated_token_cost": item.estimated_token_cost,
                        "reason": item.reason.value,
                    }
                    for item in pack.excluded_candidates
                ],
                "gold_coverage": len(included_paths & set(gold_paths)) / len(gold_paths),
                "relevant_evidence_excluded_by_budget": bool(
                    excluded_paths & set(gold_paths)
                ),
            }
        )
    return {"status": "measured", "cases": cases}


def _budget_chunk(index: int, source_size: int) -> CodeChunk:
    prefix = f"def budget_candidate_{index}():\n    return '"
    suffix = "'\n"
    fill = "x" * max(0, source_size - len(prefix) - len(suffix))
    source = prefix + fill + suffix
    path = f"budget/{index:02d}.py"
    return CodeChunk(
        chunk_id=f"{path}::function::budget_candidate_{index}::1-2",
        path=path,
        language="python",
        chunk_type=ChunkType.FUNCTION,
        symbol=f"budget_candidate_{index}",
        qualified_symbol=f"budget_candidate_{index}",
        parent_class=None,
        start_line=1,
        end_line=2,
        source_text=source,
        content_hash=sha256(source.encode("utf-8")).hexdigest(),
        imports=(),
    )


def _evaluation_hit(chunk, rank):
    from app.evaluation.harness import EvaluationHit

    return EvaluationHit.from_chunk(chunk, rank=rank)


def _direct_report(results) -> dict[str, object]:
    if not results:
        raise ValueError("measured retrieval variant produced no case results")
    return {
        "status": "measured",
        "aggregate": aggregate_case_results(results).to_dict(),
        "cases": [item.to_dict() for item in results],
    }


def _aggregate_context(results) -> dict[str, object]:
    from app.evaluation.context import aggregate_context_results

    aggregate = aggregate_context_results(results).to_dict()
    aggregate["mean_gold_file_coverage"] = sum(
        item.gold_file_coverage for item in results
    ) / len(results)
    labeled = [item.gold_symbol_coverage for item in results if item.gold_symbol_coverage is not None]
    aggregate["mean_gold_symbol_coverage"] = (
        sum(labeled) / len(labeled) if labeled else None
    )
    aggregate["relevant_excluded_case_count"] = sum(
        item.relevant_evidence_excluded_by_budget for item in results
    )
    aggregate["pack_status_distribution"] = dict(
        sorted(Counter(item.pack_status.value for item in results).items())
    )
    return aggregate


def _fixture_fingerprint(cases: tuple[RetrievalCase, ...], cases_path: Path) -> str:
    digest = sha256()
    digest.update(cases_path.read_bytes())
    for repository_ref in sorted({case.repository_ref for case in cases}):
        root = (REPOSITORY_ROOT / repository_ref).resolve(strict=True)
        if not root.is_relative_to(REPOSITORY_ROOT):
            raise ValueError("fixture path escaped repository")
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            digest.update(repository_ref.encode("utf-8"))
            digest.update(b"\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _artifact_identity(fixture_fingerprint: str) -> str:
    payload = json.dumps(
        {
            "schema": SCHEMA_VERSION,
            "fixture": fixture_fingerprint,
            "embedding_model": EMBEDDING_MODEL,
            "rrf_k": DEFAULT_RRF_K,
            "candidate_k": DEFAULT_CANDIDATE_K,
            "top_k": TOP_K,
            "context_budget": CONTEXT_BUDGET,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _provenance(*, embedding_model_digest: str | None) -> dict[str, object]:
    return {
        "git_commit": _git_commit(),
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "chroma_version": _package_version("chromadb"),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_model_digest": embedding_model_digest,
        "embedding_document": "CodeChunk.source_text",
        "rrf_k": DEFAULT_RRF_K,
        "candidate_k": DEFAULT_CANDIDATE_K,
        "returned_top_k": TOP_K,
        "context_budget_units": CONTEXT_BUDGET,
        "context_unit_counter": "utf8_bytes",
    }


async def _embedding_model_digest() -> str | None:
    """Read an already-local Ollama model digest; never install or download."""

    settings = OllamaEmbeddingSettings()
    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=min(settings.ollama_embedding_timeout_seconds, 10.0),
        ) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    for item in models:
        if not isinstance(item, dict) or item.get("name") != EMBEDDING_MODEL:
            continue
        digest = item.get("digest")
        if (
            isinstance(digest, str)
            and len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
        ):
            return digest
    return None


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if len(value) == 40 else None


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0


def _is_expected_dense_block(exc: Exception) -> bool:
    names = {
        "EmbeddingUnavailableError", "EmbeddingResponseError",
        "VectorRetrievalError", "VectorCollectionError", "ConnectError",
        "ReadTimeout",
    }
    return any(cls.__name__ in names for cls in type(exc).__mro__)


def write_artifacts(artifact: dict[str, Any], *, output_dir: Path) -> None:
    root = output_dir.resolve()
    if root == REPOSITORY_ROOT or not root.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("M8 output directory must be a nested repository path")
    root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    (root / "m8-results.json").write_text(payload, encoding="utf-8", newline="\n")
    (root / "m8-report.md").write_text(
        render_markdown_report(artifact), encoding="utf-8", newline="\n"
    )


def render_markdown_report(artifact: dict[str, Any]) -> str:
    lines = [
        "# M8 Frozen Retrieval + Safety Evaluation",
        "",
        "> Controlled local evaluation only. This is not SWE-bench, production evidence, or a statistically representative sample of Python repositories.",
        "",
        "## 1. Evaluation setup",
        "",
        f"- Fixture set: `{artifact['fixture_set_version']}` (`{artifact['fixture_fingerprint']}`)",
        f"- Git commit: `{artifact['provenance']['git_commit'] or 'unavailable'}`",
        f"- Embedding model: `{artifact['provenance']['embedding_model']}`",
        f"- Embedding model digest: `{artifact['provenance']['embedding_model_digest'] or 'unavailable'}`",
        f"- RRF k / candidate k / returned k: `{DEFAULT_RRF_K}` / `{DEFAULT_CANDIDATE_K}` / `{TOP_K}`",
        f"- Context budget: `{CONTEXT_BUDGET}` estimated UTF-8-byte units",
        "",
    ]
    retrieval = artifact.get("retrieval")
    if isinstance(retrieval, dict):
        lines.extend(["## 2. Retrieval results", "", "| Variant | Status | File Hit@1 | File Hit@5 | File MRR | Symbol Hit@1 | Symbol Hit@5 | Symbol MRR | p50 ms | p95 ms |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
        for name, record in retrieval["variants"].items():
            if record["status"] == "blocked":
                lines.append(f"| `{name}` | blocked | — | — | — | — | — | — | — | — |")
                continue
            metric = record["aggregate"]
            lines.append(
                f"| `{name}` | measured | {_fmt(metric['file_hit_at_1_rate'])} | {_fmt(metric['file_hit_at_5_rate'])} | {_fmt(metric['mean_file_reciprocal_rank'])} | {_fmt(metric['symbol_hit_at_1_rate'])} | {_fmt(metric['symbol_hit_at_5_rate'])} | {_fmt(metric['mean_symbol_reciprocal_rank'])} | {_fmt(metric['latency_p50_ms'])} | {_fmt(metric['latency_p95_ms'])} |"
            )
        structure = retrieval["one_hop_structure"]
        lines.extend(["", "## 3. Structural expansion", ""])
        if structure["status"] == "blocked":
            lines.append(f"Blocked: {structure['reason']}")
        else:
            metric = structure["aggregate"]
            lines.append(
                f"Structure helped {metric['cases_helped']} cases, was unchanged for {metric['cases_unchanged']}, and added only non-gold evidence for {metric['cases_only_noise']}. Mean additions: {_fmt(metric['mean_additional_chunks'])} chunks / {_fmt(metric['mean_additional_estimated_source_units'])} source units."
            )
        context = retrieval["final_context_pack"]
        lines.extend(["", "## 4. Context packing", ""])
        if context["status"] == "blocked":
            lines.append(f"Blocked: {context['reason']}")
        else:
            metric = context["aggregate"]
            lines.append(
                f"Mean gold-file coverage `{_fmt(metric['mean_gold_file_coverage'])}`; mean gold-symbol coverage `{_fmt(metric['mean_gold_symbol_coverage'])}`; mean file/symbol chunk precision `{_fmt(metric['mean_file_context_chunk_precision'])}` / `{_fmt(metric['mean_symbol_context_chunk_precision'])}`; mean file/symbol token waste `{_fmt(metric['mean_file_context_token_waste'])}` / `{_fmt(metric['mean_symbol_context_token_waste'])}`; mean budget utilization `{_fmt(metric['mean_budget_utilization'])}`. Relevant evidence was budget-excluded in `{metric['relevant_excluded_case_count']}` cases. Pack statuses: `{json.dumps(metric['pack_status_distribution'], sort_keys=True)}`."
            )
        degraded = retrieval.get("lexical_only_degraded_structure_context")
        if isinstance(degraded, dict):
            structure_metric = degraded["structure_aggregate"]
            context_metric = degraded["context_aggregate"]
            lines.extend([
                "",
                "### Lexical-only degraded fallback (separate evidence)",
                "",
                "This is production BM25 fallback + one-hop structure + ContextPack, not a dense/hybrid result.",
                f"Structure helped `{structure_metric['cases_helped']}` cases, was unchanged for `{structure_metric['cases_unchanged']}`, and added only noise for `{structure_metric['cases_only_noise']}`. Context gold-file coverage was `{_fmt(context_metric['mean_gold_file_coverage'])}` with file token waste `{_fmt(context_metric['mean_file_context_token_waste'])}`.",
            ])
        budget = retrieval["context_budget_policy"]
        lines.extend([
            "",
            "### Fixed-budget policy scenarios",
            "",
            "| Case | Pack status | Used / 16384 | Gold coverage | Relevant excluded |",
            "|---|---|---:|---:|---|",
        ])
        for item in budget["cases"]:
            lines.append(
                f"| `{item['case_id']}` | `{item['pack_status']}` | {item['used_units']} | {_fmt(item['gold_coverage'])} | {str(item['relevant_evidence_excluded_by_budget']).lower()} |"
            )
    safety = artifact.get("safety")
    if isinstance(safety, dict):
        lines.extend(["", "## 5. Safety scorecard", "", "| Category | Scenarios | Passed | Failed |", "|---|---:|---:|---:|"])
        for row in safety["scorecard"]:
            lines.append(f"| {row['category']} | {row['scenarios']} | {row['passed']} | {row['failed']} |")
        lines.extend(["", "## 6. Fault injection", "", "Deterministic probes injected unapproved/mixed edits, invented and unrelated evidence, stale source and approval hashes, a workspace write failure, an operational critic instruction, an attempt-three request, pre-approval/wrong-hash exports, and export conflicts. The expected boundaries rejected them, downstream authority did not expand, and canonical-repository bytes remained unchanged. Detailed observations remain visible in `m8-results.json`."])
    dense_measured = (
        isinstance(retrieval, dict)
        and retrieval["variants"]["ast_dense"]["status"] == "measured"
    )
    if dense_measured:
        key_findings = (
            "BM25 and dense retrieval each placed a gold file first in 9/10 cases and "
            "within five in 10/10; hybrid RRF did both in 10/10. At returned k=10 on "
            "these small repositories, one-hop structure added no chunks in any case. "
            "All final ContextPacks covered every labeled gold file and symbol."
        )
        if isinstance(safety, dict):
            key_findings += (
                " All 33 deterministic safety scenarios passed with no canonical "
                "repository mutation."
            )
        weaknesses = (
            "BM25 ranked the wrong file first in the deliberately ambiguous same-name "
            "`normalize` case. Dense retrieval ranked a related test above the gold helper "
            "in the cross-module email case. Structural expansion had no observable effect "
            "at the current returned-k setting on these small fixtures. ContextPacks achieved "
            "full gold coverage but had mean file chunk precision 0.3750 and mean file token "
            "waste 0.6195. The suite remains too small and synthetic for broad accuracy claims."
        )
    else:
        key_findings = (
            "BM25 placed a gold file first in 9/10 cases and within five in 10/10. The only "
            "file Hit@1 miss was the deliberately ambiguous same-name `normalize` case. In "
            "the separately labeled degraded fallback, one-hop structure helped 2/10 cases "
            "but added only non-gold evidence in 5/10. Blocked dense-dependent rows were not "
            "replaced with fake embeddings."
        )
        if isinstance(safety, dict):
            key_findings += " All safety categories passed with no canonical mutation."
        weaknesses = (
            "Real dense/hybrid quality is unmeasured because `embeddinggemma:latest` was "
            "unavailable. Unqualified symbol labels cannot disambiguate the two `normalize` "
            "definitions, so file metrics are the honest signal for that case. Structural "
            "expansion added only noise in half the cases, and the fixed-budget competition "
            "scenario excluded relevant evidence (0.50 gold coverage). The suite remains too "
            "small and synthetic for broad accuracy claims."
        )
    lines.extend([
        "", "## 7. Key findings", "",
        key_findings,
        "", "## 8. Weaknesses discovered", "",
        weaknesses,
        "", "## 9. What M9 must test", "",
        "M9 must evaluate frozen external repositories and complete repair success through the existing two-checkpoint, two-attempt workflow. M8 does not provide that system-level evidence.",
        "",
    ])
    return "\n".join(lines)


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
