"""Local HTTP boundaries for health, inference, and bounded repair review."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.api.workflow_models import (
    CreateWorkflowRequest,
    FinalDecisionRequest,
    PlanDecisionRequest,
    WorkflowView,
)
from app.dependencies import get_inference_provider, get_workflow_application
from app.exporting import FinalReviewDecision
from app.models.inference import HealthResponse, InferenceRequest, InferenceResponse
from app.providers.base import (
    InferenceProvider,
    InferenceResponseError,
    InferenceUnavailableError,
)
from app.workflow.application import WorkflowApplication, WorkflowApplicationError
from app.workflow.models import ApprovalDecision


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="repopilot-backend")


@router.post("/api/inference", response_model=InferenceResponse)
async def inference(
    request: InferenceRequest,
    provider: Annotated[InferenceProvider, Depends(get_inference_provider)],
) -> InferenceResponse:
    """Prove M0 connectivity to local inference; this is not the future agent API."""

    try:
        generated_text = await provider.generate(request.prompt)
    except InferenceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except InferenceResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return InferenceResponse(model=provider.model, response=generated_text)


@router.post(
    "/api/workflows",
    response_model=WorkflowView,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow(
    request: CreateWorkflowRequest,
    workflows: Annotated[WorkflowApplication, Depends(get_workflow_application)],
) -> WorkflowView:
    try:
        review = await workflows.create_workflow(
            repository_path=request.repository_path,
            issue=request.issue,
            thread_id=request.thread_id,
        )
        return WorkflowView.from_review(review)
    except WorkflowApplicationError as exc:
        _raise_workflow_http_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "workflow_internal_error",
                "message": "The workflow request failed safely.",
            },
        ) from exc


@router.get("/api/workflows/{thread_id}", response_model=WorkflowView)
async def get_workflow(
    thread_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    workflows: Annotated[WorkflowApplication, Depends(get_workflow_application)],
) -> WorkflowView:
    try:
        review = await workflows.get_workflow(thread_id=thread_id)
        return WorkflowView.from_review(review)
    except WorkflowApplicationError as exc:
        _raise_workflow_http_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "workflow_internal_error",
                "message": "The workflow state could not be read safely.",
            },
        ) from exc


@router.post(
    "/api/workflows/{thread_id}/plan-decision",
    response_model=WorkflowView,
)
async def submit_plan_decision(
    thread_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    request: PlanDecisionRequest,
    workflows: Annotated[WorkflowApplication, Depends(get_workflow_application)],
) -> WorkflowView:
    try:
        review = await workflows.submit_plan_decision(
            thread_id=thread_id,
            decision=ApprovalDecision.model_validate(request.model_dump()),
        )
        return WorkflowView.from_review(review)
    except WorkflowApplicationError as exc:
        _raise_workflow_http_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "workflow_internal_error",
                "message": "The plan decision failed safely.",
            },
        ) from exc


@router.post(
    "/api/workflows/{thread_id}/final-decision",
    response_model=WorkflowView,
)
async def submit_final_decision(
    thread_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")],
    request: FinalDecisionRequest,
    workflows: Annotated[WorkflowApplication, Depends(get_workflow_application)],
) -> WorkflowView:
    try:
        review = await workflows.submit_final_decision(
            thread_id=thread_id,
            decision=FinalReviewDecision.model_validate(request.model_dump()),
        )
        return WorkflowView.from_review(review)
    except WorkflowApplicationError as exc:
        _raise_workflow_http_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "workflow_internal_error",
                "message": "The final decision failed safely.",
            },
        ) from exc


def _raise_workflow_http_error(error: WorkflowApplicationError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error
