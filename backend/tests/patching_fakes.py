"""Deterministic offline helpers for M4 patching tests."""

from __future__ import annotations

from pathlib import Path
import shutil

from app.patching import PatchEdit, PatchProposal
from app.planning import RepairPlan
from tests.planning_fakes import TOY_REPOSITORY, make_context_pack, make_valid_plan


OLD_CALCULATION = "return price * (1 + discount_percent / 100)"
NEW_CALCULATION = "return price * (1 - discount_percent / 100)"


def copy_toy_repository(parent: Path) -> Path:
    repository = parent / "canonical"
    (repository / "tests").mkdir(parents=True)
    shutil.copyfile(TOY_REPOSITORY / "pricing.py", repository / "pricing.py")
    shutil.copyfile(
        TOY_REPOSITORY / "tests" / "test_pricing.py",
        repository / "tests" / "test_pricing.py",
    )
    return repository


def patch_inputs(repository: Path):
    context_pack = make_context_pack(repository)
    plan = make_valid_plan(context_pack)
    function = next(
        item for item in context_pack.included_chunks if item.path == "pricing.py"
    )
    proposal = PatchProposal(
        summary="Correct discount subtraction.",
        edits=(
            PatchEdit(
                path="pricing.py",
                expected_old_text=OLD_CALCULATION,
                replacement_text=NEW_CALCULATION,
                evidence_chunk_ids=(function.chunk_id,),
                rationale="Subtract the discount fraction instead of adding it.",
            ),
        ),
    )
    return context_pack, plan, proposal


def two_file_plan(context_pack) -> RepairPlan:
    base = make_valid_plan(context_pack)
    function = next(
        item for item in context_pack.included_chunks if item.path == "pricing.py"
    )
    test = next(
        item
        for item in context_pack.included_chunks
        if item.path == "tests/test_pricing.py"
    )
    step = base.steps[0].model_copy(
        update={
            "affected_files": ("pricing.py", "tests/test_pricing.py"),
            "evidence_chunk_ids": (function.chunk_id, test.chunk_id),
        }
    )
    return base.model_copy(
        update={
            "proposed_files": ("pricing.py", "tests/test_pricing.py"),
            "steps": (step,),
        }
    )
