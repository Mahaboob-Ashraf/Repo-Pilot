"""Local application composition for the review-workspace HTTP boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
from typing import Protocol
from uuid import uuid4

from chromadb.errors import ChromaError

from app.chunking import build_repository_chunks
from app.context_packing import ContextPackError, ContextPacker, StructuralContextPipeline
from app.critic import CriticAssessmentStore, CriticService, StructuredCritic
from app.exporting import FinalReviewDecision, PatchExporter
from app.ingestion import RepositoryRootError
from app.patching import ApprovedPatchService, StructuredPatcher, WorkspaceManager
from app.planning import StructuredPlanner
from app.providers.embeddings import EmbeddingProviderError
from app.providers.ollama import OllamaProvider
from app.providers.ollama_embeddings import OllamaEmbeddingProvider
from app.retrieval import (
    ChromaVectorIndex,
    HybridRetriever,
    SQLiteLexicalIndex,
    LexicalQueryError,
    StructuralExpander,
    StructuralIndex,
    VectorRetrievalError,
)
from app.sandbox import (
    ApprovedPatchTestService,
    DisposableTestSnapshotManager,
    DockerTestRunner,
    TestResultStore,
    TestRunRequest,
)
from app.workflow.models import ApprovalDecision, PlanReviewResult, WorkflowStatus
from app.workflow.service import PlanReviewService, open_sqlite_plan_review_service
from app.config import OllamaEmbeddingSettings, Settings


DEFAULT_CONTEXT_BUDGET = 16_384
DEFAULT_RETRIEVAL_TOP_K = 5


class WorkflowApplicationError(RuntimeError):
    """Bounded failure safe for translation at the HTTP boundary."""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class WorkflowMetadata:
    thread_id: str
    repository_path: str
    issue: str

    @property
    def repository_name(self) -> str:
        return Path(self.repository_path).name or self.repository_path


@dataclass(frozen=True, slots=True)
class WorkflowReview:
    metadata: WorkflowMetadata
    result: PlanReviewResult


class WorkflowApplication(Protocol):
    async def create_workflow(
        self, *, repository_path: str, issue: str, thread_id: str | None = None
    ) -> WorkflowReview: ...

    async def get_workflow(self, *, thread_id: str) -> WorkflowReview: ...

    async def submit_plan_decision(
        self, *, thread_id: str, decision: ApprovalDecision
    ) -> WorkflowReview: ...

    async def submit_final_decision(
        self, *, thread_id: str, decision: FinalReviewDecision
    ) -> WorkflowReview: ...


class WorkflowThreadIndex:
    """Minimal durable lookup needed to rebuild repository-specific services."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_threads (
                    thread_id TEXT PRIMARY KEY,
                    repository_path TEXT NOT NULL
                )
                """
            )

    def get(self, thread_id: str) -> WorkflowMetadata | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT thread_id, repository_path "
                "FROM workflow_threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return WorkflowMetadata(
            thread_id=str(row["thread_id"]),
            repository_path=str(row["repository_path"]),
            issue="",
        )

    def add(self, metadata: WorkflowMetadata) -> None:
        try:
            with self._connect() as connection:
                columns = {
                    str(row["name"])
                    for row in connection.execute(
                        "PRAGMA table_info(workflow_threads)"
                    ).fetchall()
                }
                if "issue" in columns:
                    connection.execute(
                        "INSERT INTO workflow_threads "
                        "(thread_id, repository_path, issue) VALUES (?, ?, ?)",
                        (metadata.thread_id, metadata.repository_path, ""),
                    )
                else:
                    connection.execute(
                        "INSERT INTO workflow_threads "
                        "(thread_id, repository_path) VALUES (?, ?)",
                        (metadata.thread_id, metadata.repository_path),
                    )
        except sqlite3.IntegrityError as exc:
            raise WorkflowApplicationError(
                "thread_conflict",
                "That workflow thread ID already exists.",
                status_code=409,
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection


class LocalWorkflowApplication:
    """Compose M1–M6 services while leaving graph transitions authoritative."""

    def __init__(
        self,
        *,
        data_root: str | Path,
        generation_settings: Settings | None = None,
        embedding_settings: OllamaEmbeddingSettings | None = None,
        context_budget: int = DEFAULT_CONTEXT_BUDGET,
        retrieval_top_k: int = DEFAULT_RETRIEVAL_TOP_K,
    ) -> None:
        root = Path(data_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        self._root = root
        self._generation_settings = generation_settings or Settings.from_environment()
        self._embedding_settings = (
            embedding_settings or OllamaEmbeddingSettings.from_environment()
        )
        self._context_budget = context_budget
        self._retrieval_top_k = retrieval_top_k
        self._threads = WorkflowThreadIndex(root / "workflow-index.sqlite3")

    @classmethod
    def from_environment(cls) -> LocalWorkflowApplication:
        configured = os.getenv("REPOPILOT_DATA_DIR")
        if configured:
            root = Path(configured)
        else:
            local_app_data = os.getenv("LOCALAPPDATA")
            root = (
                Path(local_app_data) / "RepoPilot"
                if local_app_data
                else Path.home() / ".repopilot"
            )
        return cls(data_root=root)

    async def create_workflow(
        self,
        *,
        repository_path: str,
        issue: str,
        thread_id: str | None = None,
    ) -> WorkflowReview:
        stable_thread_id = thread_id or uuid4().hex
        if self._threads.get(stable_thread_id) is not None:
            raise WorkflowApplicationError(
                "thread_conflict",
                "That workflow thread ID already exists.",
                status_code=409,
            )
        try:
            chunking = build_repository_chunks(repository_path)
        except RepositoryRootError as exc:
            raise WorkflowApplicationError(
                "invalid_repository",
                "Repository path must identify a readable local directory.",
                status_code=400,
            ) from exc
        except (OSError, ValueError) as exc:
            raise WorkflowApplicationError(
                "invalid_repository",
                "The local Python repository could not be read safely.",
                status_code=400,
            ) from exc

        try:
            context_pack = await self._build_context(chunking.chunks, issue)
        except LexicalQueryError as exc:
            raise WorkflowApplicationError(
                "invalid_issue",
                "Issue text must contain searchable words or identifiers.",
                status_code=422,
            ) from exc
        except ContextPackError as exc:
            raise WorkflowApplicationError(
                "context_failed",
                "Repository evidence could not fit the fixed context budget.",
                status_code=422,
            ) from exc
        metadata = WorkflowMetadata(
            thread_id=stable_thread_id,
            repository_path=str(chunking.repository_root),
            issue=issue,
        )
        self._threads.add(metadata)
        async with self._service_for(metadata) as service:
            result = await service.start_plan_review(
                thread_id=stable_thread_id,
                context_pack=context_pack,
            )
        return WorkflowReview(metadata=metadata, result=result)

    async def get_workflow(self, *, thread_id: str) -> WorkflowReview:
        metadata = self._metadata_or_404(thread_id)
        async with self._service_for(metadata) as service:
            result = await service.get_plan_review(thread_id=thread_id)
        if result is None:
            raise WorkflowApplicationError(
                "workflow_not_found", "Workflow was not found.", status_code=404
            )
        return WorkflowReview(
            metadata=self._metadata_with_issue(metadata, result), result=result
        )

    async def submit_plan_decision(
        self, *, thread_id: str, decision: ApprovalDecision
    ) -> WorkflowReview:
        metadata = self._metadata_or_404(thread_id)
        async with self._service_for(metadata) as service:
            result = await service.resume_plan_review(
                thread_id=thread_id,
                decision=decision,
            )
        self._raise_decision_error(result, hash_kind="plan")
        return WorkflowReview(
            metadata=self._metadata_with_issue(metadata, result), result=result
        )

    async def submit_final_decision(
        self, *, thread_id: str, decision: FinalReviewDecision
    ) -> WorkflowReview:
        metadata = self._metadata_or_404(thread_id)
        async with self._service_for(metadata) as service:
            result = await service.resume_final_review(
                thread_id=thread_id,
                decision=decision,
            )
        self._raise_decision_error(result, hash_kind="patch")
        return WorkflowReview(
            metadata=self._metadata_with_issue(metadata, result), result=result
        )

    async def _build_context(self, chunks, issue: str):
        with SQLiteLexicalIndex() as lexical:
            lexical.rebuild(chunks)
            try:
                vector = ChromaVectorIndex(
                    OllamaEmbeddingProvider(self._embedding_settings)
                )
                await vector.rebuild(chunks)
                vector_retriever = vector
            except (EmbeddingProviderError, VectorRetrievalError, ChromaError):
                vector_retriever = _UnavailableVectorRetriever()
            retriever = HybridRetriever(lexical, vector_retriever)
            expansion = StructuralExpander(StructuralIndex(chunks))
            pipeline = StructuralContextPipeline(
                retriever,
                expansion,
                ContextPacker(),
                budget=self._context_budget,
            )
            return await pipeline.build_context(issue, top_k=self._retrieval_top_k)

    @asynccontextmanager
    async def _service_for(
        self, metadata: WorkflowMetadata
    ) -> AsyncIterator[PlanReviewService]:
        provider = OllamaProvider(self._generation_settings)
        workspaces = WorkspaceManager(
            canonical_repository=metadata.repository_path,
            workspace_root=self._root / "workspaces",
        )
        patch_service = ApprovedPatchService(
            patcher=StructuredPatcher(provider),
            workspace_manager=workspaces,
        )
        test_service = ApprovedPatchTestService(
            workspace_manager=workspaces,
            snapshot_manager=DisposableTestSnapshotManager(
                workspace_manager=workspaces,
                snapshot_root=self._root / "test-snapshots",
            ),
            runner=DockerTestRunner(),
            result_store=TestResultStore(self._root / "test-results"),
        )
        critic_service = CriticService(
            StructuredCritic(provider),
            CriticAssessmentStore(self._root / "critic-assessments"),
        )
        exporter = PatchExporter(
            export_root=self._root / "exports",
            workspace_manager=workspaces,
        )
        async with open_sqlite_plan_review_service(
            planner=StructuredPlanner(provider),
            checkpoint_path=self._root / "workflow-checkpoints.sqlite3",
            patch_service=patch_service,
            test_service=test_service,
            test_request=TestRunRequest(),
            critic_service=critic_service,
            patch_exporter=exporter,
        ) as service:
            yield service

    def _metadata_or_404(self, thread_id: str) -> WorkflowMetadata:
        metadata = self._threads.get(thread_id)
        if metadata is None:
            raise WorkflowApplicationError(
                "workflow_not_found", "Workflow was not found.", status_code=404
            )
        return metadata

    @staticmethod
    def _metadata_with_issue(
        metadata: WorkflowMetadata, result: PlanReviewResult
    ) -> WorkflowMetadata:
        return WorkflowMetadata(
            thread_id=metadata.thread_id,
            repository_path=metadata.repository_path,
            issue=result.issue_text or "Issue unavailable",
        )

    @staticmethod
    def _raise_decision_error(
        result: PlanReviewResult, *, hash_kind: str
    ) -> None:
        if result.status is not WorkflowStatus.VALIDATION_FAILED:
            return
        message = result.error.message if result.error else "Decision was not accepted."
        if f"{hash_kind} hash" in message:
            code = f"stale_{hash_kind}_hash"
            safe_message = (
                f"The displayed {hash_kind} hash is stale. Refresh and review "
                "the current workflow before deciding again."
            )
        else:
            code = "invalid_transition"
            safe_message = "This workflow is not waiting for that decision."
        raise WorkflowApplicationError(code, safe_message, status_code=409)


class _UnavailableVectorRetriever:
    async def search_vector(self, query: str, *, k: int = 10):
        del query, k
        raise VectorRetrievalError(
            "dense retrieval was unavailable; lexical evidence was used"
        )


__all__ = [
    "LocalWorkflowApplication",
    "WorkflowApplication",
    "WorkflowApplicationError",
    "WorkflowMetadata",
    "WorkflowReview",
    "WorkflowThreadIndex",
]
