"""Gemini preflight, M10 calibration, and frozen Gemma/Gemini comparison."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import ValidationError

from app.config import Settings
from app.evaluation.m10 import _load_suite, _planner_context
from app.patching import PatchProposal, StructuredPatcher
from app.planning import (
    PlanValidationError,
    RepairPlan,
    RepairStep,
    StructuredPlanner,
    repair_plan_hash,
    validate_plan_grounding,
)
from app.providers.base import (
    GenerationUsage,
    InferenceProviderError,
    UsageReportingInferenceProvider,
    generate_with_optional_schema,
)
from app.providers.factory import build_generation_provider
from app.providers.gemini import GeminiProvider


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUITE = REPOSITORY_ROOT / "evaluation" / "fixtures" / "m10" / "development.json"
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "evaluation"
    / "results"
    / "provider-comparison"
    / "gemini-3.1-flash-lite-v1"
)
DEFAULT_GEMINI_M9 = (
    REPOSITORY_ROOT
    / "evaluation"
    / "results"
    / "m9-gemini-3.1-flash-lite-v1"
    / "m9-results.json"
)
FROZEN_GEMMA_M9 = REPOSITORY_ROOT / "evaluation" / "results" / "m9-v3" / "m9-results.json"
FROZEN_GEMMA_M10_PLANNER = REPOSITORY_ROOT / "evaluation" / "results" / "m10" / "planner-native_schema.json"
FROZEN_GEMMA_M10_PATCHER = REPOSITORY_ROOT / "evaluation" / "results" / "m10" / "patcher-native_schema.json"
STABLE_FLASH_IDS = frozenset(
    {
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    }
)


class _PromptOnlyProvider:
    provider_name = "prompt-only"
    model = "prompt-only"

    async def generate(self, prompt: str) -> str:
        raise RuntimeError("prompt-only provider cannot generate")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run safe Gemini preflight/calibration or build provider comparison."
    )
    parser.add_argument("mode", choices=("preflight", "calibration", "compare"))
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--gemini-results", type=Path, default=DEFAULT_GEMINI_M9)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        if args.mode == "preflight":
            artifact = asyncio.run(run_gemini_preflight(Settings.from_environment()))
            _write_json(args.output_dir, "gemini-preflight.json", artifact)
            print(json.dumps(_public_summary(artifact), indent=2, sort_keys=True))
            return 0 if artifact["ready"] else 2
        if args.mode == "calibration":
            artifact = asyncio.run(
                run_gemini_calibration(
                    Settings.from_environment(),
                    _load_suite(args.suite),
                )
            )
            _write_json(args.output_dir, "gemini-m10-calibration.json", artifact)
            print(json.dumps(artifact["summary"], indent=2, sort_keys=True))
            return 0
        artifact = build_provider_comparison(
            gemma_path=FROZEN_GEMMA_M9,
            gemini_path=args.gemini_results,
        )
        _write_json(args.output_dir, "gemini-m9-results.json", artifact["gemini_result"])
        comparison = {key: value for key, value in artifact.items() if key != "gemini_result"}
        _write_json(args.output_dir, "provider-comparison.json", comparison)
        _write_text(
            args.output_dir,
            "provider-comparison.md",
            render_provider_comparison(comparison),
        )
        print(json.dumps(comparison["summary"], indent=2, sort_keys=True))
        return 0
    except InferenceProviderError as exc:
        print(f"Provider comparison stopped safely: {type(exc).__name__}: {exc}")
        return 3
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Provider comparison error: {type(exc).__name__}: {exc}")
        return 2


async def run_gemini_preflight(settings: Settings) -> dict[str, Any]:
    if settings.generation_provider != "gemini":
        raise ValueError("Gemini preflight requires REPOPILOT_GENERATION_PROVIDER=gemini")
    provider = build_generation_provider(settings)
    if not isinstance(provider, GeminiProvider):
        raise ValueError("Gemini preflight requires GeminiProvider")
    base = {
        "schema_version": "repopilot.gemini-preflight.v1",
        "provider": provider.provider_name,
        "model": provider.model,
        "timeout_seconds": settings.gemini_timeout_seconds,
        "sdk": "google-genai==2.23.0",
    }
    accessible_models: tuple[str, ...] = ()
    model_accessible = False
    plain_succeeded = False
    small_schema_succeeded = False
    repair_plan_succeeded = False
    try:
        accessible_models = await provider.list_suitable_models()
        await provider.check_model_access()
        model_accessible = True
        plain_started = perf_counter()
        plain = await provider.generate("Return exactly the text OK and nothing else.")
        plain_ms = (perf_counter() - plain_started) * 1000.0
        plain_usage = _usage(provider)
        plain_succeeded = plain.strip().casefold() == "ok"
        if not plain_succeeded:
            raise ValueError("Gemini plain preflight response did not match its contract")
        schema = {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
            "additionalProperties": False,
        }
        structured_started = perf_counter()
        structured_text = await provider.generate_structured(
            "Return a JSON object whose status is ok.", schema
        )
        structured_ms = (perf_counter() - structured_started) * 1000.0
        structured_usage = _usage(provider)
        structured = json.loads(structured_text)
        small_schema_succeeded = structured == {"status": "ok"}
        if not small_schema_succeeded:
            raise ValueError("Gemini schema preflight response did not match its contract")
        repair_plan_started = perf_counter()
        repair_plan_text = await provider.generate_structured(
            "Return a minimal repair plan for replacing a faulty return expression "
            "in demo.py. Use only evidence chunk ID demo.py::function::fix::1-2.",
            RepairPlan.model_json_schema(),
        )
        repair_plan_ms = (perf_counter() - repair_plan_started) * 1000.0
        repair_plan_usage = _usage(provider)
        PydanticOutputParser(pydantic_object=RepairPlan).parse(repair_plan_text)
        repair_plan_succeeded = True
    except Exception as exc:
        return {
            **base,
            "ready": False,
            "model_accessible": model_accessible,
            "plain_generation_succeeded": plain_succeeded,
            "structured_generation_succeeded": small_schema_succeeded,
            "repair_plan_generation_succeeded": repair_plan_succeeded,
            **_model_access_summary(accessible_models),
            "failure": f"Gemini preflight failed safely ({type(exc).__name__}).",
        }
    return {
        **base,
        "ready": True,
        "model_accessible": True,
        "plain_generation_succeeded": True,
        "structured_generation_succeeded": True,
        "repair_plan_generation_succeeded": True,
        **_model_access_summary(accessible_models),
        "latency_ms": {
            "plain": plain_ms,
            "structured": structured_ms,
            "repair_plan": repair_plan_ms,
        },
        "token_usage": {
            "plain": plain_usage,
            "structured": structured_usage,
            "repair_plan": repair_plan_usage,
        },
        "failure": None,
    }


def _model_access_summary(model_ids: tuple[str, ...]) -> dict[str, list[str]]:
    normalized = sorted({item.removeprefix("models/") for item in model_ids})
    return {
        "accessible_stable_flash_model_ids": [
            item for item in normalized if item in STABLE_FLASH_IDS
        ],
        "accessible_pro_model_ids": [
            item for item in normalized if "pro" in item.casefold()
        ],
    }


async def run_gemini_calibration(
    settings: Settings,
    suite: dict[str, Any],
) -> dict[str, Any]:
    if settings.generation_provider != "gemini":
        raise ValueError("Gemini calibration requires the Gemini generation provider")
    provider = build_generation_provider(settings)
    planner_records = []
    for case in suite["planner_cases"]:
        context = _planner_context(case)
        prompt = StructuredPlanner(_PromptOnlyProvider()).render_prompt(context)
        started = perf_counter()
        raw = await generate_with_optional_schema(
            provider, prompt, RepairPlan.model_json_schema()
        )
        latency_ms = (perf_counter() - started) * 1000.0
        parse_succeeded = False
        citations_valid = False
        grounded = False
        failure_type = None
        try:
            plan = PydanticOutputParser(pydantic_object=RepairPlan).parse(raw)
            parse_succeeded = True
            allowed = {item.chunk_id for item in context.evidence}
            citations_valid = all(
                chunk_id in allowed
                for step in plan.steps
                for chunk_id in step.evidence_chunk_ids
            )
            validate_plan_grounding(plan, context)
            grounded = True
        except (OutputParserException, ValidationError):
            failure_type = "structured-output parse"
        except PlanValidationError:
            failure_type = "grounding"
        planner_records.append(
            {
                "case_id": case["case_id"],
                "parse_succeeded": parse_succeeded,
                "citation_ids_valid": citations_valid,
                "grounded_plan": grounded,
                "failure_type": failure_type,
                "latency_ms": latency_ms,
                "prompt_bytes": len(prompt.encode("utf-8")),
                "response_sha256": sha256(raw.encode("utf-8")).hexdigest(),
                "token_usage": _usage(provider),
            }
        )

    patch_case = suite["patch_case"]
    context = _planner_context({**patch_case, "noise_count": 2})
    evidence = next(item for item in context.evidence if item.path == patch_case["target_path"])
    plan = RepairPlan(
        summary="Correct the named rounding helper.",
        diagnosis="The supplied return expression increments instead of rounding down.",
        proposed_files=(patch_case["target_path"],),
        steps=(
            RepairStep(
                description="Replace the faulty return expression.",
                affected_files=(patch_case["target_path"],),
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
    patch_started = perf_counter()
    raw_patch = await generate_with_optional_schema(
        provider, prompt, PatchProposal.model_json_schema()
    )
    patch_latency_ms = (perf_counter() - patch_started) * 1000.0
    patch_parse = False
    exact_contract = False
    patch_failure = None
    try:
        proposal = PydanticOutputParser(pydantic_object=PatchProposal).parse(raw_patch)
        patch_parse = True
        exact_contract = bool(proposal.edits) and all(
            edit.path == patch_case["target_path"]
            and edit.evidence_chunk_ids
            and all(item == evidence.chunk_id for item in edit.evidence_chunk_ids)
            and patch_case["target_source"].count(edit.expected_old_text) == 1
            and edit.expected_old_text != edit.replacement_text
            for edit in proposal.edits
        )
    except (OutputParserException, ValidationError, ValueError):
        patch_failure = "structured-output parse"
    patch_record = {
        "case_id": patch_case["case_id"],
        "parse_succeeded": patch_parse,
        "exact_replacement_contract_valid": exact_contract,
        "failure_type": patch_failure,
        "latency_ms": patch_latency_ms,
        "prompt_bytes": len(prompt.encode("utf-8")),
        "response_sha256": sha256(raw_patch.encode("utf-8")).hexdigest(),
        "token_usage": _usage(provider),
    }
    gemma_planner = _read_json(FROZEN_GEMMA_M10_PLANNER)["summary"]
    gemma_patcher = _read_json(FROZEN_GEMMA_M10_PATCHER)["summary"]
    return {
        "schema_version": "repopilot.gemini-m10-calibration.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "suite_id": suite["suite_id"],
        "suite_fingerprint": sha256(
            json.dumps(suite, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "provider": provider.provider_name,
        "model": provider.model,
        "planner_records": planner_records,
        "patcher_record": patch_record,
        "summary": {
            "planner": {
                "case_count": len(planner_records),
                "parse_success_rate": mean(float(x["parse_succeeded"]) for x in planner_records),
                "citation_validity_rate": mean(float(x["citation_ids_valid"]) for x in planner_records),
                "grounded_plan_rate": mean(float(x["grounded_plan"]) for x in planner_records),
                "mean_latency_ms": mean(x["latency_ms"] for x in planner_records),
            },
            "patcher": {
                "case_count": 1,
                "parse_success_rate": float(patch_parse),
                "exact_replacement_contract_rate": float(exact_contract),
                "mean_latency_ms": patch_latency_ms,
            },
            "frozen_gemma_m10": {
                "planner": gemma_planner,
                "patcher": gemma_patcher,
            },
        },
    }


def build_provider_comparison(*, gemma_path: Path, gemini_path: Path) -> dict[str, Any]:
    gemma = _read_json(gemma_path)
    gemini = _read_json(gemini_path)
    if gemma["manifest_fingerprint"] != gemini["manifest_fingerprint"]:
        raise ValueError("Gemma and Gemini artifacts use different frozen manifests")
    invariant_keys = (
        "embedding_model",
        "test_image",
        "rrf_k",
        "candidate_k",
        "top_k",
        "context_budget",
        "maximum_patch_attempts",
    )
    mismatches = [
        key
        for key in invariant_keys
        if gemma["configuration"].get(key) != gemini["configuration"].get(key)
    ]
    if mismatches:
        raise ValueError(
            "Provider comparison invariants differ: " + ", ".join(mismatches)
        )
    if gemini["configuration"].get("generation_provider") != "gemini":
        raise ValueError("candidate result was not generated with Gemini")
    failure_counts: dict[str, int] = {}
    per_case = []
    for case in gemini["cases"]:
        category = _failure_category(case)
        if category is not None:
            failure_counts[category] = failure_counts.get(category, 0) + 1
        per_case.append(
            {
                "case_id": case["case_id"],
                "repair_success": case["repair_success"],
                "terminal_status": case["terminal_status"],
                "failure_category": category,
                "failure_error_type": case.get("failure_error_type"),
                "failure_message": case.get("failure_message"),
                "retrieval_mode": case["retrieval"].get("mode"),
                "plan_generated": case["plan_generated"],
                "patch_produced": case["patch_produced"],
                "tests_passed": case["tests_passed"],
                "attempts": case["attempts"],
                "latency_ms": case["latency_ms"],
                "token_usage": case.get("token_usage", {}),
            }
        )
    result = {
        "schema_version": "repopilot.provider-comparison.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_fingerprint": gemini["manifest_fingerprint"],
        "providers": {
            "gemma": {
                "provider": "ollama",
                "model": gemma["configuration"]["generation_model"],
                "runtime": "local CPU",
                "artifact_identity": gemma["artifact_identity"],
            },
            "gemini": {
                "provider": "gemini",
                "model": gemini["configuration"]["generation_model"],
                "runtime": "remote API/network",
                "artifact_identity": gemini["artifact_identity"],
            },
            "embedding": {
                "provider": "ollama",
                "model": gemini["configuration"]["embedding_model"],
                "runtime": "local",
            },
        },
        "controlled_invariants": {
            key: gemini["configuration"].get(key) for key in invariant_keys
        },
        "gemma_metrics": _comparison_metrics(gemma),
        "gemini_metrics": _comparison_metrics(gemini),
        "gemini_cases": per_case,
        "gemini_failure_breakdown": dict(sorted(failure_counts.items())),
        "token_usage": {
            "gemma": "not retained in the frozen M9-v3 artifact",
            "gemini": gemini["aggregate"].get("token_usage", {}),
        },
        "limitations": [
            "Six controlled defects across three public repositories are not a production-accuracy estimate or SWE-bench.",
            "Gemma ran locally on CPU while Gemini used a hosted API and network; latency is not hardware-equivalent.",
            "Gemini mode sends bounded generation context off-machine; retrieval remains local through EmbeddingGemma.",
            "The frozen Gemma M9-v3 artifact did not retain token usage, so token totals are not directly comparable.",
        ],
    }
    result["summary"] = {
        "gemma_repair_success": result["gemma_metrics"]["repair_success"],
        "gemini_repair_success": result["gemini_metrics"]["repair_success"],
        "gemini_model": result["providers"]["gemini"]["model"],
        "critical_safety_failure": gemini["aggregate"]["critical_safety_failure"],
    }
    _assert_no_secret_markers(result)
    return {**result, "gemini_result": gemini}


def _comparison_metrics(artifact: dict[str, Any]) -> dict[str, Any]:
    aggregate = artifact["aggregate"]
    planner = aggregate["planner_outcomes"]
    patch = aggregate["patch_test"]
    retrieval = aggregate["retrieval"]
    latency = aggregate["latency_ms"]
    attempted = aggregate["cases_attempted"]
    provider_failures = sum(
        bool(case.get("provider_error_type")) for case in artifact["cases"]
    )
    critic_usage = latency["critic_generation_ms"]["count"]
    token_usage = aggregate.get("token_usage", {})
    return {
        "repair_success": f"{aggregate['repair_success_count']}/{attempted}",
        "attempt_1_success": int(round(aggregate["attempt_1_success_rate"] * attempted)),
        "grounded_plans": planner["valid_grounded_plans"],
        "planner_parse_failures": planner["output_parse_failures"],
        "planner_grounding_failures": planner["grounding_failures"],
        "planner_provider_failures": planner["provider_failures"],
        "exact_citation_validity": (
            planner["valid_grounded_plans"] / attempted if attempted else None
        ),
        "cases_reaching_patcher": patch["cases_reaching_patch_generation"],
        "valid_patches": patch["cases_producing_valid_patches"],
        "docker_test_passes": patch["docker_test_passes"],
        "critic_usage": critic_usage,
        "retry_usage": aggregate["retry_used_rate"],
        "retry_recoveries": int(round(aggregate["attempt_2_success_rate"] * attempted)),
        "provider_api_failures": provider_failures,
        "retrieval_hit_at_1": retrieval["gold_file_hit_at_1"],
        "retrieval_hit_at_5": retrieval["gold_file_hit_at_5"],
        "retrieval_mrr": retrieval["file_mrr"],
        "context_gold_file_coverage": retrieval["gold_file_context_coverage"],
        "context_gold_symbol_coverage": retrieval["gold_symbol_context_coverage"],
        "median_planner_latency_ms": latency["planning_generation_ms"]["median"],
        "median_patcher_latency_ms": _median_generation_latency(
            artifact,
            stage="patch_generation_ms",
            reached=lambda case: bool(case.get("patch_produced"))
            or case.get("failure_error_type")
            in {"PatchOutputError", "PatchValidationError", "PatchScopeError"},
        ),
        "median_total_latency_ms": latency["total_workflow_ms"]["median"],
        "token_usage": token_usage,
        "total_generation_tokens": _total_generation_tokens(token_usage),
        "critical_safety_failure": aggregate["critical_safety_failure"],
    }


def _total_generation_tokens(token_usage: dict[str, Any]) -> int | None:
    totals = [
        stage.get("total_tokens")
        for stage in token_usage.values()
        if isinstance(stage, dict) and stage.get("total_tokens") is not None
    ]
    return sum(totals) if totals else None


def _median_generation_latency(
    artifact: dict[str, Any],
    *,
    stage: str,
    reached: Any,
) -> float | None:
    values = [
        case["latency_ms"][stage]
        for case in artifact["cases"]
        if reached(case) and case.get("latency_ms", {}).get(stage) is not None
    ]
    recorded = artifact["aggregate"]["latency_ms"][stage]
    if len(values) == recorded["count"]:
        return recorded["median"]
    return sorted(values)[(len(values) - 1) // 2] if values else None


def _failure_category(case: dict[str, Any]) -> str | None:
    if case["repair_success"]:
        return None
    error = case.get("failure_error_type")
    stage = (case.get("failure_stage") or "").casefold()
    if case.get("provider_error_type") or error in {
        "PlannerInferenceError",
        "PatchInferenceError",
        "CriticInferenceError",
    }:
        return "provider/API"
    if error in {"PlannerOutputError", "PatchOutputError", "CriticOutputError"}:
        return "structured-output parse"
    if error in {"PlanValidationError", "CriticValidationError"}:
        return "grounding" if "planner" in stage else "critic"
    if error in {"StaleApprovalError", "ApprovalDecisionError"}:
        return "stale approval"
    if "patch generation" in stage:
        return "patch generation"
    if "patch validation" in stage:
        return "patch validation"
    if "docker" in stage or "infrastructure" in stage:
        return "Docker test"
    if "critic" in stage:
        return "critic"
    if "retry" in stage:
        return "retry"
    if "final approval" in stage:
        return "final approval"
    if "export" in stage:
        return "export"
    return stage or "unknown"


def render_provider_comparison(artifact: dict[str, Any]) -> str:
    gemma = artifact["gemma_metrics"]
    gemini = artifact["gemini_metrics"]
    rows = [
        ("Repair success", gemma["repair_success"], gemini["repair_success"]),
        ("Attempt-1 success", f"{gemma['attempt_1_success']}/6", f"{gemini['attempt_1_success']}/6"),
        ("Grounded plans", f"{gemma['grounded_plans']}/6", f"{gemini['grounded_plans']}/6"),
        ("Planner parse failures", gemma["planner_parse_failures"], gemini["planner_parse_failures"]),
        ("Planner grounding failures", gemma["planner_grounding_failures"], gemini["planner_grounding_failures"]),
        ("Exact citation validity", gemma["exact_citation_validity"], gemini["exact_citation_validity"]),
        ("Cases reaching patcher", gemma["cases_reaching_patcher"], gemini["cases_reaching_patcher"]),
        ("Valid patches", gemma["valid_patches"], gemini["valid_patches"]),
        ("Docker test passes", gemma["docker_test_passes"], gemini["docker_test_passes"]),
        ("Critic usage", gemma["critic_usage"], gemini["critic_usage"]),
        ("Retry usage", gemma["retry_usage"], gemini["retry_usage"]),
        ("Retry recoveries", gemma["retry_recoveries"], gemini["retry_recoveries"]),
        ("Provider/API failures", gemma["provider_api_failures"], gemini["provider_api_failures"]),
        ("Retrieval H@1", gemma["retrieval_hit_at_1"], gemini["retrieval_hit_at_1"]),
        ("Retrieval H@5", gemma["retrieval_hit_at_5"], gemini["retrieval_hit_at_5"]),
        ("Retrieval MRR", gemma["retrieval_mrr"], gemini["retrieval_mrr"]),
        ("Context gold file coverage", gemma["context_gold_file_coverage"], gemini["context_gold_file_coverage"]),
        ("Context gold symbol coverage", gemma["context_gold_symbol_coverage"], gemini["context_gold_symbol_coverage"]),
        ("Median planner latency", _seconds(gemma["median_planner_latency_ms"]), _seconds(gemini["median_planner_latency_ms"])),
        ("Median patcher latency", _seconds(gemma["median_patcher_latency_ms"]), _seconds(gemini["median_patcher_latency_ms"])),
        ("Median total latency", _seconds(gemma["median_total_latency_ms"]), _seconds(gemini["median_total_latency_ms"])),
        ("Total generation tokens", "not retained", gemini["total_generation_tokens"]),
    ]
    lines = [
        "# Controlled Gemma vs Gemini provider comparison",
        "",
        "The frozen six-case M9-v2 fixture set, retrieval stack, prompts, schemas, validators, Docker policy, approvals, and two-attempt limit were held constant. Only generation provider/model changed.",
        "",
        "| Metric | Gemma local CPU | Gemini remote API |",
        "|---|---:|---:|",
    ]
    lines.extend(f"| {name} | {left} | {right} |" for name, left, right in rows)
    lines.extend(
        [
            "",
            "## Gemini case outcomes",
            "",
            "| Case | Result | Failure category | Plan | Patch | Tests |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for case in artifact["gemini_cases"]:
        lines.append(
            f"| `{case['case_id']}` | "
            f"{'repaired' if case['repair_success'] else 'failed'} | "
            f"{case['failure_category'] or '-'} | "
            f"{'yes' if case['plan_generated'] else 'no'} | "
            f"{'yes' if case['patch_produced'] else 'no'} | "
            f"{'pass' if case['tests_passed'] else 'not passed'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation and limits",
            "",
            "Gemma generation ran locally on CPU. Gemini generation used a hosted API and network, while retrieval stayed local through Ollama/EmbeddingGemma. This is not a hardware-equivalent latency comparison.",
            "",
            "Gemini mode sends bounded issue text, ContextPack source, approved plan, and later patch/test evidence to Google's Gemini API when those stages run. Deterministic citation, scope, hash, exact-match, retry, Docker, approval, and export boundaries are identical.",
            "",
            "The benchmark contains only six controlled defects across three public repositories and is neither SWE-bench nor production evidence. Gemma token totals are unavailable because the frozen M9-v3 artifact did not retain them; no monetary cost is estimated.",
            "",
            "Gemini failure categories: `" + json.dumps(artifact["gemini_failure_breakdown"], sort_keys=True) + "`.",
        ]
    )
    return "\n".join(lines) + "\n"


def _usage(provider: Any) -> dict[str, int | None] | None:
    if not isinstance(provider, UsageReportingInferenceProvider):
        return None
    usage: GenerationUsage | None = provider.last_usage
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }


def _public_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: artifact[key]
        for key in (
            "ready",
            "provider",
            "model",
            "model_accessible",
            "plain_generation_succeeded",
            "structured_generation_succeeded",
            "repair_plan_generation_succeeded",
            "accessible_stable_flash_model_ids",
            "accessible_pro_model_ids",
            "failure",
        )
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))


def _write_json(root: Path, name: str, artifact: dict[str, Any]) -> None:
    _assert_output_root(root)
    _assert_no_secret_markers(artifact)
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_text(root: Path, name: str, text: str) -> None:
    _assert_output_root(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8", newline="\n")


def _assert_output_root(root: Path) -> None:
    resolved = root.resolve()
    if resolved == REPOSITORY_ROOT or not resolved.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("provider comparison output must stay under the repository")


def _assert_no_secret_markers(value: Any) -> None:
    rendered = json.dumps(value, sort_keys=True).casefold()
    for marker in (
        "repopilot_gemini_api_key",
        "authorization:",
        "x-goog-api-key",
        "bearer ",
    ):
        if marker in rendered:
            raise ValueError("provider comparison artifact contains a secret marker")


def _seconds(value: float | None) -> str:
    return "not measured" if value is None else f"{value / 1000.0:.3f}s"


__all__ = [
    "build_provider_comparison",
    "render_provider_comparison",
    "run_gemini_calibration",
    "run_gemini_preflight",
]


if __name__ == "__main__":
    raise SystemExit(main())
