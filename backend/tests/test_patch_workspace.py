"""Deterministic M4 scope, evidence, workspace, transaction, and diff tests."""

from __future__ import annotations

import asyncio
from hashlib import sha256
import os
from pathlib import Path

import pytest

from app.patching import (
    ApprovedPatchService,
    PatchApplicationError,
    PatchConflictError,
    PatchEdit,
    PatchProposal,
    PatchScopeError,
    PatchValidationError,
    StaleApprovalError,
    StructuredPatcher,
    WorkspaceError,
    WorkspaceManager,
    canonical_patch_hash,
)
from app.patching.service import _evidence_range
from app.planning import PlanningContextSnapshot, PlanningEvidence, repair_plan_hash
from tests.patching_fakes import (
    NEW_CALCULATION,
    OLD_CALCULATION,
    copy_toy_repository,
    patch_inputs,
    two_file_plan,
)
from tests.planning_fakes import FakeInferenceProvider


def test_freshness_accepts_exact_indented_method_source_within_line_range() -> None:
    text = "class Counter:\n    def increment(self):\n        return self.value + 1\n"
    source = "def increment(self):\n        return self.value + 1"
    evidence = PlanningEvidence(
        chunk_id="counter.py::method::Counter.increment::2-3",
        path="counter.py",
        qualified_symbol="Counter.increment",
        chunk_type="method",
        start_line=2,
        end_line=3,
        content_hash=sha256(source.encode("utf-8")).hexdigest(),
        source_text=source,
        origin="retrieved",
        source_retrieval_rank=1,
    )

    start, end = _evidence_range(text, evidence)

    assert text[start:end] == source


def _execute(
    *,
    repository: Path,
    workspace_root: Path,
    proposal: PatchProposal,
    context_pack=None,
    plan=None,
    thread_id: str = "patch-thread",
    file_writer=None,
):
    if context_pack is None or plan is None:
        default_pack, default_plan, _default_proposal = patch_inputs(repository)
        context_pack = context_pack or default_pack
        plan = plan or default_plan
    provider = FakeInferenceProvider(proposal.model_dump_json())
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=workspace_root,
    )
    service = ApprovedPatchService(
        patcher=StructuredPatcher(provider),
        workspace_manager=manager,
        file_writer=file_writer,
    )
    plan_hash = repair_plan_hash(plan)
    artifact = asyncio.run(
        service.prepare_patch(
            thread_id=thread_id,
            workflow_status="approved_for_patch",
            approval_plan_hash=plan_hash,
            approved_plan=plan,
            approved_plan_hash=plan_hash,
            approved_files=plan.proposed_files,
            context=PlanningContextSnapshot.from_context_pack(context_pack),
        )
    )
    return artifact, provider, manager, service


def _replace_edit(proposal: PatchProposal, **updates: object) -> PatchProposal:
    return proposal.model_copy(
        update={"edits": (proposal.edits[0].model_copy(update=updates),)}
    )


def _py_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.py"))
    }


def test_workspace_root_must_be_outside_canonical_repository(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)

    with pytest.raises(WorkspaceError, match="outside"):
        WorkspaceManager(
            canonical_repository=repository,
            workspace_root=repository / "workspace",
        )


def test_workspace_snapshot_preserves_relevant_bytes_and_excludes_git(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    (repository / ".git").mkdir()
    (repository / ".git" / "config").write_text("secret", encoding="utf-8")
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    workspace_id = manager.workspace_id_for(
        thread_id="copy", approved_plan_hash="a" * 64
    )

    snapshot = manager.prepare(workspace_id)

    assert (snapshot.repository_root / "pricing.py").read_bytes() == (
        repository / "pricing.py"
    ).read_bytes()
    assert (snapshot.repository_root / "tests" / "test_pricing.py").read_bytes() == (
        repository / "tests" / "test_pricing.py"
    ).read_bytes()
    assert not (snapshot.repository_root / ".git").exists()


def test_approved_edit_changes_only_workspace_and_generates_canonical_diff(
    tmp_path,
) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    canonical_before = _py_hashes(repository)

    artifact, _provider, manager, _service = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces",
        proposal=proposal,
        context_pack=pack,
        plan=plan,
    )

    workspace_file = manager.repository_root_for(artifact.workspace_id) / "pricing.py"
    assert NEW_CALCULATION in workspace_file.read_text(encoding="utf-8")
    assert OLD_CALCULATION in (repository / "pricing.py").read_text(encoding="utf-8")
    assert _py_hashes(repository) == canonical_before
    assert artifact.changed_files == ("pricing.py",)
    assert "--- a/pricing.py\n" in artifact.unified_diff
    assert "+++ b/pricing.py\n" in artifact.unified_diff
    assert str(repository) not in artifact.unified_diff
    assert str(manager.workspace_root) not in artifact.unified_diff
    assert artifact.patch_hash == canonical_patch_hash(artifact.unified_diff)


def test_unapproved_file_rejects_whole_patch_without_application(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    test_evidence = next(
        item for item in pack.included_chunks if item.path == "tests/test_pricing.py"
    )
    expanded = proposal.model_copy(
        update={
            "edits": proposal.edits
            + (
                PatchEdit(
                    path="tests/test_pricing.py",
                    expected_old_text="50.0, 0.0",
                    replacement_text="50.0, 1.0",
                    evidence_chunk_ids=(test_evidence.chunk_id,),
                    rationale="Attempt to widen scope.",
                ),
            )
        }
    )

    with pytest.raises(PatchScopeError):
        _execute(
            repository=repository,
            workspace_root=tmp_path / "workspaces",
            proposal=expanded,
            context_pack=pack,
            plan=plan,
        )
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    workspace_id = manager.workspace_id_for(
        thread_id="patch-thread", approved_plan_hash=repair_plan_hash(plan)
    )
    assert (manager.repository_root_for(workspace_id) / "pricing.py").read_bytes() == (
        repository / "pricing.py"
    ).read_bytes()


@pytest.mark.parametrize("unsafe_path", ["C:/repo/pricing.py", "../pricing.py"])
def test_absolute_and_traversal_paths_are_rejected(tmp_path, unsafe_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)

    with pytest.raises(PatchValidationError, match="repository-relative"):
        _execute(
            repository=repository,
            workspace_root=tmp_path / "workspaces",
            proposal=_replace_edit(proposal, path=unsafe_path),
            context_pack=pack,
            plan=plan,
        )


def test_nonexistent_new_file_attempt_is_rejected(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    workspace_id = manager.workspace_id_for(
        thread_id="missing", approved_plan_hash="b" * 64
    )
    manager.prepare(workspace_id)

    with pytest.raises(PatchValidationError, match="existing"):
        manager.resolve_existing_file(workspace_id, "new_file.py")


def test_symlink_patch_target_is_rejected(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    workspace_id = manager.workspace_id_for(
        thread_id="symlink", approved_plan_hash="c" * 64
    )
    snapshot = manager.prepare(workspace_id)
    target = snapshot.repository_root / "linked.py"
    try:
        os.symlink(repository / "pricing.py", target)
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable on this platform: {exc}")

    with pytest.raises(PatchValidationError, match="symlink"):
        manager.resolve_existing_file(workspace_id, "linked.py")


def test_invented_and_unrelated_evidence_are_rejected(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    unrelated = next(
        item for item in pack.included_chunks if item.path == "tests/test_pricing.py"
    )
    cases = (
        ("invented::chunk", "outside"),
        (unrelated.chunk_id, "same-file"),
    )
    for index, (chunk_id, message) in enumerate(cases):
        with pytest.raises(PatchValidationError, match=message):
            _execute(
                repository=repository,
                workspace_root=tmp_path / f"workspaces-{index}",
                proposal=_replace_edit(
                    proposal, evidence_chunk_ids=(chunk_id,)
                ),
                context_pack=pack,
                plan=plan,
            )


def test_missing_and_ambiguous_exact_source_are_rejected(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    cases = (
        ("not present anywhere", "not found"),
        ("price", "ambiguously"),
    )
    for index, (old_text, message) in enumerate(cases):
        with pytest.raises(PatchValidationError, match=message):
            _execute(
                repository=repository,
                workspace_root=tmp_path / f"workspaces-{index}",
                proposal=_replace_edit(proposal, expected_old_text=old_text),
                context_pack=pack,
                plan=plan,
            )


def test_overlapping_edits_are_rejected_before_application(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    function = next(item for item in pack.included_chunks if item.path == "pricing.py")
    overlap = PatchEdit(
        path="pricing.py",
        expected_old_text="price * (1 + discount_percent / 100)",
        replacement_text="price * (1 - discount_percent / 100)",
        evidence_chunk_ids=(function.chunk_id,),
        rationale="Overlaps the full return-line edit.",
    )
    overlapping = proposal.model_copy(update={"edits": proposal.edits + (overlap,)})

    with pytest.raises(PatchValidationError, match="overlapping"):
        _execute(
            repository=repository,
            workspace_root=tmp_path / "workspaces",
            proposal=overlapping,
            context_pack=pack,
            plan=plan,
        )


def test_multiple_non_overlapping_edits_apply_deterministically(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    function = next(item for item in pack.included_chunks if item.path == "pricing.py")
    doc_edit = PatchEdit(
        path="pricing.py",
        expected_old_text="Return a price after applying a percentage discount.",
        replacement_text="Return the price after subtracting a discount.",
        evidence_chunk_ids=(function.chunk_id,),
        rationale="Clarify the corrected behavior.",
    )
    multi = proposal.model_copy(update={"edits": (doc_edit,) + proposal.edits})

    first, _provider, _manager, _service = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces-a",
        proposal=multi,
        context_pack=pack,
        plan=plan,
        thread_id="same",
    )
    second, _provider, _manager, _service = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces-b",
        proposal=multi.model_copy(update={"edits": tuple(reversed(multi.edits))}),
        context_pack=pack,
        plan=plan,
        thread_id="same",
    )

    assert first.unified_diff == second.unified_diff
    assert first.patch_hash == second.patch_hash


def test_changed_approved_evidence_fails_before_patch_generation(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    pricing = repository / "pricing.py"
    pricing.write_text(
        pricing.read_text(encoding="utf-8").replace(
            OLD_CALCULATION, NEW_CALCULATION
        ),
        encoding="utf-8",
    )
    provider = FakeInferenceProvider(proposal.model_dump_json())
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    service = ApprovedPatchService(
        patcher=StructuredPatcher(provider), workspace_manager=manager
    )
    plan_hash = repair_plan_hash(plan)

    with pytest.raises(StaleApprovalError):
        asyncio.run(
            service.prepare_patch(
                thread_id="stale",
                workflow_status="approved_for_patch",
                approval_plan_hash=plan_hash,
                approved_plan=plan,
                approved_plan_hash=plan_hash,
                approved_files=plan.proposed_files,
                context=PlanningContextSnapshot.from_context_pack(pack),
            )
        )
    assert provider.calls == 0


def test_invalid_multi_file_proposal_applies_nothing(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, _single_plan, base_proposal = patch_inputs(repository)
    plan = two_file_plan(pack)
    test_evidence = next(
        item for item in pack.included_chunks if item.path == "tests/test_pricing.py"
    )
    proposal = base_proposal.model_copy(
        update={
            "edits": base_proposal.edits
            + (
                PatchEdit(
                    path="tests/test_pricing.py",
                    expected_old_text="missing test text",
                    replacement_text="replacement",
                    evidence_chunk_ids=(test_evidence.chunk_id,),
                    rationale="Invalid second edit.",
                ),
            )
        }
    )

    with pytest.raises(PatchValidationError, match="not found"):
        _execute(
            repository=repository,
            workspace_root=tmp_path / "workspaces",
            proposal=proposal,
            context_pack=pack,
            plan=plan,
        )
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    workspace_id = manager.workspace_id_for(
        thread_id="patch-thread", approved_plan_hash=repair_plan_hash(plan)
    )
    assert _py_hashes(manager.repository_root_for(workspace_id)) == _py_hashes(repository)


def test_mid_apply_failure_rolls_back_all_workspace_files(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, _single_plan, base_proposal = patch_inputs(repository)
    plan = two_file_plan(pack)
    test_evidence = next(
        item for item in pack.included_chunks if item.path == "tests/test_pricing.py"
    )
    proposal = base_proposal.model_copy(
        update={
            "edits": base_proposal.edits
            + (
                PatchEdit(
                    path="tests/test_pricing.py",
                    expected_old_text="50.0, 0.0",
                    replacement_text="50.0, 0",
                    evidence_chunk_ids=(test_evidence.chunk_id,),
                    rationale="Exercise transactional rollback.",
                ),
            )
        }
    )
    calls = 0

    def failing_writer(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected write failure")
        path.write_bytes(data)

    with pytest.raises(PatchApplicationError, match="rolled back"):
        _execute(
            repository=repository,
            workspace_root=tmp_path / "workspaces",
            proposal=proposal,
            context_pack=pack,
            plan=plan,
            file_writer=failing_writer,
        )
    manager = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    )
    workspace_id = manager.workspace_id_for(
        thread_id="patch-thread", approved_plan_hash=repair_plan_hash(plan)
    )
    assert _py_hashes(manager.repository_root_for(workspace_id)) == _py_hashes(repository)


def test_workspace_patch_persists_and_replay_returns_existing_result(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    artifact, provider, manager, service = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces",
        proposal=proposal,
        context_pack=pack,
        plan=plan,
    )
    plan_hash = repair_plan_hash(plan)

    replayed = asyncio.run(
        service.prepare_patch(
            thread_id="patch-thread",
            workflow_status="approved_for_patch",
            approval_plan_hash=plan_hash,
            approved_plan=plan,
            approved_plan_hash=plan_hash,
            approved_files=plan.proposed_files,
            context=PlanningContextSnapshot.from_context_pack(pack),
        )
    )
    reconstructed = WorkspaceManager(
        canonical_repository=repository,
        workspace_root=tmp_path / "workspaces",
    ).load_patch_artifact(
        workspace_id=artifact.workspace_id,
        approved_plan_hash=plan_hash,
    )

    assert replayed == artifact == reconstructed
    assert provider.calls == 1
    assert manager.repository_root_for(artifact.workspace_id).is_dir()


def test_conflicting_completed_workspace_state_fails_explicitly(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    artifact, _provider, manager, _service = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces",
        proposal=proposal,
        context_pack=pack,
        plan=plan,
    )
    workspace_file = manager.repository_root_for(artifact.workspace_id) / "pricing.py"
    workspace_file.write_text("conflicting content", encoding="utf-8")

    with pytest.raises(PatchConflictError, match="conflicts"):
        manager.load_patch_artifact(
            workspace_id=artifact.workspace_id,
            approved_plan_hash=repair_plan_hash(plan),
        )


def test_diff_hash_is_deterministic_and_content_sensitive(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    same_a, *_ = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces-a",
        proposal=proposal,
        context_pack=pack,
        plan=plan,
        thread_id="a",
    )
    same_b, *_ = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces-b",
        proposal=proposal,
        context_pack=pack,
        plan=plan,
        thread_id="b",
    )
    changed = _replace_edit(
        proposal,
        replacement_text="return price - (price * discount_percent / 100)",
    )
    changed_artifact, *_ = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces-c",
        proposal=changed,
        context_pack=pack,
        plan=plan,
        thread_id="c",
    )

    assert same_a.unified_diff == same_b.unified_diff
    assert same_a.patch_hash == same_b.patch_hash
    assert changed_artifact.patch_hash != same_a.patch_hash


def test_authority_hash_status_and_scope_must_match(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    provider = FakeInferenceProvider(proposal.model_dump_json())
    service = ApprovedPatchService(
        patcher=StructuredPatcher(provider),
        workspace_manager=WorkspaceManager(
            canonical_repository=repository,
            workspace_root=tmp_path / "workspaces",
        ),
    )
    plan_hash = repair_plan_hash(plan)
    base = {
        "thread_id": "authority",
        "workflow_status": "approved_for_patch",
        "approval_plan_hash": plan_hash,
        "approved_plan": plan,
        "approved_plan_hash": plan_hash,
        "approved_files": plan.proposed_files,
        "context": PlanningContextSnapshot.from_context_pack(pack),
    }
    cases = (
        {"workflow_status": "rejected"},
        {"approval_plan_hash": "0" * 64},
        {"approved_files": ("tests/test_pricing.py",)},
    )
    for update in cases:
        with pytest.raises(PatchValidationError):
            asyncio.run(service.prepare_patch(**(base | update)))
    assert provider.calls == 0


def test_independent_threads_receive_isolated_workspaces(tmp_path) -> None:
    repository = copy_toy_repository(tmp_path)
    pack, plan, proposal = patch_inputs(repository)
    first, *_ = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces",
        proposal=proposal,
        context_pack=pack,
        plan=plan,
        thread_id="first",
    )
    second, *_ = _execute(
        repository=repository,
        workspace_root=tmp_path / "workspaces",
        proposal=proposal,
        context_pack=pack,
        plan=plan,
        thread_id="second",
    )

    assert first.workspace_id != second.workspace_id
