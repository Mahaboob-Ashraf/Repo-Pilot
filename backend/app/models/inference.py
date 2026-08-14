"""Schemas for the M0 inference connectivity endpoint."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_blank(cls, value: str) -> str:
        prompt = value.strip()
        if not prompt:
            raise ValueError("prompt must not be blank")
        return prompt


class InferenceResponse(BaseModel):
    model: str
    response: str


class HealthResponse(BaseModel):
    status: str
    service: str

