"""M0 HTTP endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_inference_provider
from app.models.inference import HealthResponse, InferenceRequest, InferenceResponse
from app.providers.base import (
    InferenceProvider,
    InferenceResponseError,
    InferenceUnavailableError,
)


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

