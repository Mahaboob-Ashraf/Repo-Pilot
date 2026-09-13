"""Build final M10 artifacts from immutable measured evaluation records."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = REPOSITORY_ROOT / "evaluation" / "results"
M10_ROOT = RESULTS_ROOT / "m10"


def main() -> int:
    m8 = _read("m8/m8-results.json")
    m8_v2 = _read("m8-v2/m8-results.json")
    m9_v2 = _read("m9-v2/m9-results.json")
    m9_v3 = _read("m9-v3/m9-results.json")
    planner_plain = _read("m10/planner-plain.json")
    planner_schema = _read("m10/planner-native_schema.json")
    planner_ids = _read("m10/planner-native_schema_allowed_ids.json")
    patch_plain = _read("m10/patcher-plain.json")
    patch_schema = _read("m10/patcher-native_schema.json")
    context = _read("m10/context-depth.json")
    embedding = _read("m10/embedding-batches.json")
    embedding_index = _read("m10/embedding-index-setup.json")

    optimizations = [
        {
            "id": "native-json-schema",
            "problem": "Planner structured-output reliability",
            "baseline": planner_plain["summary"],
            "change": "Optional provider-native JSON Schema for planner, patcher, and critic; deterministic parsing and validation retained.",
            "after": planner_schema["summary"],
            "safety_gate": "Pydantic and grounding/patch/critic validators remain authoritative.",
            "decision": "kept",
        },
        {
            "id": "explicit-allowed-id-list",
            "problem": "Invented evidence citations",
            "baseline": planner_schema["summary"],
            "change": "Append a compact authoritative list of real chunk IDs and paths.",
            "after": planner_ids["summary"],
            "diagnosis": "The medium prompt reached 4,081 prompt tokens in a 4,096-token runtime context and left only 15 response tokens.",
            "decision": "reverted",
        },
        {
            "id": "retrieval-depth-five",
            "problem": "Context precision and token waste",
            "baseline": context["summary"]["10"],
            "change": "Reduce returned retrieval depth from 10 to 5 before structural expansion and packing.",
            "after": context["summary"]["5"],
            "rejected_alternative": context["summary"]["3"],
            "decision": "kept",
        },
        {
            "id": "bounded-embedding-batches",
            "problem": "Single oversized dense-index embedding request and 60-second exposure",
            "baseline": embedding["summary"]["strategies"][0],
            "change": "Embed index documents in deterministic batches of 32 and retain setup timings.",
            "after": embedding["summary"]["strategies"][1],
            "index_setup": embedding_index["summary"],
            "decision": "kept",
        },
        {
            "id": "patch-prompt-change",
            "problem": "Historical toolz patch validation failure",
            "baseline": patch_plain["summary"],
            "change": "No prompt change; the development patch already satisfied exact replacement.",
            "after": patch_schema["summary"],
            "decision": "not_needed",
        },
        {
            "id": "patch-validation-diagnostics",
            "problem": "Historical M9-v2 artifact discarded the exact PatchValidationError reason",
            "change": "Retain only an allowlist of static first-party exact validation messages.",
            "decision": "kept",
        },
        {
            "id": "indented-method-freshness",
            "problem": "M9-v3 exposed two false stale-evidence failures for indented method chunks.",
            "change": "Require a unique exact source match within the declared line range instead of assuming column zero.",
            "safety_gate": "Content hash, line bounds, unique exact match, and exact edit validation remain required.",
            "decision": "kept_correctness_fix_after_evaluation",
        },
    ]

    generated = datetime.now(timezone.utc).isoformat()
    optimization_log = {
        "schema_version": "repopilot.m10.optimization-log.v1",
        "generated_at_utc": generated,
        "development_suite": planner_plain["suite_id"],
        "development_suite_sha256": planner_plain["suite_sha256"],
        "gold_independence": "Synthetic/development cases only; no M9 gold patches were used for optimization.",
        "optimizations": optimizations,
    }
    final_results = {
        "schema_version": "repopilot.m10.final-results.v1",
        "generated_at_utc": generated,
        "evaluation_scope": "frozen controlled external evaluation across 3 public Python repositories",
        "locked_models": {
            "generation": "gemma4:e4b-it-qat",
            "generation_digest": "ee665637121887cf3befff38abbb1be4ee117c7db867d97a67e29049ecd7e15f",
            "embedding": "embeddinggemma:latest",
            "embedding_digest": "85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1",
        },
        "m8_baseline": _m8_summary(m8),
        "m8_v2": _m8_summary(m8_v2),
        "m9_v2_baseline": _m9_summary(m9_v2),
        "m9_v3": _m9_summary(m9_v3),
        "m9_v3_cases": [_case_summary(case) for case in m9_v3["cases"]],
        "optimizations": optimizations,
        "safety": {
            "m8_v2_all_33_scenarios_passed": m8_v2["safety"]["passed"],
            "m9_v3_critical_safety_failure": m9_v3["aggregate"]["critical_safety_failure"],
            "m9_v3": m9_v3["aggregate"]["safety"],
        },
        "verification": {
            "focused_optimization_gate": {
                "passed": 130,
                "skipped": 1,
            },
            "complete_backend_suite": {
                "passed": 332,
                "duration_seconds": 7.58,
            },
            "frontend": {
                "test_files_passed": 2,
                "tests_passed": 18,
                "typescript_check": "passed",
                "production_build": "passed",
            },
        },
        "limitations": [
            "M8 is a small synthetic frozen suite; M9 contains six controlled defects and is not SWE-bench or production accuracy.",
            "Model calibration and M9 use one sample per case; results do not estimate stochastic variance.",
            "M9-v3 retained four lexical fallbacks after transient Ollama HTTP 400 embedding responses; an embedding-only replay later succeeded.",
            "Two M9-v3 cases hit a real indented-method freshness bug fixed only after measurement; M9-v3 was not rerun.",
            "The historical M9-v2 toolz PatchValidationError subtype is unknowable because the old workflow stored only a generic message.",
        ],
    }
    M10_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(M10_ROOT / "optimization-log.json", optimization_log)
    _write_json(M10_ROOT / "final-results.json", final_results)
    (M10_ROOT / "final-report.md").write_text(
        _render_report(final_results), encoding="utf-8", newline="\n"
    )
    return 0


def _read(relative: str) -> dict[str, Any]:
    return json.loads((RESULTS_ROOT / relative).read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _m8_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    hybrid = artifact["retrieval"]["variants"]["ast_hybrid_rrf"]["aggregate"]
    context = artifact["retrieval"]["final_context_pack"]["aggregate"]
    return {
        "artifact_identity": artifact["artifact_identity"],
        "top_k": artifact["retrieval"]["top_k"],
        "hybrid_file_hit_at_1": hybrid["file_hit_at_1_rate"],
        "hybrid_file_hit_at_5": hybrid["file_hit_at_5_rate"],
        "hybrid_file_mrr": hybrid["mean_file_reciprocal_rank"],
        "context": context,
        "safety_passed": artifact["safety"]["passed"],
        "safety_scenario_count": len(artifact["safety"]["scenarios"]),
    }


def _m9_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    aggregate = artifact["aggregate"]
    return {
        "artifact_identity": artifact["artifact_identity"],
        "manifest_fingerprint": artifact["manifest_fingerprint"],
        "repair_success_count": aggregate["repair_success_count"],
        "repair_success_rate": aggregate["repair_success_rate"],
        "attempt_1_success_rate": aggregate["attempt_1_success_rate"],
        "planner_outcomes": aggregate["planner_outcomes"],
        "patch_test": aggregate["patch_test"],
        "retrieval": aggregate["retrieval"],
        "retrieval_mode_counts": aggregate["retrieval_mode_counts"],
        "safety": aggregate["safety"],
        "critical_safety_failure": aggregate["critical_safety_failure"],
        "latency_ms": aggregate["latency_ms"],
    }


def _case_summary(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "terminal_status": case["terminal_status"],
        "repair_success": case["repair_success"],
        "failure_stage": case["failure_stage"],
        "failure_error_type": case["failure_error_type"],
        "failure_message": case["failure_message"],
        "retrieval_mode": case["retrieval"]["mode"],
        "latency_ms": case["latency_ms"],
    }


def _render_report(results: dict[str, Any]) -> str:
    m8 = results["m8_baseline"]
    m8_v2 = results["m8_v2"]
    m9 = results["m9_v2_baseline"]
    m9_v3 = results["m9_v3"]
    lines = [
        "# RepoPilot M10 final engineering report",
        "",
        "M10 used a separate synthetic development suite to select changes, then measured unchanged frozen M8 and M9 fixtures in new result directories. Original baseline artifacts remain intact.",
        "",
        "## Optimizations",
        "",
        "- Kept optional Ollama JSON-schema output, while retaining Pydantic parsing and deterministic validators.",
        "- Kept deterministic 32-document embedding batches and setup timing diagnostics.",
        "- Kept retrieval depth 5; depth 3 was rejected because development coverage fell.",
        "- Reverted the explicit allowed-ID list because it overflowed the 4,096-token runtime context on the medium case.",
        "- Kept the patch prompt and exact validator unchanged; added bounded failure diagnostics.",
        "- Fixed indented-method freshness after M9-v3 exposed a column-zero assumption.",
        "",
        "## M8 comparison",
        "",
        "| Metric | M8 baseline | M8-v2 |",
        "|---|---:|---:|",
        f"| Hybrid file Hit@1 | {m8['hybrid_file_hit_at_1']:.4f} | {m8_v2['hybrid_file_hit_at_1']:.4f} |",
        f"| Hybrid file Hit@5 | {m8['hybrid_file_hit_at_5']:.4f} | {m8_v2['hybrid_file_hit_at_5']:.4f} |",
        f"| File context precision | {m8['context']['mean_file_context_chunk_precision']:.4f} | {m8_v2['context']['mean_file_context_chunk_precision']:.4f} |",
        f"| File token waste | {m8['context']['mean_file_context_token_waste']:.4f} | {m8_v2['context']['mean_file_context_token_waste']:.4f} |",
        f"| Gold file coverage | {m8['context']['mean_gold_file_coverage']:.4f} | {m8_v2['context']['mean_gold_file_coverage']:.4f} |",
        f"| Safety scenarios | {m8['safety_scenario_count']}/33 | {m8_v2['safety_scenario_count']}/33 |",
        "",
        "## M9 comparison",
        "",
        "| Metric | M9-v2 baseline | M9-v3 optimized |",
        "|---|---:|---:|",
        f"| Repair success | {m9['repair_success_count']}/6 | {m9_v3['repair_success_count']}/6 |",
        f"| Grounded plans | {m9['planner_outcomes']['valid_grounded_plans']}/6 | {m9_v3['planner_outcomes']['valid_grounded_plans']}/6 |",
        f"| Planner parse failures | {m9['planner_outcomes']['output_parse_failures']} | {m9_v3['planner_outcomes']['output_parse_failures']} |",
        f"| Planner grounding failures | {m9['planner_outcomes']['grounding_failures']} | {m9_v3['planner_outcomes']['grounding_failures']} |",
        f"| Valid patches | {m9['patch_test']['cases_producing_valid_patches']} | {m9_v3['patch_test']['cases_producing_valid_patches']} |",
        f"| Docker test passes | {m9['patch_test']['docker_test_passes']} | {m9_v3['patch_test']['docker_test_passes']} |",
        f"| Retry recoveries | 0 | 0 |",
        f"| Retrieval H@1 | {m9['retrieval']['gold_file_hit_at_1']:.4f} | {m9_v3['retrieval']['gold_file_hit_at_1']:.4f} |",
        f"| Context file coverage | {m9['retrieval']['gold_file_context_coverage']:.4f} | {m9_v3['retrieval']['gold_file_context_coverage']:.4f} |",
        f"| Lexical fallbacks | {m9['retrieval_mode_counts']['lexical_only_degraded']} | {m9_v3['retrieval_mode_counts']['lexical_only_degraded']} |",
        f"| Median total latency (ms) | {m9['latency_ms']['total_workflow_ms']['median']:.1f} | {m9_v3['latency_ms']['total_workflow_ms']['median']:.1f} |",
        "",
        "M9-v3 repaired 1/6 controlled external cases. This is a frozen controlled external evaluation across 3 public Python repositories, not SWE-bench or a production-accuracy estimate.",
        "",
        "## Safety",
        "",
        "M8-v2 passed all 33 deterministic scenarios. M9-v3 recorded no critical safety failure, scope violation, canonical mutation, retry-limit violation, or export-order failure. The two stale rejections were safe failures caused by a correctness bug fixed after measurement.",
        "",
        "## Final verification",
        "",
        "The complete backend suite passed 332 tests in 7.58 seconds. Frontend Vitest passed 18 tests across two files; TypeScript checking and the production Vite build passed.",
        "",
        "## Reproducibility and limitations",
        "",
        "The locked models were `gemma4:e4b-it-qat` and `embeddinggemma:latest`; Gemma was verified with `size_vram=0`. Docker used the pinned local pytest image. See `final-results.json` for identities, per-case failures, latencies, and limitations.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
