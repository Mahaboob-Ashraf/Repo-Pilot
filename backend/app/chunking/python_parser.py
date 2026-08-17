"""Tree-sitter extraction of semantic constructs from Python source files."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tree_sitter import Language, Node, Parser
import tree_sitter_python


_PYTHON_LANGUAGE = Language(tree_sitter_python.language())


class ConstructType(StrEnum):
    """Python constructs currently recognized by the parsing foundation."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    TEST_FUNCTION = "test_function"


@dataclass(frozen=True, slots=True)
class PythonConstruct:
    """A semantic Python construct with source provenance."""

    construct_type: ConstructType
    symbol: str
    relative_path: str
    start_line: int
    end_line: int
    source_text: str
    parent_class: str | None = None


@dataclass(frozen=True, slots=True)
class PythonParseResult:
    """Constructs and deterministic module metadata from one Python parse."""

    constructs: tuple[PythonConstruct, ...]
    imports: tuple[str, ...]


class PathOutsideRepositoryError(ValueError):
    """Raised when a requested source path resolves outside its repository."""


def extract_python_constructs(
    repository_root: str | Path,
    source_path: str | Path,
) -> list[PythonConstruct]:
    """Extract supported constructs from one UTF-8 Python file inside a root."""

    return list(parse_python_file(repository_root, source_path).constructs)


def parse_python_file(
    repository_root: str | Path,
    source_path: str | Path,
) -> PythonParseResult:
    """Parse one UTF-8 Python file into constructs and module imports."""

    source_file, relative_path = _resolve_source_path(repository_root, source_path)

    source_bytes = source_file.read_bytes()
    try:
        source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Python source must be UTF-8 encoded") from exc

    tree = Parser(_PYTHON_LANGUAGE).parse(source_bytes)
    constructs: list[PythonConstruct] = []

    for child in tree.root_node.named_children:
        definition, span = _unwrap_definition(child)
        if definition is None:
            continue

        if definition.type == "function_definition":
            constructs.append(
                _build_function_construct(
                    definition=definition,
                    span=span,
                    source_bytes=source_bytes,
                    relative_path=relative_path,
                    parent_class=None,
                )
            )
        elif definition.type == "class_definition":
            class_name = _node_name(definition, source_bytes)
            constructs.append(
                _build_construct(
                    construct_type=ConstructType.CLASS,
                    symbol=class_name,
                    span=span,
                    source_bytes=source_bytes,
                    relative_path=relative_path,
                )
            )
            constructs.extend(
                _extract_class_methods(
                    definition,
                    class_name=class_name,
                    source_bytes=source_bytes,
                    relative_path=relative_path,
                )
            )

    return PythonParseResult(
        constructs=tuple(constructs),
        imports=_extract_top_level_imports(tree.root_node, source_bytes),
    )


def _resolve_source_path(
    repository_root: str | Path,
    source_path: str | Path,
) -> tuple[Path, str]:
    try:
        root = Path(repository_root).resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("Repository root does not exist") from exc
    if not root.is_dir():
        raise ValueError("Repository root must be a directory")

    requested_path = Path(source_path)
    candidate = requested_path if requested_path.is_absolute() else root / requested_path
    try:
        source_file = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("Python source file does not exist") from exc

    try:
        relative_path = source_file.relative_to(root).as_posix()
    except ValueError as exc:
        raise PathOutsideRepositoryError(
            "Python source path must remain inside the repository root"
        ) from exc

    if not source_file.is_file():
        raise ValueError("Python source path must identify a file")
    if source_file.suffix.lower() != ".py":
        raise ValueError("Only Python source files are supported")

    return source_file, relative_path


def _unwrap_definition(node: Node) -> tuple[Node | None, Node]:
    if node.type in {"function_definition", "class_definition"}:
        return node, node
    if node.type != "decorated_definition":
        return None, node

    for child in node.named_children:
        if child.type in {"function_definition", "class_definition"}:
            return child, node
    return None, node


def _extract_class_methods(
    class_definition: Node,
    *,
    class_name: str,
    source_bytes: bytes,
    relative_path: str,
) -> list[PythonConstruct]:
    body = class_definition.child_by_field_name("body")
    if body is None:
        return []

    methods: list[PythonConstruct] = []
    for child in body.named_children:
        definition, span = _unwrap_definition(child)
        if definition is None or definition.type != "function_definition":
            continue
        methods.append(
            _build_function_construct(
                definition=definition,
                span=span,
                source_bytes=source_bytes,
                relative_path=relative_path,
                parent_class=class_name,
            )
        )
    return methods


def _build_function_construct(
    *,
    definition: Node,
    span: Node,
    source_bytes: bytes,
    relative_path: str,
    parent_class: str | None,
) -> PythonConstruct:
    symbol = _node_name(definition, source_bytes)
    if parent_class is not None:
        construct_type = ConstructType.METHOD
    elif symbol.startswith("test_"):
        construct_type = ConstructType.TEST_FUNCTION
    else:
        construct_type = ConstructType.FUNCTION

    return _build_construct(
        construct_type=construct_type,
        symbol=symbol,
        span=span,
        source_bytes=source_bytes,
        relative_path=relative_path,
        parent_class=parent_class,
    )


def _build_construct(
    *,
    construct_type: ConstructType,
    symbol: str,
    span: Node,
    source_bytes: bytes,
    relative_path: str,
    parent_class: str | None = None,
) -> PythonConstruct:
    return PythonConstruct(
        construct_type=construct_type,
        symbol=symbol,
        relative_path=relative_path,
        start_line=span.start_point.row + 1,
        end_line=span.end_point.row + 1,
        source_text=source_bytes[span.start_byte : span.end_byte].decode("utf-8"),
        parent_class=parent_class,
    )


def _node_name(definition: Node, source_bytes: bytes) -> str:
    name = definition.child_by_field_name("name")
    if name is None:
        raise ValueError(f"Tree-sitter {definition.type} node has no name")
    return source_bytes[name.start_byte : name.end_byte].decode("utf-8")


def _extract_top_level_imports(
    root_node: Node,
    source_bytes: bytes,
) -> tuple[str, ...]:
    imported_modules: set[str] = set()

    for child in root_node.named_children:
        if child.type == "import_statement":
            for imported_name in child.named_children:
                name_node = (
                    imported_name.child_by_field_name("name")
                    if imported_name.type == "aliased_import"
                    else imported_name
                )
                if name_node is not None:
                    imported_modules.add(_node_text(name_node, source_bytes))
        elif child.type == "import_from_statement":
            module_name = child.child_by_field_name("module_name")
            if module_name is not None:
                imported_modules.add(_node_text(module_name, source_bytes))
        elif child.type == "future_import_statement":
            imported_modules.add("__future__")

    return tuple(sorted(imported_modules))


def _node_text(node: Node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8")
