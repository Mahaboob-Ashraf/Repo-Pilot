from pathlib import Path

import pytest

from app.chunking import (
    ConstructType,
    PathOutsideRepositoryError,
    PythonConstruct,
    extract_python_constructs,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOY_REPOSITORY = REPOSITORY_ROOT / "fixtures" / "toy-repo"


def _source_lines(path: Path, start_line: int, end_line: int) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start_line - 1 : end_line])


def _construct_by_symbol(
    constructs: list[PythonConstruct], symbol: str
) -> PythonConstruct:
    return next(construct for construct in constructs if construct.symbol == symbol)


def test_extracts_apply_discount_with_exact_range_and_source() -> None:
    source_path = TOY_REPOSITORY / "pricing.py"

    constructs = extract_python_constructs(TOY_REPOSITORY, "pricing.py")

    assert len(constructs) == 1
    function = constructs[0]
    assert function.construct_type is ConstructType.FUNCTION
    assert function.symbol == "apply_discount"
    assert function.relative_path == "pricing.py"
    assert (function.start_line, function.end_line) == (4, 7)
    assert function.source_text == _source_lines(source_path, 4, 7)
    assert function.parent_class is None


def test_extracts_and_classifies_both_pytest_functions() -> None:
    source_path = TOY_REPOSITORY / "tests" / "test_pricing.py"

    constructs = extract_python_constructs(
        TOY_REPOSITORY, "tests/test_pricing.py"
    )

    assert [construct.symbol for construct in constructs] == [
        "test_zero_percent_discount_keeps_price",
        "test_twenty_percent_discount_reduces_price",
    ]
    assert all(
        construct.construct_type is ConstructType.TEST_FUNCTION
        for construct in constructs
    )
    assert [
        (construct.start_line, construct.end_line) for construct in constructs
    ] == [(4, 5), (8, 9)]
    assert all(construct.relative_path == "tests/test_pricing.py" for construct in constructs)
    assert all(
        construct.source_text
        == _source_lines(source_path, construct.start_line, construct.end_line)
        for construct in constructs
    )


def test_extracts_class_and_nested_method_with_parent_context(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    source_path = repository / "greeter.py"
    source_path.write_text(
        "class Greeter:\n"
        "    def greet(self, name: str) -> str:\n"
        "        return f\"Hello, {name}\"\n",
        encoding="utf-8",
    )

    constructs = extract_python_constructs(repository, source_path)

    class_construct = _construct_by_symbol(constructs, "Greeter")
    method_construct = _construct_by_symbol(constructs, "greet")
    assert class_construct.construct_type is ConstructType.CLASS
    assert (class_construct.start_line, class_construct.end_line) == (1, 3)
    assert method_construct.construct_type is ConstructType.METHOD
    assert method_construct.parent_class == "Greeter"
    assert (method_construct.start_line, method_construct.end_line) == (2, 3)
    file_text = source_path.read_bytes().decode("utf-8")
    expected_method_source = file_text[file_text.index("def greet") :].rstrip(
        "\r\n"
    )
    assert method_construct.source_text == expected_method_source


def test_rejects_source_path_outside_repository_root(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside_source = tmp_path / "outside.py"
    outside_source.write_text("def escaped():\n    return True\n", encoding="utf-8")

    with pytest.raises(
        PathOutsideRepositoryError,
        match="must remain inside the repository root",
    ):
        extract_python_constructs(repository, outside_source)
