"""FastAPI dependency wiring."""

from functools import lru_cache

from app.config import Settings
from app.providers.base import InferenceProvider
from app.providers.factory import build_generation_provider
from app.workflow.application import LocalWorkflowApplication, WorkflowApplication


@lru_cache
def get_settings() -> Settings:
    return Settings.from_environment()


def get_inference_provider() -> InferenceProvider:
    return build_generation_provider(get_settings())


@lru_cache
def get_workflow_application() -> WorkflowApplication:
    return LocalWorkflowApplication.from_environment()
