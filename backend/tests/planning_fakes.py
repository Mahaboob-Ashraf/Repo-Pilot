"""Deterministic offline fixtures shared by M3 planner/workflow tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.chunking import build_repository_chunks
from app.context_packing import ContextPack, ContextPacker
from app.planning import RepairPlan, RepairStep
from app.retrieval import (
    EvidenceOrigin,
    ExpandedCandidate,
    HybridRetrievalMode,
    HybridSearchResult,
    RetrievalSource,
    StructuralExpansionResult,
)


TOY_REPOSITORY = Path(__file__).parents[2] / "fixtures" / "toy-repo"
ISSUE = "Applying a discount increases the price instead of reducing it."


@dataclass
class FakeInferenceProvider:
    response: str
    prompts: list[str] = field(default_factory=list)
    calls: int = 0

    @property
    def model(self) -> str:
        return "fake-planner"

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return self.response


def make_context_pack() -> ContextPack:
    chunks = build_repository_chunks(TOY_REPOSITORY).chunks
    candidates = tuple(
        ExpandedCandidate(
            chunk=chunk,
            origin=EvidenceOrigin.RETRIEVED,
            hybrid_result=HybridSearchResult(
                chunk=chunk,
                rank=rank,
                rrf_score=1 / (60 + rank),
                lexical_rank=rank,
                vector_rank=None,
                lexical_bm25_score=-1.0,
                vector_cosine_distance=None,
                retrieval_sources=(RetrievalSource.LEXICAL,),
            ),
        )
        for rank, chunk in enumerate(chunks, start=1)
    )
    expansion = StructuralExpansionResult(
        candidates=candidates,
        retrieval_mode=HybridRetrievalMode.HYBRID,
        degradation_reason=None,
    )
    return ContextPacker().pack(ISSUE, expansion, budget=100_000)


def make_valid_plan(pack: ContextPack | None = None) -> RepairPlan:
    pack = pack or make_context_pack()
    function = next(item for item in pack.included_chunks if item.path == "pricing.py")
    test = next(
        item
        for item in pack.included_chunks
        if item.path == "tests/test_pricing.py"
    )
    return RepairPlan(
        summary="Correct discount subtraction and retain regression coverage.",
        diagnosis="The calculation adds the discount amount to the price.",
        proposed_files=("pricing.py",),
        steps=(
            RepairStep(
                description="Change the price calculation to subtract the discount.",
                affected_files=("pricing.py",),
                evidence_chunk_ids=(function.chunk_id, test.chunk_id),
            ),
        ),
        suggested_tests=("Run the pricing unit tests.",),
    )

