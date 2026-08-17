from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from app.chunking import (
    ChunkType,
    CodeChunk,
    ConstructType,
    PythonConstruct,
    build_code_chunks,
    build_python_chunk,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOY_REPOSITORY = REPOSITORY_ROOT / "fixtures" / "toy-repo"


def _construct(
    *,
    construct_type: ConstructType = ConstructType.FUNCTION,
    symbol: str = "calculate",
    source_text: str = "def calculate():\n    return 1",
    parent_class: str | None = None,
) -> PythonConstruct:
    return PythonConstruct(
        construct_type=construct_type,
        symbol=symbol,
        relative_path="src/example.py",
        start_line=3,
        end_line=4,
        source_text=source_text,
        parent_class=parent_class,
    )


def _chunk_by_symbol(
    chunks: tuple[CodeChunk, ...], symbol: str
) -> CodeChunk:
    return next(chunk for chunk in chunks if chunk.symbol == symbol)


def test_function_construct_maps_to_code_chunk() -> None:
    chunk = build_python_chunk(_construct())

    assert chunk.chunk_type is ChunkType.FUNCTION
    assert chunk.language == "python"
    assert chunk.symbol == "calculate"
    assert chunk.qualified_symbol == "calculate"
    assert chunk.parent_class is None
    assert chunk.chunk_id == "src/example.py::function::calculate::3-4"


def test_pytest_function_maps_to_test_chunk() -> None:
    chunk = build_python_chunk(
        _construct(
            construct_type=ConstructType.TEST_FUNCTION,
            symbol="test_calculate",
        )
    )

    assert chunk.chunk_type is ChunkType.TEST
    assert chunk.chunk_id == "src/example.py::test::test_calculate::3-4"


def test_method_qualified_symbol_preserves_parent_class() -> None:
    chunk = build_python_chunk(
        _construct(
            construct_type=ConstructType.METHOD,
            symbol="greet",
            parent_class="Greeter",
        )
    )

    assert chunk.chunk_type is ChunkType.METHOD
    assert chunk.parent_class == "Greeter"
    assert chunk.qualified_symbol == "Greeter.greet"
    assert chunk.chunk_id == "src/example.py::method::Greeter.greet::3-4"


def test_chunk_id_is_deterministic_and_machine_independent() -> None:
    construct = _construct()

    first = build_python_chunk(construct)
    second = build_python_chunk(construct)

    assert first.chunk_id == second.chunk_id
    assert str(REPOSITORY_ROOT) not in first.chunk_id
    assert "C:\\" not in first.chunk_id


def test_content_hash_is_sha256_of_exact_source() -> None:
    construct = _construct()

    first = build_python_chunk(construct)
    second = build_python_chunk(construct)

    assert first.content_hash == second.content_hash
    assert first.content_hash == sha256(
        construct.source_text.encode("utf-8")
    ).hexdigest()


def test_content_change_produces_different_hash_without_changing_identity() -> None:
    original = _construct()
    changed = replace(original, source_text="def calculate():\n    return 2")

    original_chunk = build_python_chunk(original)
    changed_chunk = build_python_chunk(changed)

    assert original_chunk.chunk_id == changed_chunk.chunk_id
    assert original_chunk.content_hash != changed_chunk.content_hash


def test_top_level_imports_are_extracted_and_sorted(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "module.py").write_text(
        "from __future__ import annotations\n"
        "import sys\n"
        "from decimal import Decimal\n"
        "import math as maths\n"
        "import sys\n\n"
        "def calculate():\n"
        "    import secrets\n"
        "    return Decimal(maths.sqrt(4))\n",
        encoding="utf-8",
    )

    chunks = build_code_chunks(repository)

    assert len(chunks) == 1
    assert chunks[0].imports == ("__future__", "decimal", "math", "sys")


def test_class_and_method_chunks_overlap_without_duplicate_methods(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "greeter.py").write_text(
        "class Greeter:\n"
        "    def greet(self) -> str:\n"
        "        return 'hello'\n",
        encoding="utf-8",
    )

    chunks = build_code_chunks(repository)

    assert [(chunk.chunk_type, chunk.qualified_symbol) for chunk in chunks] == [
        (ChunkType.CLASS, "Greeter"),
        (ChunkType.METHOD, "Greeter.greet"),
    ]
    assert len([chunk for chunk in chunks if chunk.symbol == "greet"]) == 1
    assert chunks[0].source_text.endswith(chunks[1].source_text)


def test_toy_repository_builds_exact_chunks_with_provenance() -> None:
    chunks = build_code_chunks(TOY_REPOSITORY)

    assert [
        (chunk.path, chunk.chunk_type, chunk.symbol, chunk.start_line, chunk.end_line)
        for chunk in chunks
    ] == [
        ("pricing.py", ChunkType.FUNCTION, "apply_discount", 4, 7),
        (
            "tests/test_pricing.py",
            ChunkType.TEST,
            "test_zero_percent_discount_keeps_price",
            4,
            5,
        ),
        (
            "tests/test_pricing.py",
            ChunkType.TEST,
            "test_twenty_percent_discount_reduces_price",
            8,
            9,
        ),
    ]

    source_lines = (TOY_REPOSITORY / "pricing.py").read_text(
        encoding="utf-8"
    ).splitlines()
    function = _chunk_by_symbol(chunks, "apply_discount")
    assert function.source_text == "\n".join(source_lines[3:7])
    assert function.chunk_id == "pricing.py::function::apply_discount::4-7"
    assert function.imports == ()

    test_chunks = [chunk for chunk in chunks if chunk.chunk_type is ChunkType.TEST]
    assert all(chunk.imports == ("pricing",) for chunk in test_chunks)


def test_repository_chunk_order_is_deterministic() -> None:
    first = build_code_chunks(TOY_REPOSITORY)
    second = build_code_chunks(TOY_REPOSITORY)

    assert first == second
    assert [chunk.chunk_id for chunk in first] == [
        "pricing.py::function::apply_discount::4-7",
        "tests/test_pricing.py::test::test_zero_percent_discount_keeps_price::4-5",
        "tests/test_pricing.py::test::test_twenty_percent_discount_reduces_price::8-9",
    ]
