from hashlib import sha256
from pathlib import Path

import pytest

from app.chunking import ChunkType, CodeChunk, build_repository_chunks
from app.retrieval import (
    DuplicateChunkIdError,
    LexicalQueryError,
    SQLiteLexicalIndex,
    is_fts5_available,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOY_REPOSITORY = REPOSITORY_ROOT / "fixtures" / "toy-repo"


def _toy_chunks() -> tuple[CodeChunk, ...]:
    return build_repository_chunks(TOY_REPOSITORY).chunks


def _chunk(
    *,
    path: str,
    symbol: str,
    source_text: str,
) -> CodeChunk:
    return CodeChunk(
        chunk_id=f"{path}::function::{symbol}::1-2",
        path=path,
        language="python",
        chunk_type=ChunkType.FUNCTION,
        symbol=symbol,
        qualified_symbol=symbol,
        parent_class=None,
        start_line=1,
        end_line=2,
        source_text=source_text,
        content_hash=sha256(source_text.encode("utf-8")).hexdigest(),
        imports=(),
    )


def test_fts5_is_available_and_index_can_be_created() -> None:
    assert is_fts5_available() is True

    with SQLiteLexicalIndex() as index:
        assert index.chunk_count == 0


def test_canonical_chunks_can_be_indexed() -> None:
    chunks = _toy_chunks()

    with SQLiteLexicalIndex() as index:
        indexed_count = index.rebuild(chunks)

        assert indexed_count == 3
        assert index.chunk_count == 3


def test_exact_symbol_query_retrieves_expected_function_first() -> None:
    chunks = _toy_chunks()

    with SQLiteLexicalIndex() as index:
        index.rebuild(chunks)
        results = index.search_lexical("apply_discount")

    assert results[0].chunk_id == "pricing.py::function::apply_discount::4-7"
    assert results[0].rank == 1


def test_filename_query_retrieves_pricing_function() -> None:
    with SQLiteLexicalIndex() as index:
        index.rebuild(_toy_chunks())
        results = index.search_lexical("pricing.py")

    function = next(result for result in results if result.path == "pricing.py")
    assert function.symbol == "apply_discount"


def test_exact_test_name_retrieves_expected_test_first() -> None:
    with SQLiteLexicalIndex() as index:
        index.rebuild(_toy_chunks())
        results = index.search_lexical(
            "test_twenty_percent_discount_reduces_price"
        )

    assert results[0].chunk_type is ChunkType.TEST
    assert results[0].qualified_symbol == (
        "test_twenty_percent_discount_reduces_price"
    )


def test_top_k_is_enforced_and_validated() -> None:
    with SQLiteLexicalIndex() as index:
        index.rebuild(_toy_chunks())

        assert len(index.search_lexical("discount", k=1)) == 1
        assert len(index.search_lexical("discount", k=2)) == 2
        with pytest.raises(ValueError, match="positive integer"):
            index.search_lexical("discount", k=0)


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_blank_query_is_rejected(query: str) -> None:
    with SQLiteLexicalIndex() as index:
        with pytest.raises(LexicalQueryError, match="must not be blank"):
            index.search_lexical(query)


def test_user_query_cannot_inject_sql_or_fts_syntax() -> None:
    with SQLiteLexicalIndex() as index:
        index.rebuild(_toy_chunks())

        results = index.search_lexical(
            'apply_discount" OR 1=1; DROP TABLE lexical_chunks; --'
        )
        assert results[0].symbol == "apply_discount"
        assert index.chunk_count == 3
        assert index.search_lexical('"unterminated') == ()


def test_raw_bm25_scores_sort_ascending_with_lower_score_better() -> None:
    strong = _chunk(
        path="strong.py",
        symbol="target",
        source_text="def target():\n    return 'target target'",
    )
    weak = _chunk(
        path="weak.py",
        symbol="helper",
        source_text="def helper():\n    return 'target'",
    )

    with SQLiteLexicalIndex() as index:
        index.rebuild((weak, strong))
        results = index.search_lexical("target")

    assert [result.symbol for result in results] == ["target", "helper"]
    assert results[0].bm25_score < results[1].bm25_score < 0
    assert [result.rank for result in results] == [1, 2]


def test_equal_bm25_scores_tie_break_by_chunk_id() -> None:
    second = _chunk(
        path="b.py",
        symbol="helper",
        source_text="def helper():\n    return 'target'",
    )
    first = _chunk(
        path="a.py",
        symbol="helper",
        source_text="def helper():\n    return 'target'",
    )

    with SQLiteLexicalIndex() as index:
        index.rebuild((second, first))
        results = index.search_lexical("target")

    assert results[0].bm25_score == results[1].bm25_score
    assert [result.chunk_id for result in results] == sorted(
        [first.chunk_id, second.chunk_id]
    )


def test_result_maps_back_to_exact_canonical_chunk_provenance() -> None:
    chunks = _toy_chunks()
    expected = next(chunk for chunk in chunks if chunk.symbol == "apply_discount")

    with SQLiteLexicalIndex() as index:
        index.rebuild(chunks)
        result = index.search_lexical("apply_discount", k=1)[0]

    assert result.chunk == expected
    assert result.chunk_id == expected.chunk_id
    assert result.path == "pricing.py"
    assert (result.start_line, result.end_line) == (4, 7)


def test_rebuild_is_deterministic_and_does_not_duplicate_chunks() -> None:
    chunks = _toy_chunks()

    with SQLiteLexicalIndex() as index:
        index.rebuild(chunks)
        first = index.search_lexical("discount")
        index.rebuild(reversed(chunks))
        second = index.search_lexical("discount")

        assert index.chunk_count == 3
        assert first == second
        assert len({result.chunk_id for result in second}) == len(second)

        with pytest.raises(DuplicateChunkIdError, match="Duplicate chunk_id"):
            index.rebuild((*chunks, chunks[0]))
        assert index.chunk_count == 3
