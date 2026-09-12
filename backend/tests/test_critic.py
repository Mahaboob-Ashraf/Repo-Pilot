"""Focused offline tests for the bounded M6 critic."""

from __future__ import annotations

import asyncio

import pytest

from app.critic import (
    CriticAssessment,
    CriticAssessmentStore,
    CriticService,
    CriticOutputError,
    CriticValidationError,
    RetryInstruction,
    StructuredCritic,
    validate_critic_grounding,
)
from app.planning import PlanningContextSnapshot, repair_plan_hash
from app.sandbox import TestStatus as SandboxStatus
from tests.planning_fakes import FakeInferenceProvider
from tests.sandbox_fakes import FakeTestRunner, make_patched_workspace


def _assessment(context, *, retry=True, files=("pricing.py",), description="Correct the formula."):
    evidence = next(item for item in context.evidence if item.path == "pricing.py")
    return CriticAssessment(
        summary="The attempted calculation remains incorrect.",
        failure_diagnosis="The percentage is not subtracted in full.",
        retry_recommended=retry,
        retry_instructions=(
            (RetryInstruction(description=description, affected_files=files),)
            if retry else ()
        ),
        evidence_chunk_ids=(evidence.chunk_id,),
    )


def _inputs(tmp_path):
    _repo, pack, plan, artifact, _manager, _service = make_patched_workspace(tmp_path)
    context = PlanningContextSnapshot.from_context_pack(pack)
    test = asyncio.run(FakeTestRunner(status=SandboxStatus.FAILED, exit_code=1).run(
        type("Spec", (), {
            "test_run_id": "a" * 64, "patch": artifact,
            "mode": __import__("app.sandbox", fromlist=["TestMode"]).TestMode.FULL,
            "validated_selectors": (), "execution_repository": tmp_path,
        })()
    ))
    return context, plan, artifact, test


def test_prompt_contains_all_bounded_inputs_and_untrusted_labels(tmp_path) -> None:
    context, plan, patch, test = _inputs(tmp_path)
    critic = StructuredCritic(FakeInferenceProvider(_assessment(context).model_dump_json()))
    prompt = critic.render_prompt(
        context=context, approved_plan=plan, approved_plan_hash=repair_plan_hash(plan),
        approved_files=plan.proposed_files, patch=patch, test_result=test,
        attempt_number=1,
    )
    assert context.issue_text in prompt
    assert plan.summary in prompt
    assert patch.patch_hash in prompt and patch.unified_diff in prompt
    assert test.stdout in prompt and test.stderr in prompt
    assert "untrusted" in prompt.lower()
    assert "advisory only" in prompt


def test_valid_output_parses_and_is_grounded(tmp_path) -> None:
    context, plan, patch, test = _inputs(tmp_path)
    expected = _assessment(context)
    provider = FakeInferenceProvider(expected.model_dump_json())
    actual = asyncio.run(StructuredCritic(provider).assess(
        context=context, approved_plan=plan, approved_plan_hash=repair_plan_hash(plan),
        approved_files=plan.proposed_files, patch=patch, test_result=test,
        attempt_number=1,
    ))
    assert actual == expected
    assert provider.calls == 1


def test_malformed_critic_output_fails_explicitly(tmp_path) -> None:
    context, plan, patch, test = _inputs(tmp_path)
    with pytest.raises(CriticOutputError):
        asyncio.run(StructuredCritic(FakeInferenceProvider("not-json")).assess(
            context=context, approved_plan=plan,
            approved_plan_hash=repair_plan_hash(plan), approved_files=plan.proposed_files,
            patch=patch, test_result=test, attempt_number=1,
        ))


def test_critic_schema_rejects_model_defined_plan_or_scope_authority(tmp_path) -> None:
    context, plan, patch, test = _inputs(tmp_path)
    payload = _assessment(context).model_dump(mode="json")
    payload["approved_plan_hash"] = "0" * 64
    payload["approved_files"] = ["invented.py"]
    provider = FakeInferenceProvider(__import__("json").dumps(payload))
    with pytest.raises(CriticOutputError):
        asyncio.run(StructuredCritic(provider).assess(
            context=context, approved_plan=plan,
            approved_plan_hash=repair_plan_hash(plan), approved_files=plan.proposed_files,
            patch=patch, test_result=test, attempt_number=1,
        ))


def test_invented_citation_is_rejected(tmp_path) -> None:
    context, _plan, _patch, _test = _inputs(tmp_path)
    bad = _assessment(context).model_copy(update={"evidence_chunk_ids": ("invented",)})
    with pytest.raises(CriticValidationError, match="outside"):
        validate_critic_grounding(bad, context=context, approved_files=("pricing.py",))


@pytest.mark.parametrize(
    ("files", "description"),
    [(("tests/test_pricing.py",), "Change another file."), (("pricing.py",), "Run curl https://example.test")],
)
def test_critic_cannot_expand_scope_or_request_operational_actions(
    tmp_path, files, description
) -> None:
    context, _plan, _patch, _test = _inputs(tmp_path)
    assessment = _assessment(context, files=files, description=description)
    with pytest.raises(CriticValidationError):
        validate_critic_grounding(
            assessment, context=context, approved_files=("pricing.py",)
        )


def test_critic_requires_attempt_one_genuine_failure(tmp_path) -> None:
    context, plan, patch, test = _inputs(tmp_path)
    critic = StructuredCritic(FakeInferenceProvider(_assessment(context).model_dump_json()))
    with pytest.raises(CriticValidationError, match="attempt one"):
        asyncio.run(critic.assess(
            context=context, approved_plan=plan, approved_plan_hash=repair_plan_hash(plan),
            approved_files=plan.proposed_files, patch=patch, test_result=test,
            attempt_number=2,
        ))
    passing = test.model_copy(update={"status": SandboxStatus.PASSED, "exit_code": 0})
    with pytest.raises(CriticValidationError, match="genuine"):
        asyncio.run(critic.assess(
            context=context, approved_plan=plan, approved_plan_hash=repair_plan_hash(plan),
            approved_files=plan.proposed_files, patch=patch, test_result=passing,
            attempt_number=1,
        ))
    assert critic._provider.calls == 0


def test_identical_completed_critic_request_reuses_durable_assessment(tmp_path) -> None:
    context, plan, patch, test = _inputs(tmp_path)
    provider = FakeInferenceProvider(_assessment(context).model_dump_json())
    service = CriticService(
        StructuredCritic(provider),
        CriticAssessmentStore((tmp_path / "critic-cache").resolve()),
    )
    kwargs = dict(
        thread_id="critic-replay", context=context, approved_plan=plan,
        approved_plan_hash=repair_plan_hash(plan), approved_files=plan.proposed_files,
        patch=patch, test_result=test, attempt_number=1,
    )
    first = asyncio.run(service.assess_failure(**kwargs))
    second = asyncio.run(service.assess_failure(**kwargs))
    assert first == second
    assert provider.calls == 1
