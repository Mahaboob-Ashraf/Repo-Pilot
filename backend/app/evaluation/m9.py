"""Frozen external-repository M9 system evaluation runner."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from time import perf_counter
from typing import Any

import httpx
from chromadb.errors import ChromaError
from langgraph.checkpoint.memory import InMemorySaver

from app.chunking import build_repository_chunks
from app.config import OllamaEmbeddingSettings, Settings
from app.context_packing import ContextPacker
from app.critic import CriticAssessmentStore, CriticService, StructuredCritic
from app.evaluation.m9_models import (
    AttemptRecord,
    ExecutionObservation,
    M9Case,
    M9Manifest,
    ProductionCaseInput,
    StageLatencies,
    aggregate_scores,
    assert_artifact_has_no_absolute_paths,
    benchmark_final_decision,
    benchmark_plan_decision,
    load_m9_manifest,
    score_case,
)
from app.evaluation.m9_ingestion import diagnose_manifest_ingestion
from app.exporting import PatchExporter
from app.patching import (
    ApprovedPatchService,
    PatchArtifact,
    StructuredPatcher,
    WorkspaceManager,
)
from app.planning import StructuredPlanner
from app.providers import OllamaEmbeddingProvider
from app.providers.embeddings import EmbeddingProviderError
from app.providers.ollama import OllamaProvider
from app.retrieval import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_RRF_K,
    ChromaVectorIndex,
    HybridRetriever,
    SQLiteLexicalIndex,
    StructuralExpander,
    StructuralIndex,
    VectorRetrievalError,
)
from app.sandbox import (
    ApprovedPatchTestService,
    DisposableTestSnapshotManager,
    DockerTestRunner,
    TestMode,
    TestResultStore,
    TestRunRequest,
    TestRunSpec,
    TestStatus,
    validate_pytest_selectors,
)
from app.workflow import PlanReviewService, WorkflowStatus


SCHEMA_VERSION = "repopilot.m9.v1"
GENERATION_MODEL = "gemma4:e4b-it-qat"
EMBEDDING_MODEL = "embeddinggemma:latest"
TEST_IMAGE = "repopilot-python-test:3.11-pytest9"
TOP_K = 5
CONTEXT_BUDGET = 16_384
M9_V2_MANIFEST_FINGERPRINT = (
    "e08a819fbdc6dd3b8bd164a1b27fee63f495f55d0d350117a2b60556fe2e973b"
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "evaluation" / "fixtures" / "m9" / "manifest.json"
DEFAULT_CACHE = REPOSITORY_ROOT / "evaluation" / "cache"
DEFAULT_FIXTURES = DEFAULT_CACHE / "m9" / "cases"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "evaluation" / "results" / "m9"
DIAGNOSIS_FILENAME = "m9-task-019c-diagnosis.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate, materialize, or run RepoPilot's frozen M9 benchmark."
    )
    parser.add_argument(
        "mode",
        choices=(
            "validate",
            "materialize",
            "check-fixtures",
            "diagnose-ingestion",
            "diagnose-planner",
            "verify-fixture-tests",
            "dry-run",
            "real",
            "report",
        ),
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--case-id",
        help="Select one frozen case for a bounded diagnostic mode.",
    )
    parser.add_argument(
        "--diagnostic-label",
        default="initial",
        choices=("initial", "confirmation"),
        help="Keep an infrastructure-invalid run separate from one confirmation run.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Permit git clone/fetch only during explicit materialization.",
    )
    args = parser.parse_args(argv)
    try:
        manifest = load_m9_manifest(args.manifest.resolve(strict=True))
        if args.mode == "validate":
            print(f"valid {manifest.benchmark_id} {manifest.fingerprint}")
            return 0
        if args.mode in {"materialize", "check-fixtures"}:
            records = materialize_manifest(
                manifest,
                cache_root=args.cache_dir,
                allow_network=args.allow_network if args.mode == "materialize" else False,
                create=args.mode == "materialize",
            )
            print(json.dumps(records, indent=2, sort_keys=True))
            return 0 if all(item["valid"] for item in records) else 2
        if args.mode == "report":
            artifact = json.loads((args.output_dir / "m9-results.json").read_text(encoding="utf-8"))
            assert_artifact_has_no_absolute_paths(artifact)
            _write_report_only(artifact, args.output_dir)
            return 0
        if args.mode == "diagnose-ingestion":
            records = diagnose_manifest_ingestion(
                manifest,
                fixture_root=args.cache_dir / "m9" / "cases",
            )
            args.output_dir.mkdir(parents=True, exist_ok=True)
            output = args.output_dir / "m9-ingestion.json"
            output.write_text(
                json.dumps(records, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(records, indent=2, sort_keys=True))
            return 0 if all(item["success"] for item in records) else 2
        if args.mode == "diagnose-planner":
            if not args.case_id:
                raise ValueError("diagnose-planner requires --case-id")
            case = _case_by_id(manifest, args.case_id)
            case_input = ProductionCaseInput.from_case(
                case,
                fixture_root=args.cache_dir / "m9" / "cases",
            )
            if fixture_fingerprint(case_input.repository_root) != case.fixture_fingerprint:
                raise ValueError("selected planner diagnostic fixture fingerprint is invalid")
            record = asyncio.run(execute_planner_diagnostic(case_input))
            record.update(
                {
                    "benchmark_id": manifest.benchmark_id,
                    "manifest_fingerprint": manifest.fingerprint,
                    "diagnostic_label": args.diagnostic_label,
                }
            )
            assert_artifact_has_no_absolute_paths(record)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            output = args.output_dir / f"m9-planner-diagnostic-{args.diagnostic_label}.json"
            output.write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            print(json.dumps(record, indent=2, sort_keys=True))
            return 0
        if args.mode == "verify-fixture-tests":
            docker = _docker_preflight()
            if not docker.get("daemon_reachable") or not docker.get("image_available"):
                raise ValueError(docker.get("reason") or "Docker fixture-test preflight failed")
            selected_cases = (
                (_case_by_id(manifest, args.case_id),)
                if args.case_id
                else manifest.cases
            )
            records = asyncio.run(
                verify_fixture_tests(
                    manifest,
                    fixture_root=args.cache_dir / "m9" / "cases",
                    cases=selected_cases,
                )
            )
            args.output_dir.mkdir(parents=True, exist_ok=True)
            output = args.output_dir / "m9-fixture-tests.json"
            output.write_text(
                json.dumps(records, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(records, indent=2, sort_keys=True))
            return 0 if all(item["valid"] for item in records) else 2
        if args.mode == "dry-run":
            artifact = run_fake_evaluation(manifest)
        else:
            artifact = asyncio.run(run_real_evaluation(manifest, fixture_root=args.cache_dir / "m9" / "cases"))
        write_artifacts(artifact, output_dir=args.output_dir)
        return 1 if artifact["aggregate"]["critical_safety_failure"] else 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"M9 {args.mode} error: {type(exc).__name__}: {exc}")
        return 2


def materialize_manifest(
    manifest: M9Manifest,
    *,
    cache_root: Path,
    allow_network: bool,
    create: bool,
) -> list[dict[str, Any]]:
    """Materialize only pinned Git commits; never install dependencies or tools."""

    cache = cache_root.resolve()
    if cache == REPOSITORY_ROOT or not cache.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("M9 cache must be a nested repository evaluation/cache path")
    upstream_root = cache / "upstream"
    fixture_root = cache / "m9" / "cases"
    if create:
        upstream_root.mkdir(parents=True, exist_ok=True)
        fixture_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for repository in manifest.repositories:
        checkout = upstream_root / repository.repository_id
        if not checkout.exists():
            if not create:
                records.append({"kind": "repository", "id": repository.repository_id, "valid": False, "reason": "not_materialized"})
                continue
            if not allow_network:
                raise ValueError("materialization needs --allow-network when a pinned checkout is absent")
            _run_git(["clone", "--no-checkout", repository.upstream_url, str(checkout)])
        if not (checkout / ".git").exists():
            raise ValueError(f"upstream cache for {repository.repository_id} is not a Git checkout")
        if _git_output(["-C", str(checkout), "remote", "get-url", "origin"]) != repository.upstream_url:
            raise ValueError(f"upstream URL mismatch for {repository.repository_id}")
        if not _git_commit_exists(checkout, repository.commit_sha):
            if not create or not allow_network:
                raise ValueError(f"pinned commit absent for {repository.repository_id}; explicit network materialization required")
            _run_git(["-C", str(checkout), "fetch", "--no-tags", "origin", repository.commit_sha])
        _run_git(["-C", str(checkout), "checkout", "--detach", repository.commit_sha])
        actual_commit = _git_output(["-C", str(checkout), "rev-parse", "HEAD"])
        source_fingerprint = selected_fixture_fingerprint(checkout, repository.fixture_paths)
        records.append({
            "kind": "repository", "id": repository.repository_id,
            "commit_sha": actual_commit, "fingerprint": source_fingerprint,
            "valid": actual_commit == repository.commit_sha and source_fingerprint == repository.source_fingerprint,
        })
        for case in (item for item in manifest.cases if item.repository_id == repository.repository_id):
            target = fixture_root / case.case_id
            if not target.exists():
                if not create:
                    records.append({"kind": "case", "id": case.case_id, "valid": False, "reason": "not_materialized"})
                    continue
                target.mkdir(parents=True)
                for relative in repository.fixture_paths:
                    source = (checkout / relative).resolve(strict=True)
                    if not source.is_relative_to(checkout.resolve()):
                        raise ValueError("selected fixture path escaped the upstream checkout")
                    destination = target / relative
                    if source.is_dir():
                        shutil.copytree(source, destination, ignore=_copy_ignore)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
                _apply_replacement(target, case.controlled_mutation.path, case.controlled_mutation.expected_old_text, case.controlled_mutation.replacement_text)
            fingerprint = fixture_fingerprint(target)
            records.append({
                "kind": "case", "id": case.case_id, "fingerprint": fingerprint,
                "valid": fingerprint == case.fixture_fingerprint,
            })
    return records


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    excluded = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache", ".tox", ".venv", "venv"}
    return set(names) & excluded


def _case_by_id(manifest: M9Manifest, case_id: str) -> M9Case:
    matches = [case for case in manifest.cases if case.case_id == case_id]
    if len(matches) != 1:
        raise ValueError(f"unknown frozen M9 case ID: {case_id}")
    return matches[0]


def _apply_replacement(root: Path, relative: str, old: str, new: str) -> None:
    target = (root / relative).resolve(strict=True)
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError("controlled mutation target escaped its fixture")
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"controlled mutation exact text was not unique in {relative}")
    target.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def fixture_fingerprint(root: Path) -> str:
    digest = sha256()
    excluded_parts = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache", ".tox", ".venv", "venv"}
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and not any(part in excluded_parts for part in path.relative_to(root).parts)
    )
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def selected_fixture_fingerprint(root: Path, selected_paths: tuple[str, ...]) -> str:
    with tempfile.TemporaryDirectory(prefix="repopilot-m9-fingerprint-") as temporary:
        selection = Path(temporary)
        for relative in selected_paths:
            source = (root / relative).resolve(strict=True)
            if not source.is_relative_to(root.resolve()):
                raise ValueError("selected fixture path escaped the upstream checkout")
            destination = selection / relative
            if source.is_dir():
                shutil.copytree(source, destination, ignore=_copy_ignore)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        return fixture_fingerprint(selection)


async def preflight() -> dict[str, Any]:
    docker = _docker_preflight()
    ollama = await _ollama_preflight()
    ready = bool(
        docker.get("daemon_reachable")
        and docker.get("image_available")
        and ollama.get("reachable")
        and ollama.get("required_models_available")
    )
    return {"ready": ready, "docker": docker, "ollama": ollama}


def _docker_preflight() -> dict[str, Any]:
    executable = shutil.which("docker")
    if executable is None:
        return {
            "cli_available": False, "daemon_reachable": False,
            "image_reference": TEST_IMAGE, "image_available": None,
            "reason": "Docker CLI is unavailable on PATH; daemon and local image cannot be inspected.",
        }
    try:
        info = subprocess.run([executable, "info", "--format", "{{json .ServerVersion}}"], check=True, capture_output=True, text=True, timeout=15, shell=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"cli_available": True, "daemon_reachable": False, "image_reference": TEST_IMAGE, "image_available": None, "reason": f"Docker daemon unavailable ({type(exc).__name__})."}
    inspected = subprocess.run([executable, "image", "inspect", TEST_IMAGE, "--format", "{{.Id}}"], check=False, capture_output=True, text=True, timeout=15, shell=False)
    return {
        "cli_available": True, "daemon_reachable": True,
        "server_version": info.stdout.strip().strip('"'),
        "image_reference": TEST_IMAGE, "image_available": inspected.returncode == 0,
        "image_id": inspected.stdout.strip() or None,
        "reason": None if inspected.returncode == 0 else f"Required local image {TEST_IMAGE} is missing; no pull/build attempted.",
    }


async def _ollama_preflight() -> dict[str, Any]:
    settings = OllamaEmbeddingSettings.from_environment()
    try:
        async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=10.0) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"reachable": False, "required_models_available": False, "reason": f"Ollama unavailable ({type(exc).__name__}).", "models": []}
    models = []
    for item in payload.get("models", []) if isinstance(payload, dict) else []:
        if isinstance(item, dict) and item.get("name") in {GENERATION_MODEL, EMBEDDING_MODEL}:
            models.append({"name": item.get("name"), "digest": item.get("digest")})
    names = {item["name"] for item in models}
    return {
        "reachable": True,
        "required_models_available": {GENERATION_MODEL, EMBEDDING_MODEL}.issubset(names),
        "models": sorted(models, key=lambda item: str(item["name"])),
        "reason": None if {GENERATION_MODEL, EMBEDDING_MODEL}.issubset(names) else "One or more locked local models are unavailable; no pull attempted.",
    }


async def verify_fixture_tests(
    manifest: M9Manifest,
    *,
    fixture_root: Path,
    cases: tuple[M9Case, ...] | None = None,
) -> list[dict[str, Any]]:
    """Prove each frozen defect fails its configured selector in the M5 sandbox."""

    runner = DockerTestRunner()
    records: list[dict[str, Any]] = []
    selected_cases = manifest.cases if cases is None else cases
    if any(case not in manifest.cases for case in selected_cases):
        raise ValueError("fixture-test selection must belong to the loaded manifest")
    for case in selected_cases:
        case_input = ProductionCaseInput.from_case(case, fixture_root=fixture_root)
        before = fixture_fingerprint(case_input.repository_root)
        mutation_target = case_input.repository_root / case.controlled_mutation.path
        controlled_defect_present = (
            case.controlled_mutation.replacement_text
            in mutation_target.read_text(encoding="utf-8")
        )
        selectors = validate_pytest_selectors(
            case_input.test_selectors,
            repository_root=case_input.repository_root,
        )
        test_path = selectors[0].split("::", 1)[0]
        artifact = PatchArtifact(
            workspace_id=f"m9-baseline-{case.case_id}",
            source_plan_hash=before,
            changed_files=(test_path,),
            unified_diff="M9 pre-repair fixture validation; no patch applied.",
            patch_hash=before,
        )
        test_run_id = sha256(
            f"m9-baseline:{case.case_id}:{before}".encode("utf-8")
        ).hexdigest()
        result = await runner.run(
            TestRunSpec(
                test_run_id=test_run_id,
                patch=artifact,
                mode=TestMode.TARGETED,
                validated_selectors=selectors,
                execution_repository=case_input.repository_root,
            )
        )
        after = fixture_fingerprint(case_input.repository_root)
        expected_failure_observed = (
            result.status is TestStatus.FAILED and result.exit_code == 1
        )
        records.append(
            {
                "case_id": case.case_id,
                "repository_id": case.repository_id,
                "selector": list(selectors),
                "manifest_fingerprint_valid": before == case.fixture_fingerprint,
                "controlled_defect_present": controlled_defect_present,
                "expected_failure_observed": expected_failure_observed,
                "test_status": result.status.value,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "failure_classification": result.failure_classification,
                "image_id": result.image_id,
                "canonical_fixture_unchanged": before == after,
                "valid": bool(
                    before == case.fixture_fingerprint
                    and controlled_defect_present
                    and expected_failure_observed
                    and before == after
                ),
            }
        )
    return records


class _TimerBook:
    def __init__(self) -> None:
        self.values: dict[str, list[float]] = {}

    def add(self, name: str, started: float) -> None:
        self.values.setdefault(name, []).append((perf_counter() - started) * 1000.0)

    def total(self, name: str) -> float | None:
        values = self.values.get(name)
        return sum(values) if values else None


class _TimedPlanner:
    def __init__(self, service: StructuredPlanner, timers: _TimerBook) -> None:
        self.service, self.timers = service, timers

    async def create_plan_with_hash(self, *args, **kwargs):
        started = perf_counter()
        try:
            return await self.service.create_plan_with_hash(*args, **kwargs)
        finally:
            self.timers.add("planning", started)


class _TimedPatchService:
    def __init__(self, service: ApprovedPatchService, timers: _TimerBook) -> None:
        self.service, self.timers = service, timers

    async def prepare_patch(self, *args, **kwargs):
        started = perf_counter()
        try:
            return await self.service.prepare_patch(*args, **kwargs)
        finally:
            self.timers.add("retry_patch" if kwargs.get("attempt_number") == 2 else "patch", started)


class _TimedTestService:
    def __init__(self, service: ApprovedPatchTestService, timers: _TimerBook) -> None:
        self.service, self.timers = service, timers

    async def run_tests(self, *args, **kwargs):
        started = perf_counter()
        try:
            return await self.service.run_tests(*args, **kwargs)
        finally:
            self.timers.add("docker", started)


class _TimedCriticService:
    def __init__(self, service: CriticService, timers: _TimerBook) -> None:
        self.service, self.timers = service, timers

    async def assess_failure(self, *args, **kwargs):
        started = perf_counter()
        try:
            return await self.service.assess_failure(*args, **kwargs)
        finally:
            self.timers.add("critic", started)


class _UnavailableVectorRetriever:
    async def search_vector(self, query: str, *, k: int = 10):
        del query, k
        raise VectorRetrievalError("dense retrieval unavailable during M9; lexical production fallback used")


class _CapturingGenerationProvider:
    """Diagnostic-only observer around the unchanged production provider."""

    def __init__(self, provider: OllamaProvider) -> None:
        self._provider = provider
        self.last_output: str | None = None

    @property
    def model(self) -> str:
        return self._provider.model

    async def generate(self, prompt: str) -> str:
        output = await self._provider.generate(prompt)
        self.last_output = output
        return output

    async def generate_structured(
        self,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> str:
        output = await self._provider.generate_structured(prompt, response_schema)
        self.last_output = output
        return output


def _safe_raw_planner_output(
    output: str | None, *, failure_error_type: str | None
) -> tuple[str | None, str | None]:
    """Retain bounded public-fixture output only for a structured parse failure."""

    if output is None or failure_error_type != "PlannerOutputError":
        return None, None
    digest = sha256(output.encode("utf-8")).hexdigest()
    folded = output.casefold()
    sensitive_markers = (
        "authorization:",
        "api_key=",
        "api-key=",
        "password=",
        "bearer ",
        "private key",
    )
    if any(marker in folded for marker in sensitive_markers):
        return None, digest
    return output[:20_000], digest


async def execute_planner_diagnostic(
    case_input: ProductionCaseInput,
) -> dict[str, Any]:
    """Run one production planner start and stop before either approval resume."""

    total_started = perf_counter()
    canonical_before = fixture_fingerprint(case_input.repository_root)
    indexing_started = perf_counter()
    chunking = build_repository_chunks(case_input.repository_root)
    lexical = SQLiteLexicalIndex()
    try:
        lexical.rebuild(chunking.chunks)
        repository_indexing_ms = (perf_counter() - indexing_started) * 1000.0
        embedding_started = perf_counter()
        degradation_reason = None
        try:
            vector = ChromaVectorIndex(
                OllamaEmbeddingProvider(OllamaEmbeddingSettings.from_environment()),
                collection_name=(
                    "m9_diag_"
                    f"{sha256(case_input.case_id.encode()).hexdigest()[:16]}"
                ),
            )
            await vector.rebuild(chunking.chunks)
            vector_retriever: Any = vector
        except (EmbeddingProviderError, VectorRetrievalError, ChromaError) as exc:
            vector_retriever = _UnavailableVectorRetriever()
            degradation_reason = (
                f"Dense setup failed safely ({type(exc).__name__}); "
                "production lexical fallback used."
            )
        embedding_ms = (perf_counter() - embedding_started) * 1000.0
        retriever = HybridRetriever(
            lexical,
            vector_retriever,
            k_rrf=DEFAULT_RRF_K,
            candidate_k=DEFAULT_CANDIDATE_K,
        )
        retrieval_started = perf_counter()
        response = await retriever.search_hybrid(case_input.issue, top_k=TOP_K)
        retrieval_ms = (perf_counter() - retrieval_started) * 1000.0
        expansion = StructuralExpander(StructuralIndex(chunking.chunks)).expand(response)
        pack = ContextPacker().pack(
            case_input.issue,
            expansion,
            budget=CONTEXT_BUDGET,
        )

        settings = Settings.from_environment()
        capture = _CapturingGenerationProvider(OllamaProvider(settings))
        timers = _TimerBook()
        service = PlanReviewService(
            _TimedPlanner(StructuredPlanner(capture), timers),
            InMemorySaver(),
        )
        result = await service.start_plan_review(
            thread_id=f"m9-diagnostic-{case_input.case_id}",
            context_pack=pack,
        )
        error_type = result.error.error_type if result.error else None
        raw_output, raw_output_hash = _safe_raw_planner_output(
            capture.last_output,
            failure_error_type=error_type,
        )
        canonical_after = fixture_fingerprint(case_input.repository_root)
        record = {
            "schema_version": "repopilot.m9.planner-diagnostic.v1",
            "case_id": case_input.case_id,
            "generation_attempts": 1,
            "generation_model": settings.ollama_model,
            "generation_timeout_seconds": settings.ollama_timeout_seconds,
            "retrieval": {
                "mode": response.mode.value,
                "degraded": response.degraded,
                "degradation_reason": degradation_reason
                or response.degradation_reason,
                "ranked_files": [item.chunk.path for item in response.results],
                "ranked_symbols": [
                    item.chunk.qualified_symbol for item in response.results
                ],
            },
            "context_pack": {
                "status": pack.status.value,
                "included_chunk_count": len(pack.included_chunks),
                "excluded_candidate_count": len(pack.excluded_candidates),
                "total_token_cost": pack.total_token_cost,
                "configured_budget": pack.configured_budget,
                "files": sorted({item.path for item in pack.included_chunks}),
            },
            "workflow_status": result.status.value,
            "plan_generated": result.plan is not None,
            "approval_checkpoint_reached": (
                result.status is WorkflowStatus.AWAITING_APPROVAL
            ),
            "failure_error_type": error_type,
            "failure_message": result.error.message if result.error else None,
            "provider_error_type": (
                result.error.provider_error_type if result.error else None
            ),
            "provider_error_classification": (
                result.error.provider_error_classification if result.error else None
            ),
            "provider_error_message": (
                result.error.provider_error_message if result.error else None
            ),
            "parser_error_type": (
                "PlannerOutputError" if error_type == "PlannerOutputError" else None
            ),
            "grounding_error_type": (
                "PlanValidationError" if error_type == "PlanValidationError" else None
            ),
            "raw_model_response": raw_output,
            "raw_model_response_sha256": raw_output_hash,
            "raw_model_response_truncated": bool(
                raw_output is not None and capture.last_output is not None
                and len(capture.last_output) > len(raw_output)
            ),
            "latency_ms": {
                "repository_indexing": repository_indexing_ms,
                "embedding_index_setup": embedding_ms,
                "retrieval": retrieval_ms,
                "planner_generation": timers.total("planning"),
                "total_to_planner_boundary": (
                    perf_counter() - total_started
                )
                * 1000.0,
            },
            "canonical_fixture_unchanged": canonical_before == canonical_after,
            "patch_or_retry_executed": False,
        }
        assert_artifact_has_no_absolute_paths(record)
        return record
    finally:
        lexical.close()


async def execute_partial_retrieval(
    case_input: ProductionCaseInput, *, blocked_reason: str
) -> ExecutionObservation:
    """Measure production ingestion/retrieval while keeping repair blocked."""

    total_started = perf_counter()
    canonical_before = fixture_fingerprint(case_input.repository_root)
    indexing_started = perf_counter()
    chunking = build_repository_chunks(case_input.repository_root)
    lexical = SQLiteLexicalIndex()
    lexical.rebuild(chunking.chunks)
    repository_indexing_ms = (perf_counter() - indexing_started) * 1000.0
    vector_retriever: Any
    embedding_started = perf_counter()
    degradation_reason = None
    try:
        vector = ChromaVectorIndex(
            OllamaEmbeddingProvider(OllamaEmbeddingSettings.from_environment()),
            collection_name=f"m9_{sha256(case_input.case_id.encode()).hexdigest()[:16]}",
        )
        await vector.rebuild(chunking.chunks)
        vector_retriever = vector
    except (EmbeddingProviderError, VectorRetrievalError, ChromaError) as exc:
        vector_retriever = _UnavailableVectorRetriever()
        degradation_reason = f"Dense setup failed safely ({type(exc).__name__}); production lexical fallback used."
    embedding_ms = (perf_counter() - embedding_started) * 1000.0
    retriever = HybridRetriever(
        lexical, vector_retriever,
        k_rrf=DEFAULT_RRF_K, candidate_k=DEFAULT_CANDIDATE_K,
    )
    retrieval_started = perf_counter()
    response = await retriever.search_hybrid(case_input.issue, top_k=TOP_K)
    retrieval_ms = (perf_counter() - retrieval_started) * 1000.0
    expansion = StructuralExpander(StructuralIndex(chunking.chunks)).expand(response)
    pack = ContextPacker().pack(case_input.issue, expansion, budget=CONTEXT_BUDGET)
    lexical.close()
    return ExecutionObservation(
        case_id=case_input.case_id,
        terminal_status="infrastructure_blocked",
        failure_stage="infrastructure",
        blocked_reason=blocked_reason,
        retrieval_mode=response.mode.value,
        retrieval_degraded=response.degraded,
        degradation_reason=degradation_reason or response.degradation_reason,
        context_status=pack.status.value,
        ranked_files=tuple(item.chunk.path for item in response.results),
        ranked_symbols=tuple(item.chunk.qualified_symbol for item in response.results),
        context_files=tuple(item.path for item in pack.included_chunks),
        context_symbols=tuple(item.qualified_symbol for item in pack.included_chunks),
        canonical_repository_mutated=(fixture_fingerprint(case_input.repository_root) != canonical_before),
        latencies=StageLatencies(
            repository_indexing_ms=repository_indexing_ms,
            embedding_index_setup_ms=embedding_ms,
            retrieval_ms=retrieval_ms,
            total_workflow_ms=(perf_counter() - total_started) * 1000.0,
        ),
    )


async def execute_production_case(case_input: ProductionCaseInput) -> ExecutionObservation:
    """Run M1-M6 production components. No oracle data is accepted here."""

    total_started = perf_counter()
    timers = _TimerBook()
    canonical_before = fixture_fingerprint(case_input.repository_root)
    indexing_started = perf_counter()
    chunking = build_repository_chunks(case_input.repository_root)
    lexical = SQLiteLexicalIndex()
    lexical.rebuild(chunking.chunks)
    repository_indexing_ms = (perf_counter() - indexing_started) * 1000.0
    embedding_started = perf_counter()
    degradation_reason = None
    try:
        vector = ChromaVectorIndex(
            OllamaEmbeddingProvider(OllamaEmbeddingSettings.from_environment()),
            collection_name=f"m9_{sha256(case_input.case_id.encode()).hexdigest()[:16]}",
        )
        await vector.rebuild(chunking.chunks)
        vector_retriever: Any = vector
    except (EmbeddingProviderError, VectorRetrievalError, ChromaError) as exc:
        vector_retriever = _UnavailableVectorRetriever()
        degradation_reason = (
            f"Dense setup failed safely ({type(exc).__name__}); "
            "production lexical fallback used."
        )
    embedding_ms = (perf_counter() - embedding_started) * 1000.0
    retriever = HybridRetriever(lexical, vector_retriever, k_rrf=DEFAULT_RRF_K, candidate_k=DEFAULT_CANDIDATE_K)
    retrieval_started = perf_counter()
    response = await retriever.search_hybrid(case_input.issue, top_k=TOP_K)
    retrieval_ms = (perf_counter() - retrieval_started) * 1000.0
    expansion = StructuralExpander(StructuralIndex(chunking.chunks)).expand(response)
    pack = ContextPacker().pack(case_input.issue, expansion, budget=CONTEXT_BUDGET)
    ranked_files = tuple(item.chunk.path for item in response.results)
    ranked_symbols = tuple(item.chunk.qualified_symbol for item in response.results)
    context_files = tuple(item.path for item in pack.included_chunks)
    context_symbols = tuple(item.qualified_symbol for item in pack.included_chunks)
    generation = OllamaProvider(Settings.from_environment())

    with tempfile.TemporaryDirectory(prefix="repopilot-m9-") as temporary:
        data = Path(temporary).resolve()
        workspaces = WorkspaceManager(canonical_repository=case_input.repository_root, workspace_root=data / "workspaces")
        patch = _TimedPatchService(ApprovedPatchService(patcher=StructuredPatcher(generation), workspace_manager=workspaces), timers)
        tests = _TimedTestService(ApprovedPatchTestService(
            workspace_manager=workspaces,
            snapshot_manager=DisposableTestSnapshotManager(workspace_manager=workspaces, snapshot_root=data / "snapshots"),
            runner=DockerTestRunner(), result_store=TestResultStore(data / "test-results"),
        ), timers)
        critic = _TimedCriticService(CriticService(StructuredCritic(generation), CriticAssessmentStore(data / "critics")), timers)
        exporter = PatchExporter(export_root=data / "exports", workspace_manager=workspaces)
        service = PlanReviewService(
            _TimedPlanner(StructuredPlanner(generation), timers), InMemorySaver(),
            patch, tests,
            TestRunRequest(mode=TestMode.TARGETED, selectors=case_input.test_selectors),
            critic, exporter,
        )
        result = await service.start_plan_review(thread_id=f"m9-{case_input.case_id}", context_pack=pack)
        approval_1 = False
        final_approval = False
        decision = benchmark_plan_decision(result)
        if decision is not None:
            approval_1 = True
            result = await service.resume_plan_review(thread_id=result.thread_id, decision=decision)
        if result.status is WorkflowStatus.AWAITING_FINAL_APPROVAL:
            final_decision = benchmark_final_decision(result)
            if final_decision is not None:
                final_approval = True
                result = await service.resume_final_review(thread_id=result.thread_id, decision=final_decision)

    lexical.close()
    attempts = tuple(
        AttemptRecord(
            attempt_number=item.attempt_number, patch_hash=item.patch_hash,
            changed_files=item.changed_files, test_status=item.test_status,
            test_run_id=item.test_run_id,
        )
        for item in result.attempts
    )
    error_type = result.error.error_type if result.error else None
    stage = _failure_stage(result.status, error_type=error_type, attempts=len(result.attempts))
    blocked_reason = None
    if result.test is not None and result.test.status.value == "pytest_error":
        output = f"{result.test.stdout}\n{result.test.stderr}"
        if "ModuleNotFoundError" in output or "ImportError" in output:
            blocked_reason = "Required test dependency is unavailable in the pinned local image; no installation attempted."
        else:
            blocked_reason = result.test.failure_message or "Pytest could not execute the configured tests."
    elif result.test is not None and result.test.status.value in {
        "infrastructure_failed", "timed_out", "no_tests_collected"
    }:
        blocked_reason = result.test.failure_message or (
            f"Configured Docker test ended as {result.test.status.value}."
        )
    scope_violations = int(error_type == "PatchScopeError")
    canonical_mutated = fixture_fingerprint(case_input.repository_root) != canonical_before
    return ExecutionObservation(
        case_id=case_input.case_id, terminal_status=result.status.value,
        failure_stage=stage, blocked_reason=blocked_reason,
        failure_error_type=result.error.error_type if result.error else None,
        failure_message=result.error.message if result.error else None,
        provider_error_type=result.error.provider_error_type if result.error else None,
        provider_error_classification=(
            result.error.provider_error_classification if result.error else None
        ),
        provider_error_message=(
            result.error.provider_error_message if result.error else None
        ),
        ranked_files=ranked_files, ranked_symbols=ranked_symbols,
        retrieval_mode=response.mode.value, retrieval_degraded=response.degraded,
        degradation_reason=degradation_reason or response.degradation_reason,
        context_status=pack.status.value,
        context_files=context_files, context_symbols=context_symbols,
        plan_generated=result.plan is not None,
        plan_proposed_files=result.plan.proposed_files if result.plan else (),
        approval_1_completed=approval_1,
        approved_file_scope=result.approved_file_scope or (),
        patch_produced=result.patch is not None, patch_hash=result.patch.patch_hash if result.patch else None,
        actual_changed_files=result.patch.changed_files if result.patch else (),
        tests_passed=result.test is not None and result.test.status.value == "passed",
        final_approval_completed=final_approval,
        export_completed=result.export is not None,
        exported_patch_hash=result.export.patch_hash if result.export else None,
        attempts=attempts,
        critic_declined_retry=(
            result.status is WorkflowStatus.REPAIR_FAILED
            and result.critic_assessment is not None
            and result.critic_assessment.retry_recommended is False
        ),
        scope_violation_attempts=scope_violations,
        stale_hash_failures=int(error_type in {"StaleApprovalError", "ApprovalDecisionError"}),
        patch_validation_failures=int(error_type in {"PatchValidationError", "PatchScopeError"}),
        canonical_repository_mutated=canonical_mutated,
        export_only_after_final_approval=result.export is None or final_approval,
        candidate_diff=result.patch.unified_diff if result.patch else None,
        latencies=StageLatencies(
            repository_indexing_ms=repository_indexing_ms,
            embedding_index_setup_ms=embedding_ms, retrieval_ms=retrieval_ms,
            planning_generation_ms=timers.total("planning"),
            patch_generation_ms=timers.total("patch"), docker_testing_ms=timers.total("docker"),
            critic_generation_ms=timers.total("critic"), retry_patch_generation_ms=timers.total("retry_patch"),
            total_workflow_ms=(perf_counter() - total_started) * 1000.0,
        ),
    )


def _failure_stage(
    status: WorkflowStatus, *, error_type: str | None, attempts: int
) -> str | None:
    if status is WorkflowStatus.PATCH_FAILED:
        if error_type == "PatchInferenceError":
            return "retry patch" if attempts else "patch generation"
        return "retry patch" if attempts else "patch validation"
    if status is WorkflowStatus.REPAIR_FAILED:
        return "Docker test" if attempts >= 2 else "critic"
    mapping = {
        WorkflowStatus.PLANNER_FAILED: "planner",
        WorkflowStatus.VALIDATION_FAILED: "approval #1 validation",
        WorkflowStatus.TESTS_FAILED: "Docker test",
        WorkflowStatus.TEST_INFRASTRUCTURE_FAILED: "infrastructure",
        WorkflowStatus.CRITIC_FAILED: "critic",
        WorkflowStatus.EXPORT_FAILED: "export",
        WorkflowStatus.FINAL_REJECTED: "final approval",
    }
    return mapping.get(status)


async def run_real_evaluation(manifest: M9Manifest, *, fixture_root: Path) -> dict[str, Any]:
    fixture_records = materialize_manifest(manifest, cache_root=fixture_root.parents[1], allow_network=False, create=False)
    if not all(item["valid"] for item in fixture_records):
        raise ValueError("M9 fixtures are absent or do not match the frozen manifest")
    checks = await preflight()
    observations: list[ExecutionObservation] = []
    fixture_validation: list[dict[str, Any]] = []
    if not checks["ready"]:
        reason = checks["docker"].get("reason") or checks["ollama"].get("reason") or "M9 prerequisites unavailable"
        observations = [
            ExecutionObservation(case_id=case.case_id, terminal_status="infrastructure_blocked", failure_stage="infrastructure", blocked_reason=reason)
            for case in manifest.cases
        ]
    else:
        fixture_validation = await verify_fixture_tests(
            manifest,
            fixture_root=fixture_root,
        )
        validation_by_id = {item["case_id"]: item for item in fixture_validation}
        for case in manifest.cases:
            if not validation_by_id[case.case_id]["valid"]:
                validation = validation_by_id[case.case_id]
                if not validation["manifest_fingerprint_valid"]:
                    reason = "Frozen fixture fingerprint did not match the manifest."
                elif not validation["controlled_defect_present"]:
                    reason = "Frozen fixture did not contain its controlled defect."
                elif not validation["canonical_fixture_unchanged"]:
                    reason = "Pre-repair validation mutated the canonical fixture."
                else:
                    reason = "Configured pre-repair selector passed; the frozen repair case is invalid."
                observations.append(
                    ExecutionObservation(
                        case_id=case.case_id,
                        terminal_status="benchmark_fixture_invalid",
                        failure_stage="fixture validation",
                        blocked_reason=reason,
                    )
                )
                continue
            production_input = ProductionCaseInput.from_case(case, fixture_root=fixture_root)
            try:
                observations.append(await execute_production_case(production_input))
            except Exception as exc:
                observations.append(ExecutionObservation(
                    case_id=case.case_id, terminal_status="infrastructure_blocked",
                    failure_stage="infrastructure", blocked_reason=f"Production execution failed safely ({type(exc).__name__}).",
                ))
    return build_artifact(
        manifest,
        observations,
        evaluation_mode="real",
        preflight_record=checks,
        fixture_validation=fixture_validation,
    )


def run_fake_evaluation(manifest: M9Manifest) -> dict[str, Any]:
    observations = []
    for index, case in enumerate(manifest.cases):
        gold_file = case.evaluation_oracle.gold_changed_files[0]
        gold_symbol = case.evaluation_oracle.gold_symbols[0]
        if index == len(manifest.cases) - 1:
            observations.append(ExecutionObservation(case_id=case.case_id, terminal_status="infrastructure_blocked", failure_stage="infrastructure", blocked_reason="deterministic fake infrastructure block"))
            continue
        attempts = (
            AttemptRecord(attempt_number=1, patch_hash="a" * 64, changed_files=(gold_file,), test_status="failed", test_run_id="1" * 64),
            AttemptRecord(attempt_number=2, patch_hash="b" * 64, changed_files=(gold_file,), test_status="passed", test_run_id="2" * 64),
        ) if index == 1 else (
            AttemptRecord(attempt_number=1, patch_hash="a" * 64, changed_files=(gold_file,), test_status="passed", test_run_id="1" * 64),
        )
        final_hash = attempts[-1].patch_hash
        observations.append(ExecutionObservation(
            case_id=case.case_id, terminal_status="completed", ranked_files=(gold_file,), ranked_symbols=(gold_symbol,),
            context_files=(gold_file,), context_symbols=(gold_symbol,), plan_generated=True,
            plan_proposed_files=(gold_file,), approval_1_completed=True, approved_file_scope=(gold_file,),
            patch_produced=True, patch_hash=final_hash, actual_changed_files=(gold_file,), tests_passed=True,
            final_approval_completed=True, export_completed=True, exported_patch_hash=final_hash,
            attempts=attempts, candidate_diff="alternate behaviorally valid fake patch",
            latencies=StageLatencies(repository_indexing_ms=1, embedding_index_setup_ms=2, retrieval_ms=3, planning_generation_ms=4, patch_generation_ms=5, docker_testing_ms=6, critic_generation_ms=1 if index == 1 else None, retry_patch_generation_ms=5 if index == 1 else None, total_workflow_ms=20),
        ))
    fake_preflight = {"ready": False, "docker": {"reason": "deterministic fake"}, "ollama": {"reason": "deterministic fake"}}
    return build_artifact(manifest, observations, evaluation_mode="deterministic_fake", preflight_record=fake_preflight)


def build_artifact(
    manifest: M9Manifest,
    observations: list[ExecutionObservation],
    *,
    evaluation_mode: str,
    preflight_record: dict[str, Any],
    fixture_validation: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    by_id = {item.case_id: item for item in observations}
    if set(by_id) != {item.case_id for item in manifest.cases}:
        raise ValueError("each frozen case must have exactly one observation")
    cases = [score_case(case, by_id[case.case_id]) for case in manifest.cases]
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "evaluation_name": "M9 frozen external repository and system evaluation",
        "evaluation_scope": "controlled_external_system_evaluation",
        "evaluation_mode": evaluation_mode,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_fingerprint": manifest.fingerprint,
        "artifact_identity": sha256(json.dumps({"schema": SCHEMA_VERSION, "manifest": manifest.fingerprint, "mode": evaluation_mode, "git": _git_commit(), "generation_model": GENERATION_MODEL, "embedding_model": EMBEDDING_MODEL, "image": TEST_IMAGE}, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "repopilot_commit": _git_commit(),
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "unavailable",
            "logical_cpu_count": os.cpu_count(),
            "memory_bytes": None,
            "memory_note": "Host physical memory was not measured; Docker enforced the configured per-test memory limit.",
            "generation_runtime": "local CPU",
        },
        "models": preflight_record.get("ollama", {}).get("models", []),
        "configuration": {"generation_model": GENERATION_MODEL, "embedding_model": EMBEDDING_MODEL, "test_image": TEST_IMAGE, "rrf_k": DEFAULT_RRF_K, "candidate_k": DEFAULT_CANDIDATE_K, "top_k": TOP_K, "context_budget": CONTEXT_BUDGET, "maximum_patch_attempts": 2},
        "preflight": preflight_record,
        "fixture_validation": fixture_validation or [],
        "repositories": [item.model_dump(mode="json") for item in manifest.repositories],
        "case_provenance": [{"case_id": item.case_id, "repository_id": item.repository_id, "case_type": item.case_type, "fixture_fingerprint": item.fixture_fingerprint, "evaluation_mode": item.evaluation_mode, "required_test_selectors": list(item.required_test_selectors), "acquisition_provenance": item.acquisition_provenance} for item in manifest.cases],
        "cases": cases,
        "aggregate": aggregate_scores(cases),
        "limitations": ["Six controlled-defect cases across three external repositories are a small controlled sample.", "Controlled mutations are not historical real-world bugs.", "This is not SWE-bench or production-scale evidence.", "Gold labels were used only for post-hoc scoring, never workflow decisions.", "Slow CPU-local generation is not classified as repair failure."],
    }
    assert_artifact_has_no_absolute_paths(artifact)
    return artifact


def write_artifacts(artifact: dict[str, Any], *, output_dir: Path) -> None:
    root = output_dir.resolve()
    if root == REPOSITORY_ROOT or not root.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("M9 output directory must be a nested repository path")
    assert_artifact_has_no_absolute_paths(artifact)
    root.mkdir(parents=True, exist_ok=True)
    (root / "m9-results.json").write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _write_report_only(artifact, root)


def _write_report_only(artifact: dict[str, Any], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    diagnosis_path = root / DIAGNOSIS_FILENAME
    diagnosis = (
        json.loads(diagnosis_path.read_text(encoding="utf-8"))
        if diagnosis_path.exists()
        else None
    )
    if diagnosis is not None:
        assert_artifact_has_no_absolute_paths(diagnosis)
    (root / "m9-report.md").write_text(
        render_report(artifact, diagnosis=diagnosis),
        encoding="utf-8",
        newline="\n",
    )


def render_report(
    artifact: dict[str, Any], *, diagnosis: dict[str, Any] | None = None
) -> str:
    aggregate = artifact["aggregate"]
    lines = [
        "# M9 Frozen External Repository + System Evaluation", "",
        "> Controlled external-repository evaluation only. This is not SWE-bench or production-scale evidence.", "",
    ]
    if diagnosis is not None:
        original = diagnosis["original_five_attempts"]
        confirmation = diagnosis["confirmation_diagnostic"]
        lines.extend([
            "## Post-run Task 019C diagnosis", "",
            f"The five original planner-stage attempts are now classified post-hoc as "
            f"`{original['post_hoc_classification']}`: the retained Ollama log "
            "ties every generation request to Vulkan device loss and HTTP 500. "
            "The historical 0/5 artifact is preserved, but it is not valid repair-quality evidence.", "",
            "One separately labeled confirmation generation returned a schema-valid plan, "
            f"then failed grounding as `{confirmation['grounding_error_type']}`: "
            f"`{confirmation['failure_message']}`. No patch or retry ran. A clean full M9 "
            "rerun is scientifically justified but was not performed in Task 019C.", "",
        ])
    if artifact.get("manifest_fingerprint") == M9_V2_MANIFEST_FINGERPRINT:
        lines.extend([
            "## Final M9 v2 measurement", "",
            "M9 v1 remains historical and is not repair-quality evidence: its five "
            "generation attempts were invalidated by retained Vulkan device-loss/HTTP-500 "
            "evidence, and its sixth case used a non-discriminating pre-repair selector. "
            "M9 v2 is the clean frozen benchmark-data repair: all six selectors failed "
            "before repair and every canonical fixture remained unchanged.", "",
            "The v2 run used the locked models and `REPOPILOT_OLLAMA_TIMEOUT_SECONDS=600`. "
            "Ollama `/api/ps` reported `size_vram=0` for Gemma before and repeatedly "
            "during the run, confirming 100% CPU placement and preventing the known GPU "
            "runtime path. No RepoPilot prompt, retrieval, context-budget, model, schema, "
            "grounding, or retry-policy tuning occurred between diagnosis and this run. "
            "Each frozen case ran exactly once, with no benchmark-level retry or manual "
            "repair.", "",
        ])
    lines.extend([
        "## 1. Setup", "",
        f"- Repositories/cases: `{len(artifact['repositories'])}` / `{len(artifact['cases'])}`",
        "- Case type: external-repository controlled-defect cases (no historical cases)",
        f"- Generation / embedding: `{artifact['configuration']['generation_model']}` / `{artifact['configuration']['embedding_model']}`",
        f"- Docker image: `{artifact['configuration']['test_image']}`",
        f"- Docker image ID: `{artifact.get('preflight', {}).get('docker', {}).get('image_id') or 'not available'}`",
        f"- Runtime: Python `{artifact['environment']['python_version']}` on `{artifact['environment']['platform']}`; logical CPUs `{artifact['environment']['logical_cpu_count']}`; memory `{_fmt(artifact['environment']['memory_bytes'])}`",
        f"- Evaluation mode: `{artifact['evaluation_mode']}`", "",
        "Repositories:", "",
    ])
    for repository in artifact["repositories"]:
        lines.append(
            f"- `{repository['name']}` at `{repository['commit_sha']}` "
            f"(`{repository['license_identifier']}`)"
        )
    lines.extend([
        "", "Locked model identities:", "",
    ])
    for model in artifact.get("models", []):
        lines.append(f"- `{model['name']}`: `{model['digest']}`")
    lines.extend([
        "",
        "## 2. End-to-end results", "",
        "| Case | Repo | Retrieval | Plan | Patch #1 | Test #1 | Critic | Patch #2 | Test #2 | Final | Result |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ])
    for case in artifact["cases"]:
        attempts = case["attempts"]
        test1 = attempts[0]["test_status"] if attempts else "not run"
        test2 = attempts[1]["test_status"] if len(attempts) > 1 else "not run"
        patch1 = "yes" if attempts else "no"
        patch2 = "yes" if len(attempts) > 1 else "no"
        critic = (
            "declined" if case.get("critic_declined_retry") else
            "used" if len(attempts) > 1 else
            "not run"
        )
        retrieval = (
            case["retrieval"].get("mode")
            if case["retrieval"].get("measured")
            else "not run"
        )
        lines.append(
            f"| `{case['case_id']}` | `{case['repository_id']}` | {retrieval} | "
            f"{_yes(case['plan_generated'])} | {patch1} | {test1} | {critic} | "
            f"{patch2} | {test2} | {_yes(case['final_approval_completed'])} | "
            f"`{case['attempt_classification']}` |"
        )
    lines.extend([
        "", "## 3. Aggregate repair results", "",
        f"Valid/attempted/completed: `{aggregate.get('valid_case_count', len(artifact['cases']))}` / `{aggregate['cases_attempted']}` / `{aggregate['cases_completed']}`. Repair successes: `{aggregate.get('repair_success_count', aggregate['cases_completed'])}`; repair success rate: `{_fmt(aggregate['repair_success_rate'])}`; attempt-1 rate: `{_fmt(aggregate['attempt_1_success_rate'])}`; retry-used rate: `{_fmt(aggregate['retry_used_rate'])}`; attempt-2 recovery rate: `{_fmt(aggregate['attempt_2_success_rate'])}`; terminal failure rate: `{_fmt(aggregate['terminal_repair_failure_rate'])}`; infrastructure blocked: `{aggregate['infrastructure_blocked_count']}`; invalid frozen fixtures: `{aggregate.get('benchmark_fixture_invalid_count', 0)}`.",
        "Repair success requires a produced patch, passing configured tests for that exact patch, final approval, exact export, unchanged canonical input, and no critical scope/authority breach.",
        f"Patch scope diagnostics across attempted cases: changed-file cases `{aggregate.get('patch_quality', {}).get('cases_with_changed_files', 0)}`, exact gold-file scopes `{aggregate.get('patch_quality', {}).get('exact_gold_file_scope_count', 0)}`, extra files `{aggregate.get('patch_quality', {}).get('extra_changed_file_count', 0)}`, missing gold files `{aggregate.get('patch_quality', {}).get('missing_gold_file_count', 0)}`, behavioral successes `{aggregate.get('patch_quality', {}).get('behavioral_success_count', 0)}`.",
        "", "## 4. Retrieval", "",
        f"Post-hoc gold file Hit@1/Hit@5/MRR: `{_fmt(aggregate['retrieval']['gold_file_hit_at_1'])}` / `{_fmt(aggregate['retrieval']['gold_file_hit_at_5'])}` / `{_fmt(aggregate['retrieval']['file_mrr'])}`. Context gold-file/symbol coverage: `{_fmt(aggregate['retrieval']['gold_file_context_coverage'])}` / `{_fmt(aggregate['retrieval']['gold_symbol_context_coverage'])}`. M8 was synthetic retrieval-only evidence; M9 does not reuse M8 labels.",
        f"Retrieval modes: `{json.dumps(aggregate.get('retrieval_mode_counts', {}), sort_keys=True)}`. Lexical fallback is recorded as current production behavior, not infrastructure invalidation.",
        "", "## 5. Failure analysis", "",
        f"Failure-stage counts: `{json.dumps(aggregate['failure_stage_counts'], sort_keys=True)}`. Per-case bounded reasons are retained in the JSON artifact.",
    ])
    planner = aggregate.get("planner_outcomes", {})
    patch_test = aggregate.get("patch_test", {})
    lines.extend([
        "",
        "Planner outcomes: "
        f"valid grounded plans `{planner.get('valid_grounded_plans', 0)}`, "
        f"structured-output parse failures `{planner.get('output_parse_failures', 0)}`, "
        f"grounding failures `{planner.get('grounding_failures', 0)}`, "
        f"provider failures `{planner.get('provider_failures', 0)}`.",
        "",
        "Patch/test outcomes: "
        f"cases reaching patch generation `{patch_test.get('cases_reaching_patch_generation', 0)}`, "
        f"valid patches `{patch_test.get('cases_producing_valid_patches', 0)}`, "
        f"Docker repair-test passes/failures `{patch_test.get('docker_test_passes', 0)}` / "
        f"`{patch_test.get('docker_test_failures', 0)}`.",
    ])
    lines.append("")
    for case in artifact["cases"]:
        if case["failure_stage"] is not None:
            lines.append(
                f"- `{case['case_id']}`: `{case['failure_stage']}` - "
                f"{case.get('failure_message') or case['blocked_reason'] or case['terminal_status']}"
            )
    lines.extend([
        "", "## 6. Safety", "",
        f"Critical authority/scope/workspace violation observed: `{str(aggregate['critical_safety_failure']).lower()}`. Scope attempts `{aggregate.get('safety', {}).get('scope_violation_attempts', 0)}`, stale/hash failures `{aggregate.get('safety', {}).get('stale_hash_failures', 0)}`, patch-validation failures `{aggregate.get('safety', {}).get('patch_validation_failures', 0)}`, canonical mutations `{aggregate.get('safety', {}).get('canonical_repository_mutation_count', 0)}`, retry-limit violations `{aggregate.get('safety', {}).get('retry_limit_violation_count', 0)}`, export-order failures `{aggregate.get('safety', {}).get('export_order_failure_count', 0)}`. The five planner failures did not reach approval, patch, Docker repair-test, or export; the one grounded plan reached approval #1 and patch generation, then failed deterministic patch validation before testing. The pre-repair Docker fixture tests did exercise the M5 sandbox. Safety is fail-loud and is never averaged.",
        "", "## 7. Latency", "",
        "Per-case indexing, embedding setup, retrieval, planner, patcher, Docker, critic, retry patcher, and total wall-clock timings follow in milliseconds; p95 is reported only at n>=5.",
    ])
    lines.extend([
        "",
        "| Case | Index | Embed | Retrieve | Planner | Patcher | Tests | Critic | Retry patch | Total |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for case in artifact["cases"]:
        latency = case["latency_ms"]
        lines.append(
            f"| `{case['case_id']}` | {_fmt(latency['repository_indexing_ms'])} | "
            f"{_fmt(latency['embedding_index_setup_ms'])} | {_fmt(latency['retrieval_ms'])} | "
            f"{_fmt(latency['planning_generation_ms'])} | {_fmt(latency['patch_generation_ms'])} | "
            f"{_fmt(latency['docker_testing_ms'])} | {_fmt(latency['critic_generation_ms'])} | "
            f"{_fmt(latency['retry_patch_generation_ms'])} | {_fmt(latency['total_workflow_ms'])} |"
        )
    lines.extend(["", "Aggregate latency:", ""])
    for name, values in aggregate["latency_ms"].items():
        lines.append(
            f"- `{name}`: n=`{values['count']}`, median=`{_fmt(values['median'])}`, p95=`{_fmt(values['p95'])}`"
        )
    lines.extend([
        "", "## 8. Limitations", "",
        "- Only six frozen cases across three repositories were defined; all six were valid controlled-defect cases in v2.",
        "- Every case is a controlled defect, not a historical bug.",
        "- This is not SWE-bench and is not representative of arbitrary Python repositories.",
        "- CPU-local generation is slow.",
        "", "## 9. M10 candidates", "",
        "- Diagnose the measured 60-second dense-index timeout on the four larger fixtures; those cases used the existing lexical fallback.",
        "- Analyze the five measured planner-stage failures using typed failure evidence retained by subsequent runs; do not rerun M9 for score shopping.",
        "- Investigate why grounded patch generation produced output that deterministic patch validation rejected, without weakening validation.",
        "- Preserve the byte-offset line-accounting regression for large Tree-sitter inputs.", "",
    ])
    docker_reason = artifact.get("preflight", {}).get("docker", {}).get("reason")
    if docker_reason:
        lines.extend(["## Real-run blocker", "", f"M9 real end-to-end execution blocked by Docker prerequisite: {docker_reason}", ""])
    return "\n".join(lines)


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def _fmt(value: Any) -> str:
    return "not measured" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)


def _git_commit() -> str | None:
    try:
        value = _git_output(["-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"])
    except (OSError, subprocess.SubprocessError):
        return None
    return value if len(value) == 40 else None


def _git_commit_exists(checkout: Path, commit: str) -> bool:
    result = subprocess.run(["git", "-C", str(checkout), "cat-file", "-e", f"{commit}^{{commit}}"], check=False, capture_output=True, text=True, timeout=15, shell=False)
    return result.returncode == 0


def _git_output(arguments: list[str]) -> str:
    return subprocess.run(["git", *arguments], check=True, capture_output=True, text=True, timeout=60, shell=False).stdout.strip()


def _run_git(arguments: list[str]) -> None:
    subprocess.run(["git", *arguments], check=True, capture_output=True, text=True, timeout=180, shell=False)


if __name__ == "__main__":
    raise SystemExit(main())
