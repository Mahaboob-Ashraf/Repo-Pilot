"""Offline Gemini provider, factory, integration, and safety regressions."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
import traceback
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GENERATION_PROVIDER,
    OllamaEmbeddingSettings,
    Settings,
)
from app.critic import StructuredCritic
from app.patching import (
    ApprovedPatchService,
    PatchEdit,
    PatchProposal,
    PatchScopeError,
    PatchValidationError,
    StructuredPatcher,
    WorkspaceManager,
)
from app.planning import (
    PlanValidationError,
    PlanningContextSnapshot,
    StructuredPlanner,
    repair_plan_hash,
)
from app.providers.base import (
    InferenceProviderError,
    InferenceResponseError,
    InferenceUnavailableError,
)
from app.providers.factory import build_generation_provider
from app.providers.gemini import GeminiProvider
from app.providers.ollama import OllamaProvider
from tests.patching_fakes import copy_toy_repository, patch_inputs
from tests.planning_fakes import make_context_pack, make_valid_plan
from tests.sandbox_fakes import FakeTestRunner, make_patched_workspace
from app.sandbox import TestMode as SandboxTestMode, TestStatus as SandboxTestStatus
from app.critic import CriticAssessment, RetryInstruction


@dataclass
class _Usage:
    prompt_token_count: int = 11
    candidates_token_count: int = 7
    total_token_count: int = 18


@dataclass
class _Response:
    text: str | None
    usage_metadata: _Usage | None = None


class _Models:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = list(responses or [])
        self.generate_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []

    async def generate_content(self, **kwargs):
        self.generate_calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected Gemini generation")
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    async def get(self, *, model: str):
        self.get_calls.append(model)
        return SimpleNamespace(name=f"models/{model}")

    async def list(self):
        async def items():
            for name in (
                "models/gemini-3.5-flash",
                "models/gemini-3.5-pro",
                "models/embedding-001",
            ):
                yield SimpleNamespace(
                    name=name,
                    supported_actions=("generateContent",),
                )

        return items()


class _ClientContext(AbstractAsyncContextManager[Any]):
    def __init__(self, models: _Models) -> None:
        self.client = SimpleNamespace(models=models)

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _provider(*responses: Any, key: str = "test-secret") -> tuple[GeminiProvider, _Models]:
    models = _Models(list(responses))
    provider = GeminiProvider(
        Settings(
            generation_provider="gemini",
            gemini_api_key=key,
            gemini_model="gemini-test-model",
            gemini_timeout_seconds=3.0,
        ),
        _client_factory=lambda: _ClientContext(models),
    )
    return provider, models


def test_gemini_provider_loads_exact_configured_model_and_safe_identity() -> None:
    provider, models = _provider(_Response("ok"))

    assert asyncio.run(provider.check_model_access()) == "gemini-test-model"
    assert provider.provider_name == "gemini"
    assert provider.model == "gemini-test-model"
    assert models.get_calls == ["gemini-test-model"]


def test_gemini_provider_lists_only_generation_capable_gemini_models() -> None:
    provider, _models = _provider()

    assert asyncio.run(provider.list_suitable_models()) == (
        "gemini-3.5-flash",
        "gemini-3.5-pro",
    )


def test_missing_gemini_key_fails_safely() -> None:
    with pytest.raises(InferenceProviderError, match="API key is not configured"):
        GeminiProvider(Settings(generation_provider="gemini", gemini_api_key=None))


def test_api_key_never_appears_in_settings_provider_or_error_trace() -> None:
    secret = "super-secret-key-value"
    provider, _models = _provider(RuntimeError(secret), key=secret)

    with pytest.raises(InferenceProviderError) as raised:
        asyncio.run(provider.generate("hello"))

    rendered = "".join(
        (
            repr(Settings(generation_provider="gemini", gemini_api_key=secret)),
            repr(provider),
            "".join(traceback.format_exception(raised.value)),
        )
    )
    assert secret not in rendered
    assert str(raised.value) == "Gemini provider failed"


def test_plain_generation_maps_text_and_safe_token_usage() -> None:
    provider, models = _provider(_Response("plain answer", _Usage()))

    assert asyncio.run(provider.generate("hello")) == "plain answer"
    assert models.generate_calls == [
        {
            "model": "gemini-test-model",
            "contents": "hello",
            "config": {"temperature": 0},
        }
    ]
    assert provider.last_usage is not None
    assert provider.last_usage.total_tokens == 18


def test_native_schema_is_sent_without_sdk_objects_escaping() -> None:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    provider, models = _provider(_Response('{"answer":"ok"}'))

    result = asyncio.run(provider.generate_structured("structured", schema))

    assert result == '{"answer":"ok"}'
    assert models.generate_calls[0]["config"] == {
        "temperature": 0,
        "response_mime_type": "application/json",
        "response_json_schema": schema,
    }


@pytest.mark.parametrize("text", [None, "", "   "])
def test_malformed_provider_response_fails_safely(text) -> None:
    provider, _models = _provider(_Response(text))

    with pytest.raises(
        InferenceResponseError,
        match="Gemini response did not contain generated text",
    ):
        asyncio.run(provider.generate("hello"))


def test_timeout_maps_to_unavailable_error() -> None:
    provider, _models = _provider(asyncio.TimeoutError("private transport detail"))

    with pytest.raises(InferenceUnavailableError, match="Gemini API is unavailable"):
        asyncio.run(provider.generate("hello"))


def test_planner_works_unchanged_and_rejects_invented_citation() -> None:
    pack = make_context_pack()
    valid = make_valid_plan(pack)
    provider, models = _provider(_Response(valid.model_dump_json()))

    assert asyncio.run(StructuredPlanner(provider).create_plan(pack)) == valid
    assert models.generate_calls[0]["config"]["response_json_schema"]

    invented = valid.model_copy(
        update={
            "steps": (
                valid.steps[0].model_copy(
                    update={"evidence_chunk_ids": ("invented-chunk",)}
                ),
            )
        }
    )
    bad_provider, _ = _provider(_Response(invented.model_dump_json()))
    with pytest.raises(PlanValidationError, match="unknown chunk"):
        asyncio.run(StructuredPlanner(bad_provider).create_plan(pack))


def test_patcher_works_unchanged_through_gemini(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    provider, models = _provider(_Response(proposal.model_dump_json()))

    actual = asyncio.run(
        StructuredPatcher(provider).create_patch(
            context=PlanningContextSnapshot.from_context_pack(pack),
            approved_plan=plan,
            approved_plan_hash=repair_plan_hash(plan),
            approved_files=plan.proposed_files,
        )
    )

    assert actual == proposal
    assert models.generate_calls[0]["config"]["response_json_schema"]


def test_critic_works_unchanged_through_gemini(tmp_path) -> None:
    _repository, pack, plan, patch, _manager, _service = make_patched_workspace(tmp_path)
    context = PlanningContextSnapshot.from_context_pack(pack)
    test_result = asyncio.run(
        FakeTestRunner(status=SandboxTestStatus.FAILED, exit_code=1).run(
            SimpleNamespace(
                test_run_id="a" * 64,
                patch=patch,
                mode=SandboxTestMode.FULL,
                validated_selectors=(),
                execution_repository=tmp_path,
            )
        )
    )
    evidence = next(item for item in context.evidence if item.path == "pricing.py")
    expected = CriticAssessment(
        summary="The formula is still incorrect.",
        failure_diagnosis="The attempted arithmetic did not satisfy the test.",
        retry_recommended=True,
        retry_instructions=(
            RetryInstruction(
                description="Correct the approved pricing formula.",
                affected_files=("pricing.py",),
            ),
        ),
        evidence_chunk_ids=(evidence.chunk_id,),
    )
    provider, models = _provider(_Response(expected.model_dump_json()))

    actual = asyncio.run(
        StructuredCritic(provider).assess(
            context=context,
            approved_plan=plan,
            approved_plan_hash=repair_plan_hash(plan),
            approved_files=plan.proposed_files,
            patch=patch,
            test_result=test_result,
            attempt_number=1,
        )
    )

    assert actual == expected
    assert models.generate_calls[0]["config"]["response_json_schema"]


@pytest.mark.parametrize(
    ("edit", "expected_error"),
    [
        (
            PatchEdit(
                path="tests/test_pricing.py",
                expected_old_text="assert apply_discount(50.0, 0.0) == 50.0",
                replacement_text="assert False",
                evidence_chunk_ids=("placeholder",),
                rationale="Outside approved scope.",
            ),
            PatchScopeError,
        ),
        (
            PatchEdit(
                path="pricing.py",
                expected_old_text="text that is not in the approved source",
                replacement_text="replacement",
                evidence_chunk_ids=("placeholder",),
                rationale="Invalid exact match.",
            ),
            PatchValidationError,
        ),
    ],
)
def test_gemini_output_cannot_bypass_scope_or_exact_match(
    tmp_path, edit: PatchEdit, expected_error: type[Exception]
) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, valid = patch_inputs(repository)
    function = next(item for item in pack.included_chunks if item.path == "pricing.py")
    test_evidence = next(
        item for item in pack.included_chunks if item.path == "tests/test_pricing.py"
    )
    citation = (
        test_evidence.chunk_id
        if edit.path == "tests/test_pricing.py"
        else function.chunk_id
    )
    proposal = PatchProposal(
        summary=valid.summary,
        edits=(edit.model_copy(update={"evidence_chunk_ids": (citation,)}),),
    )
    provider, _models = _provider(_Response(proposal.model_dump_json()))
    service = ApprovedPatchService(
        patcher=StructuredPatcher(provider),
        workspace_manager=WorkspaceManager(
            canonical_repository=repository,
            workspace_root=(tmp_path / "workspaces").resolve(),
        ),
    )

    with pytest.raises(expected_error):
        asyncio.run(
            service.prepare_patch(
                thread_id="gemini-safety",
                workflow_status="approved_for_patch",
                approval_plan_hash=repair_plan_hash(plan),
                approved_plan=plan,
                approved_plan_hash=repair_plan_hash(plan),
                approved_files=plan.proposed_files,
                context=PlanningContextSnapshot.from_context_pack(pack),
            )
        )


def test_provider_factory_defaults_to_ollama_and_selects_gemini_explicitly() -> None:
    assert DEFAULT_GENERATION_PROVIDER == "ollama"
    assert DEFAULT_GEMINI_MODEL == "gemini-3.1-flash-lite"
    assert isinstance(build_generation_provider(Settings()), OllamaProvider)
    selected = build_generation_provider(
        Settings(generation_provider="gemini", gemini_api_key="test-secret")
    )
    assert isinstance(selected, GeminiProvider)


def test_embeddinggemma_configuration_is_independent() -> None:
    generation = Settings(
        generation_provider="gemini",
        gemini_api_key="test-secret",
        gemini_model="gemini-test-model",
    )
    embeddings = OllamaEmbeddingSettings(
        ollama_embedding_model="embeddinggemma:latest"
    )

    assert build_generation_provider(generation).model == "gemini-test-model"
    assert embeddings.ollama_embedding_model == "embeddinggemma:latest"
