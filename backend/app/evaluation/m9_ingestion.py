"""Subprocess-isolated M9 diagnostics for the production M1 chunking path."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from app.chunking import build_repository_chunks
from app.chunking.code_chunks import build_python_chunk
from app.chunking.python_parser import parse_python_file
from app.evaluation.m9_models import M9Manifest, ProductionCaseInput
from app.ingestion import discover_repository


_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def diagnose_manifest_ingestion(
    manifest: M9Manifest,
    *,
    fixture_root: Path,
) -> list[dict[str, Any]]:
    """Diagnose every frozen case without allowing one parser exit to hide another."""

    return [
        diagnose_case_ingestion(
            ProductionCaseInput.from_case(case, fixture_root=fixture_root)
        )
        for case in manifest.cases
    ]


def diagnose_case_ingestion(case_input: ProductionCaseInput) -> dict[str, Any]:
    inventory = discover_repository(case_input.repository_root)
    python_files = tuple(
        item.relative_path
        for item in inventory.parser_supported_files
        if item.language == "python"
    )
    file_results: list[dict[str, Any]] = []
    for relative_path in python_files:
        file_results.append(
            _run_worker("file", case_input.repository_root, relative_path)
        )

    failed_file = next(
        (item["relative_path"] for item in file_results if not item["success"]),
        None,
    )
    aggregate_result: dict[str, Any] | None = None
    if failed_file is None:
        aggregate_result = _run_worker("repository", case_input.repository_root)

    success = failed_file is None and bool(
        aggregate_result and aggregate_result["success"]
    )
    chunk_count = (
        aggregate_result.get("chunk_count")
        if aggregate_result and aggregate_result["success"]
        else None
    )
    failure = next(
        (item for item in file_results if not item["success"]),
        aggregate_result if aggregate_result and not aggregate_result["success"] else None,
    )
    return {
        "case_id": case_input.case_id,
        "repository_id": case_input.repository_id,
        "discovered_file_count": len(inventory.files),
        "python_file_count": len(python_files),
        "chunk_count": chunk_count,
        "success": success,
        "failing_file": failed_file,
        "error_type": failure.get("error_type") if failure else None,
        "error_message": failure.get("error_message") if failure else None,
        "process_terminated": bool(failure and failure.get("process_terminated")),
        "files": file_results,
    }


def _run_worker(
    operation: str,
    repository_root: Path,
    relative_path: str | None = None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "app.evaluation.m9_ingestion",
        "--worker",
        operation,
        "--repository-root",
        str(repository_root),
    ]
    if relative_path is not None:
        command.extend(("--relative-path", relative_path))
    try:
        completed = subprocess.run(
            command,
            cwd=_BACKEND_ROOT,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "relative_path": relative_path,
            "success": False,
            "error_type": "WorkerTimeout",
            "error_message": "isolated ingestion worker exceeded 60 seconds",
            "process_terminated": True,
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    if completed.returncode == 0 and isinstance(payload, dict):
        return payload
    if isinstance(payload, dict):
        return payload
    return {
        "relative_path": relative_path,
        "success": False,
        "error_type": "WorkerProcessExit",
        "error_message": f"isolated ingestion worker exited with code {completed.returncode}",
        "process_terminated": True,
    }


def _worker(operation: str, repository_root: Path, relative_path: str | None) -> int:
    try:
        if operation == "file":
            if relative_path is None:
                raise ValueError("file worker requires a relative path")
            parsed = parse_python_file(repository_root, relative_path)
            chunks = tuple(
                build_python_chunk(item, imports=parsed.imports)
                for item in parsed.constructs
            )
            payload = {
                "relative_path": relative_path,
                "success": True,
                "construct_count": len(parsed.constructs),
                "chunk_count": len(chunks),
                "error_type": None,
                "error_message": None,
                "process_terminated": False,
            }
        elif operation == "repository":
            result = build_repository_chunks(repository_root)
            payload = {
                "relative_path": None,
                "success": True,
                "chunk_count": result.chunk_count,
                "error_type": None,
                "error_message": None,
                "process_terminated": False,
            }
        else:
            raise ValueError("unknown ingestion worker operation")
    except Exception as exc:
        safe_message = str(exc).replace(str(repository_root), "<fixture>")[:300]
        payload = {
            "relative_path": relative_path,
            "success": False,
            "error_type": type(exc).__name__,
            "error_message": safe_message,
            "process_terminated": False,
        }
        print(json.dumps(payload, sort_keys=True))
        return 2
    print(json.dumps(payload, sort_keys=True))
    return 0
def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("file", "repository"), required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--relative-path")
    args = parser.parse_args(argv)
    return _worker(args.worker, args.repository_root, args.relative_path)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))


__all__ = ["diagnose_case_ingestion", "diagnose_manifest_ingestion"]
