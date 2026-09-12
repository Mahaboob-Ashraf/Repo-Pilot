"""Strict pytest selector parsing with no shell or executable semantics."""

from __future__ import annotations

from pathlib import Path
import re

from app.patching import PatchValidationError, validate_repository_relative_path
from app.sandbox.errors import TestConfigurationError


_NODE_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[A-Za-z0-9_.:-]+\])?$")


def validate_pytest_selectors(
    selectors: tuple[str, ...],
    *,
    repository_root: Path,
) -> tuple[str, ...]:
    validated: list[str] = []
    for selector in selectors:
        if (
            not isinstance(selector, str)
            or not selector
            or selector != selector.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in selector)
        ):
            raise TestConfigurationError("pytest selector contains invalid text")
        parts = selector.split("::")
        if not parts or not parts[0].endswith(".py"):
            raise TestConfigurationError(
                "pytest selector must start with a repository-relative .py path"
            )
        try:
            relative = validate_repository_relative_path(parts[0])
        except PatchValidationError as exc:
            raise TestConfigurationError(
                "pytest selector path must be repository-relative"
            ) from exc
        if any(not _NODE_SEGMENT.fullmatch(segment) for segment in parts[1:]):
            raise TestConfigurationError("pytest selector node segment is invalid")
        candidate = repository_root.joinpath(*relative.parts)
        if candidate.is_symlink():
            raise TestConfigurationError("pytest selector must not target a symlink")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(repository_root.resolve())
        except (OSError, ValueError) as exc:
            raise TestConfigurationError("pytest selector file does not exist") from exc
        if not resolved.is_file():
            raise TestConfigurationError("pytest selector must target a regular file")
        validated.append(selector)
    return tuple(validated)


def pytest_argv(selectors: tuple[str, ...]) -> tuple[str, ...]:
    """Return the fixed in-container executable and literal pytest arguments."""

    return (
        "python",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        *selectors,
    )


__all__ = ["pytest_argv", "validate_pytest_selectors"]
