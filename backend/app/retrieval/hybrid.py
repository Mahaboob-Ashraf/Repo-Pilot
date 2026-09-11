"""Deterministic rank-only fusion for lexical and dense code retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.chunking import CodeChunk
from app.retrieval.lexical import LexicalSearchResult
from app.retrieval.vector import VectorRetrievalError, VectorSearchResult


DEFAULT_RRF_K = 60
DEFAULT_CANDIDATE_K = 20


class RetrievalSource(StrEnum):
    """Retrieval lists that contributed to a fused result."""

    LEXICAL = "lexical"
    VECTOR = "vector"


class HybridRetrievalMode(StrEnum):
    """Whether both retrievers ran or dense retrieval degraded cleanly."""

    HYBRID = "hybrid"
    LEXICAL_ONLY_DEGRADED = "lexical_only_degraded"


class HybridProvenanceError(ValueError):
    """Raised when one chunk ID maps to conflicting canonical provenance."""


class LexicalRetriever(Protocol):
    def search_lexical(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[LexicalSearchResult, ...]:
        """Return ranked lexical candidates."""


class VectorRetriever(Protocol):
    async def search_vector(
        self,
        query: str,
        *,
        k: int = 10,
    ) -> tuple[VectorSearchResult, ...]:
        """Return ranked dense candidates."""


@dataclass(frozen=True, slots=True)
class HybridSearchResult:
    """A fused query result that retains canonical and modality evidence."""

    chunk: CodeChunk
    rank: int
    rrf_score: float
    lexical_rank: int | None
    vector_rank: int | None
    lexical_bm25_score: float | None
    vector_cosine_distance: float | None
    retrieval_sources: tuple[RetrievalSource, ...]

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def path(self) -> str:
        return self.chunk.path

    @property
    def symbol(self) -> str:
        return self.chunk.symbol

    @property
    def qualified_symbol(self) -> str:
        return self.chunk.qualified_symbol


@dataclass(frozen=True, slots=True)
class HybridSearchResponse:
    """Hybrid results plus an explicit normal/degraded execution status."""

    results: tuple[HybridSearchResult, ...]
    mode: HybridRetrievalMode
    degradation_reason: str | None = None

    @property
    def degraded(self) -> bool:
        return self.mode is HybridRetrievalMode.LEXICAL_ONLY_DEGRADED


class HybridRetriever:
    """Fetch bounded candidates and fuse their 1-based ranks with RRF."""

    def __init__(
        self,
        lexical_retriever: LexicalRetriever,
        vector_retriever: VectorRetriever,
        *,
        k_rrf: int = DEFAULT_RRF_K,
        candidate_k: int = DEFAULT_CANDIDATE_K,
    ) -> None:
        _validate_positive_integer(k_rrf, name="k_rrf")
        _validate_positive_integer(candidate_k, name="candidate_k")
        self._lexical_retriever = lexical_retriever
        self._vector_retriever = vector_retriever
        self._k_rrf = k_rrf
        self._candidate_k = candidate_k

    @property
    def k_rrf(self) -> int:
        return self._k_rrf

    @property
    def candidate_k(self) -> int:
        return self._candidate_k

    async def search_hybrid(
        self,
        query: str,
        *,
        top_k: int = 10,
        candidate_k: int | None = None,
    ) -> HybridSearchResponse:
        """Retrieve each modality and return fused or explicit fallback results."""

        _validate_positive_integer(top_k, name="top_k")
        depth = self._candidate_k if candidate_k is None else candidate_k
        _validate_positive_integer(depth, name="candidate_k")

        lexical_results = self._lexical_retriever.search_lexical(query, k=depth)
        mode = HybridRetrievalMode.HYBRID
        degradation_reason: str | None = None
        try:
            vector_results = await self._vector_retriever.search_vector(
                query,
                k=depth,
            )
        except VectorRetrievalError as exc:
            vector_results = ()
            mode = HybridRetrievalMode.LEXICAL_ONLY_DEGRADED
            degradation_reason = f"{type(exc).__name__}: {exc}"

        results = reciprocal_rank_fusion(
            lexical_results,
            vector_results,
            k_rrf=self._k_rrf,
            top_k=top_k,
        )
        return HybridSearchResponse(
            results=results,
            mode=mode,
            degradation_reason=degradation_reason,
        )


def reciprocal_rank_fusion(
    lexical_results: Sequence[LexicalSearchResult],
    vector_results: Sequence[VectorSearchResult],
    *,
    k_rrf: int = DEFAULT_RRF_K,
    top_k: int = 10,
) -> tuple[HybridSearchResult, ...]:
    """Fuse ranks as sum(1 / (k_rrf + rank)); raw scores stay metadata."""

    _validate_positive_integer(k_rrf, name="k_rrf")
    _validate_positive_integer(top_k, name="top_k")

    candidates: dict[str, dict[str, object]] = {}
    for result in lexical_results:
        _validate_positive_integer(result.rank, name="lexical rank")
        candidate = _candidate_for(candidates, result.chunk)
        candidate["lexical_rank"] = result.rank
        candidate["lexical_bm25_score"] = result.bm25_score

    for result in vector_results:
        _validate_positive_integer(result.rank, name="vector rank")
        candidate = _candidate_for(candidates, result.chunk)
        candidate["vector_rank"] = result.rank
        candidate["vector_cosine_distance"] = result.cosine_distance

    scored: list[tuple[float, str, dict[str, object]]] = []
    for chunk_id, candidate in candidates.items():
        lexical_rank = _optional_int(candidate.get("lexical_rank"))
        vector_rank = _optional_int(candidate.get("vector_rank"))
        score = sum(
            1.0 / (k_rrf + rank)
            for rank in (lexical_rank, vector_rank)
            if rank is not None
        )
        scored.append((score, chunk_id, candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(
        _build_result(candidate, rank=rank, rrf_score=score)
        for rank, (score, _chunk_id, candidate) in enumerate(
            scored[:top_k],
            start=1,
        )
    )


def _candidate_for(
    candidates: dict[str, dict[str, object]],
    chunk: CodeChunk,
) -> dict[str, object]:
    candidate = candidates.setdefault(chunk.chunk_id, {"chunk": chunk})
    if candidate["chunk"] != chunk:
        raise HybridProvenanceError(
            f"Conflicting canonical provenance for chunk {chunk.chunk_id}"
        )
    return candidate


def _build_result(
    candidate: dict[str, object],
    *,
    rank: int,
    rrf_score: float,
) -> HybridSearchResult:
    chunk = candidate["chunk"]
    if not isinstance(chunk, CodeChunk):
        raise TypeError("Hybrid candidate did not contain a CodeChunk")

    lexical_rank = _optional_int(candidate.get("lexical_rank"))
    vector_rank = _optional_int(candidate.get("vector_rank"))
    sources = tuple(
        source
        for source, source_rank in (
            (RetrievalSource.LEXICAL, lexical_rank),
            (RetrievalSource.VECTOR, vector_rank),
        )
        if source_rank is not None
    )
    return HybridSearchResult(
        chunk=chunk,
        rank=rank,
        rrf_score=rrf_score,
        lexical_rank=lexical_rank,
        vector_rank=vector_rank,
        lexical_bm25_score=_optional_float(candidate.get("lexical_bm25_score")),
        vector_cosine_distance=_optional_float(
            candidate.get("vector_cosine_distance")
        ),
        retrieval_sources=sources,
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _validate_positive_integer(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
