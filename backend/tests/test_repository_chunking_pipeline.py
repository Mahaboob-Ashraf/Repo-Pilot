from pathlib import Path

import pytest

from app.chunking import (
    ChunkType,
    PythonSyntaxError,
    build_repository_chunks,
)
from app.ingestion import RepositoryRootError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOY_REPOSITORY = REPOSITORY_ROOT / "fixtures" / "toy-repo"


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _source_for_range(path: Path, start_line: int, end_line: int) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start_line - 1 : end_line])


def test_full_toy_repository_produces_expected_summary_and_chunks() -> None:
    result = build_repository_chunks(TOY_REPOSITORY)

    assert result.repository_root == TOY_REPOSITORY.resolve()
    assert result.discovered_file_count == 2
    assert result.language_counts == {"python": 2}
    assert result.parser_supported_file_count == 2
    assert result.parser_supported_paths == (
        "pricing.py",
        "tests/test_pricing.py",
    )
    assert result.chunk_count == 3
    assert [
        (
            chunk.chunk_id,
            chunk.chunk_type,
            chunk.path,
            chunk.start_line,
            chunk.end_line,
            chunk.content_hash,
        )
        for chunk in result.chunks
    ] == [
        (
            "pricing.py::function::apply_discount::4-7",
            ChunkType.FUNCTION,
            "pricing.py",
            4,
            7,
            "f8b9c570dd350555a000686e9f5594903aaf158c9be2827a1c41e01e11408d99",
        ),
        (
            "tests/test_pricing.py::test::"
            "test_zero_percent_discount_keeps_price::4-5",
            ChunkType.TEST,
            "tests/test_pricing.py",
            4,
            5,
            "d03c05c9af5e4281f90cdeafd05dae06fbb2f9b6b25da37e23b4bb4f5ee2ef10",
        ),
        (
            "tests/test_pricing.py::test::"
            "test_twenty_percent_discount_reduces_price::8-9",
            ChunkType.TEST,
            "tests/test_pricing.py",
            8,
            9,
            "8e8ba94954062684b815bd86feecac2d62194c57805b9a7d3b7a956b5ef17b17",
        ),
    ]
    assert all(
        chunk.source_text
        == _source_for_range(
            result.repository_root / chunk.path,
            chunk.start_line,
            chunk.end_line,
        )
        for chunk in result.chunks
    )


def test_full_pipeline_is_deterministic_across_repeated_runs() -> None:
    first = build_repository_chunks(TOY_REPOSITORY)
    second = build_repository_chunks(TOY_REPOSITORY)

    assert first == second
    assert [chunk.chunk_id for chunk in first.chunks] == [
        chunk.chunk_id for chunk in second.chunks
    ]
    assert [chunk.content_hash for chunk in first.chunks] == [
        chunk.content_hash for chunk in second.chunks
    ]


def test_class_and_method_survive_complete_repository_pipeline(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _write(
        repository / "greeter.py",
        "class Greeter:\n"
        "    def greet(self, name: str) -> str:\n"
        "        return f'Hello, {name}'\n",
    )

    result = build_repository_chunks(repository)

    assert result.discovered_file_count == 1
    assert result.parser_supported_paths == ("greeter.py",)
    assert [
        (
            chunk.chunk_type,
            chunk.qualified_symbol,
            chunk.start_line,
            chunk.end_line,
        )
        for chunk in result.chunks
    ] == [
        (ChunkType.CLASS, "Greeter", 1, 3),
        (ChunkType.METHOD, "Greeter.greet", 2, 3),
    ]


def test_repository_with_no_recognized_source_returns_empty_result(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _write(repository / "README.md", "No recognized source files.\n")

    result = build_repository_chunks(repository)

    assert result.discovered_file_count == 0
    assert result.language_counts == {}
    assert result.parser_supported_file_count == 0
    assert result.parser_supported_paths == ()
    assert result.chunk_count == 0
    assert result.chunks == ()


def test_detected_but_unsupported_repository_returns_inventory_without_chunks(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _write(repository / "app.js", "export const value = 1;\n")
    _write(repository / "src" / "main.ts", "export const value: number = 1;\n")

    result = build_repository_chunks(repository)

    assert result.discovered_file_count == 2
    assert result.language_counts == {"javascript": 1, "typescript": 1}
    assert result.parser_supported_file_count == 0
    assert result.parser_supported_paths == ()
    assert result.chunk_count == 0
    assert result.chunks == ()


def test_invalid_repository_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RepositoryRootError, match="does not exist"):
        build_repository_chunks(tmp_path / "missing")


def test_malformed_python_rejects_the_repository_build(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _write(repository / "broken.py", "def broken(:\n    return True\n")

    with pytest.raises(PythonSyntaxError) as exc_info:
        build_repository_chunks(repository)

    error = exc_info.value
    assert error.relative_path == "broken.py"
    assert error.node_type in {"ERROR", "MISSING"}
    assert error.start_line >= 1
    assert "broken.py" in str(error)
    assert "Tree-sitter reported invalid Python syntax" in str(error)


def test_canonical_toy_bug_fixture_source_remains_unchanged() -> None:
    assert (TOY_REPOSITORY / "pricing.py").read_text(encoding="utf-8") == (
        '"""Small pricing helpers for the RepoPilot toy fixture."""\n\n\n'
        "def apply_discount(price: float, discount_percent: float) -> float:\n"
        '    """Return a price after applying a percentage discount."""\n\n'
        "    return price * (1 + discount_percent / 100)\n\n"
    )
    assert (TOY_REPOSITORY / "tests" / "test_pricing.py").read_text(
        encoding="utf-8"
    ) == (
        "from pricing import apply_discount\n\n\n"
        "def test_zero_percent_discount_keeps_price() -> None:\n"
        "    assert apply_discount(50.0, 0.0) == 50.0\n\n\n"
        "def test_twenty_percent_discount_reduces_price() -> None:\n"
        "    assert apply_discount(100.0, 20.0) == 80.0\n\n"
    )
