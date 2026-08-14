"""Focused tests for the M0 backend endpoints and Ollama boundary."""

from collections.abc import Callable, Iterator
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_inference_provider
from app.main import app
from app.providers.ollama import OllamaProvider


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def use_mock_ollama(handler: Callable[[httpx.Request], httpx.Response]) -> None:
    settings = Settings(
        ollama_base_url="http://ollama.test",
        ollama_model="gemma4:e4b-it-qat",
        ollama_timeout_seconds=1.0,
    )
    provider = OllamaProvider(settings, transport=httpx.MockTransport(handler))
    app.dependency_overrides[get_inference_provider] = lambda: provider


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "repopilot-backend",
    }


def test_inference_returns_only_generated_response(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://ollama.test/api/generate"
        assert json.loads(request.content) == {
            "model": "gemma4:e4b-it-qat",
            "prompt": "Answer briefly.",
            "stream": False,
        }
        return httpx.Response(
            200,
            json={
                "model": "gemma4:e4b-it-qat",
                "created_at": "2026-08-14T00:00:00Z",
                "thinking": "internal reasoning that must stay private",
                "response": "A brief answer.",
                "done": True,
                "done_reason": "stop",
                "eval_count": 4,
            },
        )

    use_mock_ollama(handler)

    response = client.post("/api/inference", json={"prompt": "Answer briefly."})

    assert response.status_code == 200
    assert response.json() == {
        "model": "gemma4:e4b-it-qat",
        "response": "A brief answer.",
    }


def test_inference_reports_ollama_unavailable(client: TestClient) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    use_mock_ollama(handler)

    response = client.post("/api/inference", json={"prompt": "Hello"})

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Ollama is unavailable at http://ollama.test"
    }


@pytest.mark.parametrize("prompt", ["", "   "])
def test_inference_rejects_blank_prompt(
    client: TestClient, prompt: str
) -> None:
    response = client.post("/api/inference", json={"prompt": prompt})

    assert response.status_code == 422

