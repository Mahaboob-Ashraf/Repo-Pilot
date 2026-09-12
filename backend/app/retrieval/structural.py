"""Deterministic one-hop structural relationships over canonical CodeChunks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
import re
from types import MappingProxyType

from app.chunking import ChunkType, CodeChunk
from app.retrieval.hybrid import (
    HybridRetrievalMode,
    HybridSearchResponse,
    HybridSearchResult,
)


class StructuralRelation(StrEnum):
    """Supported directed one-hop relationship kinds."""

    PARENT = "parent"
    RELATED_TEST = "related_test"
    IMPORTED_MODULE = "imported_module"
    CHILD = "child"


STRUCTURAL_RELATION_PRIORITY: Mapping[StructuralRelation, int] = MappingProxyType(
    {
        StructuralRelation.PARENT: 1,
        StructuralRelation.RELATED_TEST: 2,
        StructuralRelation.IMPORTED_MODULE: 3,
        StructuralRelation.CHILD: 4,
    }
)


class EvidenceOrigin(StrEnum):
    """Whether evidence came from ranking or one-hop expansion."""

    RETRIEVED = "retrieved"
    STRUCTURAL = "structural"


class StructuralIndexError(ValueError):
    """Raised when canonical structural inputs conflict."""


@dataclass(frozen=True, slots=True)
class StructuralLink:
    """One directed relationship between canonical chunk IDs."""

    source_chunk_id: str
    target_chunk_id: str
    relation: StructuralRelation


@dataclass(frozen=True, slots=True)
class StructuralCause:
    """Why one structural candidate was reachable from a retrieved seed."""

    seed_chunk_id: str
    seed_retrieval_rank: int
    relation: StructuralRelation


@dataclass(frozen=True, slots=True)
class ExpandedCandidate:
    """A deduplicated direct or one-hop structural evidence candidate."""

    chunk: CodeChunk
    origin: EvidenceOrigin
    hybrid_result: HybridSearchResult | None
    structural_causes: tuple[StructuralCause, ...] = ()

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def source_retrieval_rank(self) -> int | None:
        return self.hybrid_result.rank if self.hybrid_result is not None else None


@dataclass(frozen=True, slots=True)
class StructuralExpansionResult:
    """One-hop candidates plus the original hybrid execution status."""

    candidates: tuple[ExpandedCandidate, ...]
    retrieval_mode: HybridRetrievalMode
    degradation_reason: str | None

    @property
    def degraded(self) -> bool:
        return self.retrieval_mode is HybridRetrievalMode.LEXICAL_ONLY_DEGRADED


class StructuralIndex:
    """Small in-memory adjacency index derived only from CodeChunk metadata."""

    def __init__(self, chunks: Iterable[CodeChunk]) -> None:
        ordered_chunks = tuple(sorted(chunks, key=lambda chunk: chunk.chunk_id))
        chunks_by_id: dict[str, CodeChunk] = {}
        for chunk in ordered_chunks:
            existing = chunks_by_id.get(chunk.chunk_id)
            if existing is not None:
                raise StructuralIndexError(
                    f"Duplicate chunk_id in structural index: {chunk.chunk_id}"
                )
            chunks_by_id[chunk.chunk_id] = chunk

        links = _build_structural_links(ordered_chunks)
        adjacency: dict[str, list[StructuralLink]] = defaultdict(list)
        for link in links:
            adjacency[link.source_chunk_id].append(link)

        self._chunks_by_id = MappingProxyType(chunks_by_id)
        self._adjacency = MappingProxyType(
            {
                chunk_id: tuple(
                    sorted(
                        outgoing,
                        key=lambda link: (
                            STRUCTURAL_RELATION_PRIORITY[link.relation],
                            link.target_chunk_id,
                        ),
                    )
                )
                for chunk_id, outgoing in adjacency.items()
            }
        )
        self._links = tuple(
            sorted(
                links,
                key=lambda link: (
                    link.source_chunk_id,
                    STRUCTURAL_RELATION_PRIORITY[link.relation],
                    link.target_chunk_id,
                ),
            )
        )

    @property
    def links(self) -> tuple[StructuralLink, ...]:
        return self._links

    def chunk(self, chunk_id: str) -> CodeChunk:
        try:
            return self._chunks_by_id[chunk_id]
        except KeyError as exc:
            raise StructuralIndexError(f"Unknown structural chunk: {chunk_id}") from exc

    def relationships_from(self, chunk_id: str) -> tuple[StructuralLink, ...]:
        if chunk_id not in self._chunks_by_id:
            raise StructuralIndexError(f"Unknown structural chunk: {chunk_id}")
        return self._adjacency.get(chunk_id, ())


class StructuralExpander:
    """Expand only the original hybrid seeds by one deterministic hop."""

    def __init__(self, index: StructuralIndex) -> None:
        self._index = index

    def expand(self, response: HybridSearchResponse) -> StructuralExpansionResult:
        direct_results = tuple(
            sorted(response.results, key=lambda result: (result.rank, result.chunk_id))
        )
        direct_by_id: dict[str, HybridSearchResult] = {}
        for result in direct_results:
            canonical = self._index.chunk(result.chunk_id)
            if canonical != result.chunk:
                raise StructuralIndexError(
                    f"Hybrid provenance conflicts with structural index: {result.chunk_id}"
                )
            existing = direct_by_id.get(result.chunk_id)
            if existing is None or result.rank < existing.rank:
                direct_by_id[result.chunk_id] = result

        causes_by_target: dict[str, set[StructuralCause]] = defaultdict(set)
        # Only direct results are seeds. Newly added targets are never traversed.
        for seed in sorted(
            direct_by_id.values(),
            key=lambda result: (result.rank, result.chunk_id),
        ):
            for link in self._index.relationships_from(seed.chunk_id):
                causes_by_target[link.target_chunk_id].add(
                    StructuralCause(
                        seed_chunk_id=seed.chunk_id,
                        seed_retrieval_rank=seed.rank,
                        relation=link.relation,
                    )
                )

        direct_candidates = tuple(
            ExpandedCandidate(
                chunk=result.chunk,
                origin=EvidenceOrigin.RETRIEVED,
                hybrid_result=result,
                structural_causes=_sort_causes(causes_by_target.get(result.chunk_id, set())),
            )
            for result in sorted(
                direct_by_id.values(),
                key=lambda item: (item.rank, item.chunk_id),
            )
        )
        structural_candidates = tuple(
            ExpandedCandidate(
                chunk=self._index.chunk(chunk_id),
                origin=EvidenceOrigin.STRUCTURAL,
                hybrid_result=None,
                structural_causes=_sort_causes(causes),
            )
            for chunk_id, causes in sorted(
                (
                    (chunk_id, causes)
                    for chunk_id, causes in causes_by_target.items()
                    if chunk_id not in direct_by_id
                ),
                key=lambda item: _structural_candidate_order(item[0], item[1]),
            )
        )

        return StructuralExpansionResult(
            candidates=(*direct_candidates, *structural_candidates),
            retrieval_mode=response.mode,
            degradation_reason=response.degradation_reason,
        )


def _build_structural_links(chunks: tuple[CodeChunk, ...]) -> set[StructuralLink]:
    links: set[StructuralLink] = set()
    classes = {
        (chunk.path, chunk.symbol): chunk
        for chunk in chunks
        if chunk.chunk_type is ChunkType.CLASS
    }

    for method in (chunk for chunk in chunks if chunk.chunk_type is ChunkType.METHOD):
        if method.parent_class is None:
            continue
        parent = classes.get((method.path, method.parent_class))
        if parent is None:
            continue
        links.add(
            StructuralLink(method.chunk_id, parent.chunk_id, StructuralRelation.PARENT)
        )
        links.add(
            StructuralLink(parent.chunk_id, method.chunk_id, StructuralRelation.CHILD)
        )

    confident_modules = _confident_local_modules(chunks)
    module_by_path = {
        chunk.path: _module_name_for_path(chunk.path)
        for chunk in chunks
    }
    for importer in chunks:
        for imported_name in importer.imports:
            for imported_chunk in confident_modules.get(imported_name, ()):
                if importer.chunk_id != imported_chunk.chunk_id:
                    links.add(
                        StructuralLink(
                            importer.chunk_id,
                            imported_chunk.chunk_id,
                            StructuralRelation.IMPORTED_MODULE,
                        )
                    )

    source_chunks = tuple(
        chunk for chunk in chunks if chunk.chunk_type is not ChunkType.TEST
    )
    test_chunks = tuple(chunk for chunk in chunks if chunk.chunk_type is ChunkType.TEST)
    for source in source_chunks:
        source_module = module_by_path[source.path]
        for test in test_chunks:
            imports_source_module = (
                source_module is not None and source_module in test.imports
            )
            references_symbol = _references_symbol(test.source_text, source.symbol)
            if imports_source_module or references_symbol:
                links.add(
                    StructuralLink(
                        source.chunk_id,
                        test.chunk_id,
                        StructuralRelation.RELATED_TEST,
                    )
                )

    return links


def _confident_local_modules(
    chunks: tuple[CodeChunk, ...],
) -> dict[str, tuple[CodeChunk, ...]]:
    paths_by_module: dict[str, set[str]] = defaultdict(set)
    chunks_by_module: dict[str, list[CodeChunk]] = defaultdict(list)
    for chunk in chunks:
        module = _module_name_for_path(chunk.path)
        if module is None:
            continue
        paths_by_module[module].add(chunk.path)
        chunks_by_module[module].append(chunk)

    return {
        module: tuple(sorted(chunks_by_module[module], key=lambda chunk: chunk.chunk_id))
        for module, paths in paths_by_module.items()
        if len(paths) == 1
    }


def _module_name_for_path(path: str) -> str | None:
    pure_path = PurePosixPath(path)
    if pure_path.suffix != ".py":
        return None
    parts = list(pure_path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def _references_symbol(source_text: str, symbol: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])"
    return re.search(pattern, source_text) is not None


def _sort_causes(causes: set[StructuralCause]) -> tuple[StructuralCause, ...]:
    return tuple(
        sorted(
            causes,
            key=lambda cause: (
                STRUCTURAL_RELATION_PRIORITY[cause.relation],
                cause.seed_retrieval_rank,
                cause.seed_chunk_id,
            ),
        )
    )


def _structural_candidate_order(
    chunk_id: str,
    causes: set[StructuralCause],
) -> tuple[int, int, str, str]:
    best_cause = min(
        causes,
        key=lambda cause: (
            STRUCTURAL_RELATION_PRIORITY[cause.relation],
            cause.seed_retrieval_rank,
            cause.seed_chunk_id,
        ),
    )
    return (
        STRUCTURAL_RELATION_PRIORITY[best_cause.relation],
        best_cause.seed_retrieval_rank,
        best_cause.seed_chunk_id,
        chunk_id,
    )
