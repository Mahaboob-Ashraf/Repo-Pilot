"""Serializable frozen retrieval-case definitions for local evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RetrievalCase:
    """One frozen query and its evaluation-only file/symbol relevance labels."""

    case_id: str
    query: str
    repository_ref: str
    relevant_files: tuple[str, ...]
    relevant_symbols: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _validate_nonblank(self.case_id, name="case_id")
        _validate_nonblank(self.query, name="query")
        _validate_relative_posix_path(self.repository_ref, name="repository_ref")
        if not isinstance(self.relevant_files, tuple) or not self.relevant_files:
            raise ValueError("relevant_files must be a nonempty tuple")
        _validate_unique_nonblank(self.relevant_files, name="relevant_files")
        for path in self.relevant_files:
            _validate_relative_posix_path(path, name="relevant_files")

        if self.relevant_symbols is not None:
            if not isinstance(self.relevant_symbols, tuple) or not self.relevant_symbols:
                raise ValueError(
                    "relevant_symbols must be None or a nonempty tuple"
                )
            _validate_unique_nonblank(
                self.relevant_symbols,
                name="relevant_symbols",
            )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON/CSV-friendly record."""

        return {
            "case_id": self.case_id,
            "query": self.query,
            "repository_ref": self.repository_ref,
            "relevant_files": list(self.relevant_files),
            "relevant_symbols": (
                list(self.relevant_symbols)
                if self.relevant_symbols is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RetrievalCase:
        """Construct and validate a case from serialized data."""

        if not isinstance(value, Mapping):
            raise ValueError("Invalid serialized retrieval case")
        try:
            files = value["relevant_files"]
            symbols = value.get("relevant_symbols")
            if not isinstance(files, (list, tuple)) or isinstance(files, str):
                raise ValueError("relevant_files must be a JSON array")
            if symbols is not None and (
                not isinstance(symbols, (list, tuple))
                or isinstance(symbols, str)
            ):
                raise ValueError("relevant_symbols must be null or a JSON array")
            return cls(
                case_id=str(value["case_id"]),
                query=str(value["query"]),
                repository_ref=str(value["repository_ref"]),
                relevant_files=tuple(str(path) for path in files),
                relevant_symbols=(
                    tuple(str(symbol) for symbol in symbols)
                    if symbols is not None
                    else None
                ),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError("Invalid serialized retrieval case") from exc


def load_retrieval_cases(path: str | Path) -> tuple[RetrievalCase, ...]:
    """Load a deterministic JSON array of frozen retrieval cases."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load retrieval cases from {path}") from exc
    if not isinstance(payload, list):
        raise ValueError("Retrieval case file must contain a JSON array")

    cases = tuple(RetrievalCase.from_dict(item) for item in payload)
    case_ids = tuple(case.case_id for case in cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Retrieval case IDs must be unique")
    return cases


def _validate_nonblank(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _validate_unique_nonblank(values: tuple[str, ...], *, name: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} must contain only nonblank strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")


def _validate_relative_posix_path(value: object, *, name: str) -> None:
    _validate_nonblank(value, name=name)
    assert isinstance(value, str)
    if "\\" in value:
        raise ValueError(f"{name} must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ValueError(f"{name} must be a normalized relative POSIX path")
