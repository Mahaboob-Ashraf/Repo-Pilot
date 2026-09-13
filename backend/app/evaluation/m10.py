"""Gold-independent M10 calibration experiments over synthetic evidence."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from app.chunking import ChunkType, CodeChunk
from app.config import OllamaEmbeddingSettings, Settings
from app.context_packing import ContextPacker
from app.patching import PatchProposal, StructuredPatcher
from app.planning import (
    PlanningContextSnapshot,
    PlanValidationError,
    RepairPlan,
    RepairStep,
    StructuredPlanner,
    repair_plan_hash,
    validate_plan_grounding,
)
from app.providers import OllamaEmbeddingProvider
from app.retrieval import (
    EvidenceOrigin,
    ExpandedCandidate,
    ChromaVectorIndex,
    HybridRetrievalMode,
    HybridSearchResult,
    RetrievalSource,
    StructuralExpansionResult,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUITE = REPOSITORY_ROOT / "evaluation" / "fixtures" / "m10" / "development.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "evaluation" / "results" / "m10"
GENERATION_MODEL = "gemma4:e4b-it-qat"
EMBEDDING_MODEL = "embeddinggemma:latest"
CONTEXT_BUDGET = 16_384


class _PromptOnlyProvider:
    model = GENERATION_MODEL

    async def generate(self, prompt: str) -> str:
        raise RuntimeError("prompt-only provider cannot generate")


@dataclass
class _TimedBatchingProvider:
    provider: OllamaEmbeddingProvider
    batch_size: int | None
    batch_durations_ms: list[float] = field(default_factory=list)
    batch_cardinalities: list[int] = field(default_factory=list)

    @property
    def provider_name(self) -> str:
        return self.provider.provider_name

    @property
    def model(self) -> str:
        return self.provider.model

    async def embed_text(self, text: str) -> tuple[float, ...]:
        return await self.provider.embed_text(text)

    async def embed_batch(self, texts) -> tuple[tuple[float, ...], ...]:
        items = tuple(texts)
        size = self.batch_size or len(items)
        output: list[tuple[float, ...]] = []
        for offset in range(0, len(items), size):
            batch = items[offset : offset + size]
            started = perf_counter()
            output.extend(await self.provider.embed_batch(batch))
            self.batch_durations_ms.append((perf_counter() - started) * 1000)
            self.batch_cardinalities.append(len(batch))
        return tuple(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run M10 development-only experiments.")
    parser.add_argument(
        "experiment",
        choices=("planner", "patcher", "context", "embedding", "embedding_index"),
    )
    parser.add_argument(
        "--phase",
        choices=("plain", "native_schema", "native_schema_allowed_ids"),
        default="plain",
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    suite = _load_suite(args.suite)
    if args.experiment == "planner":
        artifact = asyncio.run(run_planner_experiment(suite, phase=args.phase))
        name = f"planner-{args.phase}.json"
    elif args.experiment == "patcher":
        artifact = asyncio.run(run_patcher_experiment(suite, phase=args.phase))
        name = f"patcher-{args.phase}.json"
    elif args.experiment == "context":
        artifact = run_context_experiment(suite)
        name = "context-depth.json"
    elif args.experiment == "embedding":
        artifact = asyncio.run(run_embedding_experiment(suite))
        name = "embedding-batches.json"
    else:
        artifact = asyncio.run(run_embedding_index_experiment(suite))
        name = "embedding-index-setup.json"
    _write_artifact(artifact, args.output_dir, name)
    print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
    return 0


def _load_suite(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("M10 development suite must be inside the repository")
    suite = json.loads(resolved.read_text(encoding="utf-8"))
    if suite.get("suite_id") != "m10-development-v1":
        raise ValueError("unsupported M10 development suite")
    if len(suite.get("planner_cases", [])) != 3:
        raise ValueError("M10 development suite must contain three planner cases")
    if not isinstance(suite.get("patch_case"), dict):
        raise ValueError("M10 development suite must contain one patch case")
    return suite


async def run_planner_experiment(
    suite: dict[str, Any], *, phase: str
) -> dict[str, Any]:
    if phase not in {"plain", "native_schema", "native_schema_allowed_ids"}:
        raise ValueError("invalid planner experiment phase")
    settings = Settings.from_environment()
    if settings.ollama_model != GENERATION_MODEL:
        raise ValueError("M10 planner calibration requires the locked generation model")
    records = []
    for case in suite["planner_cases"]:
        context = _planner_context(case)
        prompt = StructuredPlanner(_PromptOnlyProvider()).render_prompt(context)
        if phase == "native_schema_allowed_ids":
            prompt = _with_allowed_identifiers(prompt, context)
        started = perf_counter()
        response = await _ollama_generate(
            settings,
            prompt,
            response_schema=(
                RepairPlan.model_json_schema() if phase != "plain" else None
            ),
        )
        latency_ms = (perf_counter() - started) * 1000
        raw = response["response"]
        parser = PydanticOutputParser(pydantic_object=RepairPlan)
        parse_succeeded = False
        citations_valid = False
        grounded = False
        error_type = None
        error_message = None
        try:
            plan = parser.parse(raw)
            parse_succeeded = True
            allowed = {item.chunk_id for item in context.evidence}
            citations_valid = all(
                chunk_id in allowed
                for step in plan.steps
                for chunk_id in step.evidence_chunk_ids
            )
            validate_plan_grounding(plan, context)
            grounded = True
        except (OutputParserException, ValidationError, ValueError) as exc:
            error_type = type(exc).__name__
            error_message = str(exc)
            if isinstance(exc, PlanValidationError):
                error_type = "PlanValidationError"
        records.append(
            {
                "case_id": case["case_id"],
                "citation_ids_valid": citations_valid,
                "error_message": error_message,
                "error_type": error_type,
                "grounded_plan": grounded,
                "latency_ms": latency_ms,
                "parse_succeeded": parse_succeeded,
                "prompt_bytes": len(prompt.encode("utf-8")),
                "prompt_eval_count": response.get("prompt_eval_count"),
                "raw_output": raw,
                "raw_output_sha256": sha256(raw.encode("utf-8")).hexdigest(),
                "response_eval_count": response.get("eval_count"),
            }
        )
    return _artifact(
        suite,
        experiment="planner",
        configuration={"phase": phase, "model": GENERATION_MODEL},
        records=records,
        summary={
            "case_count": len(records),
            "citation_validity_rate": mean(
                float(item["citation_ids_valid"]) for item in records
            ),
            "grounded_plan_rate": mean(float(item["grounded_plan"]) for item in records),
            "mean_latency_ms": mean(item["latency_ms"] for item in records),
            "parse_success_rate": mean(
                float(item["parse_succeeded"]) for item in records
            ),
        },
    )


async def run_patcher_experiment(
    suite: dict[str, Any], *, phase: str
) -> dict[str, Any]:
    if phase not in {"plain", "native_schema"}:
        raise ValueError("patcher experiment phase must be plain or native_schema")
    settings = Settings.from_environment()
    if settings.ollama_model != GENERATION_MODEL:
        raise ValueError("M10 patcher calibration requires the locked generation model")
    case = suite["patch_case"]
    context = _planner_context({**case, "noise_count": 2})
    evidence = next(item for item in context.evidence if item.path == case["target_path"])
    plan = RepairPlan(
        summary="Correct the named rounding helper.",
        diagnosis="The supplied return expression increments instead of rounding down.",
        proposed_files=(case["target_path"],),
        steps=(
            RepairStep(
                description="Replace the faulty return expression.",
                affected_files=(case["target_path"],),
                evidence_chunk_ids=(evidence.chunk_id,),
            ),
        ),
        suggested_tests=("Run a focused rounding helper regression.",),
    )
    prompt = StructuredPatcher(_PromptOnlyProvider()).render_prompt(
        context=context,
        approved_plan=plan,
        approved_plan_hash=repair_plan_hash(plan),
        approved_files=plan.proposed_files,
    )
    started = perf_counter()
    response = await _ollama_generate(
        settings,
        prompt,
        response_schema=(
            PatchProposal.model_json_schema() if phase == "native_schema" else None
        ),
    )
    latency_ms = (perf_counter() - started) * 1000
    raw = response["response"]
    parser = PydanticOutputParser(pydantic_object=PatchProposal)
    parse_succeeded = False
    exact_contract_valid = False
    error_type = None
    error_message = None
    try:
        proposal = parser.parse(raw)
        parse_succeeded = True
        exact_contract_valid = bool(proposal.edits) and all(
            edit.path == case["target_path"]
            and edit.evidence_chunk_ids
            and all(item == evidence.chunk_id for item in edit.evidence_chunk_ids)
            and case["target_source"].count(edit.expected_old_text) == 1
            and edit.expected_old_text != edit.replacement_text
            for edit in proposal.edits
        )
    except (OutputParserException, ValidationError, ValueError) as exc:
        error_type = type(exc).__name__
        error_message = str(exc)
    record = {
        "case_id": case["case_id"],
        "error_message": error_message,
        "error_type": error_type,
        "exact_replacement_contract_valid": exact_contract_valid,
        "latency_ms": latency_ms,
        "parse_succeeded": parse_succeeded,
        "prompt_bytes": len(prompt.encode("utf-8")),
        "prompt_eval_count": response.get("prompt_eval_count"),
        "raw_output": raw,
        "raw_output_sha256": sha256(raw.encode("utf-8")).hexdigest(),
        "response_eval_count": response.get("eval_count"),
    }
    return _artifact(
        suite,
        experiment="patcher",
        configuration={"phase": phase, "model": GENERATION_MODEL},
        records=[record],
        summary={
            "case_count": 1,
            "exact_replacement_contract_rate": float(exact_contract_valid),
            "parse_success_rate": float(parse_succeeded),
            "mean_latency_ms": latency_ms,
        },
    )


def run_context_experiment(suite: dict[str, Any]) -> dict[str, Any]:
    cases = (
        ("relevant-rank-1", 1, 10),
        ("relevant-rank-3", 3, 10),
        ("relevant-rank-5", 5, 10),
    )
    records = []
    for top_k in (10, 5, 3):
        for case_id, relevant_rank, candidate_count in cases:
            candidates = tuple(
                _candidate(
                    _chunk(
                        path=(
                            "calibration/target.py"
                            if rank == relevant_rank
                            else f"calibration/noise_{rank:02d}.py"
                        ),
                        symbol=("target_operation" if rank == relevant_rank else f"noise_{rank:02d}"),
                        source=(
                            "def target_operation(value: int) -> int:\n    return value - 1\n"
                            if rank == relevant_rank
                            else f"def noise_{rank:02d}(value: int) -> int:\n    return value + {rank}\n"
                        ),
                        rank=rank,
                    ),
                    rank,
                )
                for rank in range(1, candidate_count + 1)
            )
            pack = ContextPacker().pack(
                "Correct target_operation without changing unrelated helpers.",
                StructuralExpansionResult(
                    candidates=candidates[:top_k],
                    retrieval_mode=HybridRetrievalMode.HYBRID,
                    degradation_reason=None,
                ),
                budget=CONTEXT_BUDGET,
            )
            relevant = [item for item in pack.included_chunks if item.path == "calibration/target.py"]
            included_cost = pack.included_chunk_token_cost
            relevant_cost = sum(item.token_cost for item in relevant)
            prompt = StructuredPlanner(_PromptOnlyProvider()).render_prompt(
                PlanningContextSnapshot.from_context_pack(pack)
            )
            records.append(
                {
                    "case_id": case_id,
                    "coverage": bool(relevant),
                    "included_chunks": len(pack.included_chunks),
                    "precision": len(relevant) / len(pack.included_chunks),
                    "prompt_bytes": len(prompt.encode("utf-8")),
                    "token_waste": (
                        (included_cost - relevant_cost) / included_cost
                        if included_cost
                        else None
                    ),
                    "top_k": top_k,
                }
            )
    summaries = {}
    for top_k in (10, 5, 3):
        rows = [item for item in records if item["top_k"] == top_k]
        summaries[str(top_k)] = {
            "coverage_rate": mean(float(item["coverage"]) for item in rows),
            "mean_precision": mean(item["precision"] for item in rows),
            "mean_prompt_bytes": mean(item["prompt_bytes"] for item in rows),
            "mean_token_waste": mean(item["token_waste"] for item in rows),
        }
    return _artifact(
        suite,
        experiment="context_depth",
        configuration={"top_k_values": [10, 5, 3], "budget": CONTEXT_BUDGET},
        records=records,
        summary=summaries,
    )


async def run_embedding_experiment(suite: dict[str, Any]) -> dict[str, Any]:
    case = suite["embedding_case"]
    count = int(case["chunk_count"])
    payload_size = int(case["source_payload_characters"])
    texts = tuple(
        f"def calibration_{index:03d}(value: int) -> int:\n"
        f"    return value + {index}\n# " + "x" * payload_size
        for index in range(count)
    )


async def run_embedding_index_experiment(suite: dict[str, Any]) -> dict[str, Any]:
    case = suite["embedding_case"]
    count = int(case["chunk_count"])
    payload_size = int(case["source_payload_characters"])
    settings = OllamaEmbeddingSettings.from_environment()
    if settings.ollama_embedding_model != EMBEDDING_MODEL:
        raise ValueError("M10 embedding calibration requires the locked embedding model")
    chunks = tuple(
        _chunk(
            path=f"calibration/index_{index:03d}.py",
            symbol=f"calibration_{index:03d}",
            source=(
                f"def calibration_{index:03d}(value: int) -> int:\n"
                f"    return value + {index}\n# " + "x" * payload_size
            ),
            rank=1,
        )
        for index in range(count)
    )
    index = ChromaVectorIndex(
        OllamaEmbeddingProvider(settings),
        collection_name="m10_development_embedding_setup",
    )
    rebuilt = await index.rebuild(chunks)
    metrics = index.last_rebuild_metrics
    if metrics is None:
        raise RuntimeError("vector rebuild did not retain setup metrics")
    record = {
        "batch_cardinalities": [
            min(metrics.embedding_batch_size, count - offset)
            for offset in range(0, count, metrics.embedding_batch_size)
        ],
        "chunk_count": rebuilt,
        "chroma_write_ms": metrics.chroma_write_ms,
        "embedding_batch_durations_ms": metrics.embedding_batch_durations_ms,
        "embedding_total_ms": metrics.embedding_total_ms,
        "total_setup_ms": metrics.total_ms,
    }
    return _artifact(
        suite,
        experiment="embedding_index_setup",
        configuration={
            "model": EMBEDDING_MODEL,
            "chunk_count": count,
            "batch_size": metrics.embedding_batch_size,
        },
        records=[record],
        summary=record,
    )
    settings = OllamaEmbeddingSettings.from_environment()
    if settings.ollama_embedding_model != EMBEDDING_MODEL:
        raise ValueError("M10 embedding calibration requires the locked embedding model")
    records = []
    for batch_size in (None, 32):
        provider = _TimedBatchingProvider(
            OllamaEmbeddingProvider(settings), batch_size=batch_size
        )
        started = perf_counter()
        vectors = await provider.embed_batch(texts)
        total_ms = (perf_counter() - started) * 1000
        records.append(
            {
                "batch_cardinalities": provider.batch_cardinalities,
                "batch_durations_ms": provider.batch_durations_ms,
                "batch_size": batch_size or count,
                "embedding_count": len(vectors),
                "total_embedding_ms": total_ms,
            }
        )
    return _artifact(
        suite,
        experiment="embedding_batches",
        configuration={"model": EMBEDDING_MODEL, "chunk_count": count},
        records=records,
        summary={
            "strategies": [
                {
                    "batch_size": item["batch_size"],
                    "request_count": len(item["batch_durations_ms"]),
                    "total_embedding_ms": item["total_embedding_ms"],
                    "maximum_request_ms": max(item["batch_durations_ms"]),
                }
                for item in records
            ]
        },
    )


async def _ollama_generate(
    settings: Settings,
    prompt: str,
    *,
    response_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
    }
    if response_schema is not None:
        body["format"] = response_schema
    async with httpx.AsyncClient(
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout_seconds,
    ) as client:
        response = await client.post("/api/generate", json=body)
        response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), str):
        raise ValueError("Ollama returned an invalid calibration response")
    return payload


def _planner_context(case: dict[str, Any]) -> PlanningContextSnapshot:
    chunks = [
        _chunk(
            path=case["target_path"],
            symbol=case["target_symbol"],
            source=case["target_source"],
            rank=1,
        )
    ]
    noise_size = int(case.get("noise_source_characters", 80))
    for index in range(1, int(case["noise_count"]) + 1):
        symbol = (
            f"{case['target_symbol']}_{index}"
            if case.get("similar_identifiers")
            else f"unrelated_helper_{index:02d}"
        )
        source = (
            f"def {symbol}(value):\n    return value\n# "
            + ("calibration noise " * 40)[:noise_size]
        )
        chunks.append(
            _chunk(
                path=f"calibration/noise_{index:02d}.py",
                symbol=symbol,
                source=source,
                rank=index + 1,
            )
        )
    expansion = StructuralExpansionResult(
        candidates=tuple(
            _candidate(chunk, rank) for rank, chunk in enumerate(chunks, start=1)
        ),
        retrieval_mode=HybridRetrievalMode.HYBRID,
        degradation_reason=None,
    )
    pack = ContextPacker().pack(case["issue"], expansion, budget=CONTEXT_BUDGET)
    return PlanningContextSnapshot.from_context_pack(pack)


def _with_allowed_identifiers(
    prompt: str, context: PlanningContextSnapshot
) -> str:
    chunk_ids = "\n".join(f'- "{item.chunk_id}"' for item in context.evidence)
    paths = "\n".join(
        f'- "{path}"' for path in sorted({item.path for item in context.evidence})
    )
    section = (
        "AUTHORITATIVE ALLOWED IDENTIFIERS:\n"
        "Copy complete values exactly; list position numbers are not IDs.\n"
        "ALLOWED_EVIDENCE_CHUNK_IDS:\n"
        f"{chunk_ids}\n"
        "ALLOWED_FILE_PATHS:\n"
        f"{paths}\n\n"
    )
    marker = "REQUIRED STRUCTURED OUTPUT:\n"
    if marker not in prompt:
        raise ValueError("planner prompt output marker is missing")
    return prompt.replace(marker, section + marker, 1)


def _chunk(*, path: str, symbol: str, source: str, rank: int) -> CodeChunk:
    end_line = len(source.splitlines())
    chunk_id = f"{path}::function::{symbol}::{rank}-{rank + end_line - 1}"
    return CodeChunk(
        chunk_id=chunk_id,
        path=path,
        language="python",
        chunk_type=ChunkType.FUNCTION,
        symbol=symbol,
        qualified_symbol=symbol,
        parent_class=None,
        start_line=rank,
        end_line=rank + end_line - 1,
        source_text=source,
        content_hash=sha256(source.encode("utf-8")).hexdigest(),
        imports=(),
    )


def _candidate(chunk: CodeChunk, rank: int) -> ExpandedCandidate:
    return ExpandedCandidate(
        chunk=chunk,
        origin=EvidenceOrigin.RETRIEVED,
        hybrid_result=HybridSearchResult(
            chunk=chunk,
            rank=rank,
            rrf_score=1 / (60 + rank),
            lexical_rank=rank,
            vector_rank=rank,
            lexical_bm25_score=-1.0,
            vector_cosine_distance=0.1,
            retrieval_sources=(RetrievalSource.LEXICAL, RetrievalSource.VECTOR),
        ),
    )


def _artifact(
    suite: dict[str, Any],
    *,
    experiment: str,
    configuration: dict[str, Any],
    records: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "repopilot.m10.development.v1",
        "suite_id": suite["suite_id"],
        "suite_sha256": sha256(
            json.dumps(suite, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "experiment": experiment,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": configuration,
        "records": records,
        "summary": summary,
        "limitations": [
            "Synthetic development cases only; frozen M8/M9 labels were not used.",
            "Model measurements are single samples and not broad reliability claims.",
        ],
    }


def _write_artifact(artifact: dict[str, Any], output_dir: Path, name: str) -> None:
    root = output_dir.resolve()
    if root == REPOSITORY_ROOT or not root.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("M10 output directory must be nested inside the repository")
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    raise SystemExit(main())
