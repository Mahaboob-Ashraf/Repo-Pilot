from pathlib import Path

from app.chunking import CodeChunk, build_repository_chunks
from app.retrieval import (
    EvidenceOrigin,
    HybridRetrievalMode,
    HybridSearchResponse,
    HybridSearchResult,
    RetrievalSource,
    StructuralExpander,
    StructuralIndex,
    StructuralRelation,
)


STRUCTURE_REPOSITORY = Path(__file__).parent / "fixtures" / "structure_repo"


def _chunks() -> tuple[CodeChunk, ...]:
    return build_repository_chunks(STRUCTURE_REPOSITORY).chunks


def _by_symbol() -> dict[str, CodeChunk]:
    return {chunk.qualified_symbol: chunk for chunk in _chunks()}


def _hybrid(chunk: CodeChunk, rank: int) -> HybridSearchResult:
    return HybridSearchResult(
        chunk=chunk,
        rank=rank,
        rrf_score=1 / (60 + rank),
        lexical_rank=rank,
        vector_rank=None,
        lexical_bm25_score=-1.0,
        vector_cosine_distance=None,
        retrieval_sources=(RetrievalSource.LEXICAL,),
    )


def _response(*ranked_chunks: CodeChunk) -> HybridSearchResponse:
    return HybridSearchResponse(
        results=tuple(
            _hybrid(chunk, rank)
            for rank, chunk in enumerate(ranked_chunks, start=1)
        ),
        mode=HybridRetrievalMode.HYBRID,
    )


def test_retrieved_method_adds_its_parent_class() -> None:
    chunks = _by_symbol()
    result = StructuralExpander(StructuralIndex(_chunks())).expand(
        _response(chunks["Cart.total"])
    )

    parent = next(item for item in result.candidates if item.chunk.symbol == "Cart")
    assert parent.origin is EvidenceOrigin.STRUCTURAL
    assert parent.structural_causes[0].relation is StructuralRelation.PARENT
    assert parent.structural_causes[0].seed_chunk_id == chunks["Cart.total"].chunk_id


def test_retrieved_class_adds_only_its_direct_child_methods() -> None:
    chunks = _by_symbol()
    result = StructuralExpander(StructuralIndex(_chunks())).expand(
        _response(chunks["Cart"])
    )

    children = tuple(
        item.chunk.qualified_symbol
        for item in result.candidates
        if any(
            cause.relation is StructuralRelation.CHILD
            for cause in item.structural_causes
        )
    )
    assert set(children) == {"Cart.total", "Cart.tax"}
    assert "checkout" not in children


def test_local_module_import_adds_direct_imported_module_chunks() -> None:
    chunks = _by_symbol()
    index = StructuralIndex(_chunks())
    links = index.relationships_from(chunks["checkout"].chunk_id)

    assert any(
        link.target_chunk_id == chunks["calculate"].chunk_id
        and link.relation is StructuralRelation.IMPORTED_MODULE
        for link in links
    )


def test_third_party_import_is_not_treated_as_a_local_module() -> None:
    chunks = _by_symbol()
    index = StructuralIndex(_chunks())

    assert all("requests" not in link.target_chunk_id for link in index.links)
    assert all(
        index.chunk(link.target_chunk_id).path != "requests.py"
        for link in index.relationships_from(chunks["checkout"].chunk_id)
    )


def test_source_function_adds_a_directly_related_test() -> None:
    chunks = _by_symbol()
    result = StructuralExpander(StructuralIndex(_chunks())).expand(
        _response(chunks["checkout"])
    )

    test = next(
        item
        for item in result.candidates
        if item.chunk.qualified_symbol == "test_checkout_uses_calculation"
    )
    assert test.origin is EvidenceOrigin.STRUCTURAL
    assert test.structural_causes[0].relation is StructuralRelation.RELATED_TEST


def test_expansion_is_exactly_one_hop_and_never_traverses_added_imports() -> None:
    chunks = _by_symbol()
    result = StructuralExpander(StructuralIndex(_chunks())).expand(
        _response(chunks["checkout"])
    )

    ids = {item.chunk_id for item in result.candidates}
    assert chunks["calculate"].chunk_id in ids
    assert chunks["deep_value"].chunk_id not in ids


def test_structural_duplicates_are_deduplicated_with_all_causes_retained() -> None:
    chunks = _by_symbol()
    result = StructuralExpander(StructuralIndex(_chunks())).expand(
        _response(chunks["checkout"], chunks["calculate"])
    )

    calculate = tuple(
        item for item in result.candidates if item.chunk_id == chunks["calculate"].chunk_id
    )
    assert len(calculate) == 1
    assert any(
        cause.relation is StructuralRelation.IMPORTED_MODULE
        for cause in calculate[0].structural_causes
    )


def test_direct_retrieval_provenance_outranks_structural_provenance() -> None:
    chunks = _by_symbol()
    result = StructuralExpander(StructuralIndex(_chunks())).expand(
        _response(chunks["checkout"], chunks["calculate"])
    )

    calculate = next(
        item for item in result.candidates if item.chunk_id == chunks["calculate"].chunk_id
    )
    assert calculate.origin is EvidenceOrigin.RETRIEVED
    assert calculate.source_retrieval_rank == 2


def test_expansion_order_is_deterministic_and_relation_prioritized() -> None:
    chunks = _by_symbol()
    expander = StructuralExpander(StructuralIndex(_chunks()))

    first = expander.expand(_response(chunks["checkout"]))
    second = expander.expand(_response(chunks["checkout"]))

    assert first == second
    assert [item.origin for item in first.candidates[:1]] == [
        EvidenceOrigin.RETRIEVED
    ]
    assert [
        item.structural_causes[0].relation for item in first.candidates[1:]
    ] == [StructuralRelation.RELATED_TEST, StructuralRelation.IMPORTED_MODULE]
