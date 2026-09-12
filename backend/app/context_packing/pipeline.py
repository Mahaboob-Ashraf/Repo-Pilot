"""Composition boundary from hybrid retrieval to a bounded ContextPack."""

from __future__ import annotations

from app.context_packing.packing import ContextPack, ContextPacker
from app.retrieval import HybridRetriever, StructuralExpander


class StructuralContextPipeline:
    """Run hybrid retrieval, one-hop expansion, then hard-budget packing."""

    def __init__(
        self,
        retriever: HybridRetriever,
        expander: StructuralExpander,
        packer: ContextPacker,
        *,
        budget: int,
    ) -> None:
        if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
            raise ValueError("budget must be a positive integer")
        self._retriever = retriever
        self._expander = expander
        self._packer = packer
        self._budget = budget

    async def build_context(self, query: str, *, top_k: int) -> ContextPack:
        response = await self._retriever.search_hybrid(query, top_k=top_k)
        expansion = self._expander.expand(response)
        return self._packer.pack(query, expansion, budget=self._budget)
