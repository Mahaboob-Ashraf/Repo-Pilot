import os
from pathlib import Path

import pytest

from app.chunking import extract_python_constructs
from app.ingestion import (
    EXCLUDED_DIRECTORY_NAMES,
    RepositoryRootError,
    detect_language,
    discover_repository,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOY_REPOSITORY = REPOSITORY_ROOT / "fixtures" / "toy-repo"


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_discovers_python_files_recursively_in_deterministic_order(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _write(repository / "z.py", "Z = 1\n")
    _write(repository / "src" / "b.py", "B = 1\n")
    _write(repository / "a.py", "A = 1\n")

    first = discover_repository(repository)
    second = discover_repository(repository)

    expected_paths = ("a.py", "src/b.py", "z.py")
    assert tuple(source.relative_path for source in first.files) == expected_paths
    assert second == first
    assert first.language_counts == {"python": 3}
    assert all(source.size_bytes > 0 for source in first.files)


@pytest.mark.parametrize(
    ("file_name", "expected_language"),
    [
        ("module.py", "python"),
        ("component.JSX", "javascript"),
        ("script.js", "javascript"),
        ("screen.tsx", "typescript"),
        ("types.TS", "typescript"),
        ("README.md", None),
    ],
)
def test_detects_language_by_extension(
    file_name: str, expected_language: str | None
) -> None:
    assert detect_language(file_name) == expected_language


def test_excluded_directories_are_not_traversed(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    for directory_name in EXCLUDED_DIRECTORY_NAMES:
        _write(repository / directory_name / "hidden.py", "HIDDEN = True\n")
    _write(repository / "visible.py", "VISIBLE = True\n")

    inventory = discover_repository(repository)

    assert tuple(source.relative_path for source in inventory.files) == (
        "visible.py",
    )


def test_recognized_but_unsupported_languages_remain_inventory_metadata(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    _write(repository / "app.py", "VALUE = 1\n")
    _write(repository / "web" / "app.ts", "export const value = 1;\n")
    _write(repository / "README.md", "not source inventory\n")

    inventory = discover_repository(repository)

    assert inventory.language_counts == {"python": 1, "typescript": 1}
    assert tuple(source.relative_path for source in inventory.files) == (
        "app.py",
        "web/app.ts",
    )
    assert inventory.files[0].parser_supported is True
    assert inventory.files[1].parser_supported is False
    assert inventory.parser_supported_files == (inventory.files[0],)


def test_invalid_repository_roots_are_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(RepositoryRootError, match="does not exist"):
        discover_repository(missing)
    with pytest.raises(RepositoryRootError, match="must be a directory"):
        discover_repository(file_path)


def test_symlinked_source_outside_root_is_not_discovered(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside_source = tmp_path / "outside.py"
    outside_source.write_text("ESCAPED = True\n", encoding="utf-8")
    linked_source = repository / "linked.py"

    try:
        os.symlink(outside_source, linked_source)
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable on this platform: {exc}")

    inventory = discover_repository(repository)

    assert inventory.files == ()


def test_toy_repository_inventory_finds_expected_python_files() -> None:
    inventory = discover_repository(TOY_REPOSITORY)

    assert tuple(source.relative_path for source in inventory.files) == (
        "pricing.py",
        "tests/test_pricing.py",
    )
    assert inventory.language_counts == {"python": 2}
    assert inventory.parser_supported_files == inventory.files


def test_discovered_toy_python_files_integrate_with_parser() -> None:
    inventory = discover_repository(TOY_REPOSITORY)

    symbols = {
        construct.symbol
        for source_file in inventory.parser_supported_files
        for construct in extract_python_constructs(
            inventory.repository_root,
            source_file.relative_path,
        )
    }

    assert symbols == {
        "apply_discount",
        "test_zero_percent_discount_keeps_price",
        "test_twenty_percent_discount_reduces_price",
    }

