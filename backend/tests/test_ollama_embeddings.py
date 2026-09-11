import asyncio
from collections.abc import Callable
import json

import httpx
import pytest

from app.config import OllamaEmbeddingSettings
from app.providers import (
    EmbeddingInputError,
    EmbeddingResponseError,
    EmbeddingUnavailableError,
    OllamaEmbeddingProvider,
)


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OllamaEmbeddingProvider:
    settings = OllamaEmbeddingSettings(
        ollama_base_url="http://ollama.test",
        ollama_embedding_model="embeddinggemma",
        ollama_embedding_timeout_seconds=1.0,
    )
    return OllamaEmbeddingProvider(
        settings,
        transport=httpx.MockTransport(handler),
    )


def test_batch_provider_sends_api_embed_payload_and_preserves_cardinality() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://ollama.test/api/embed"
        assert json.loads(request.content) == {
            "model": "embeddinggemma",
            "input": ["first", "second"],
            "truncate": False,
        }
        return httpx.Response(
            200,
            json={
                "model": "embeddinggemma",
                "embeddings": [[1, 0, 0], [0, 1, 0]],
                "total_duration": 10,
            },
        )

    provider = _provider(handler)
    result = asyncio.run(provider.embed_batch(("first", "second")))

    assert provider.provider_name == "ollama"
    assert provider.model == "embeddinggemma"
    assert result == ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def test_single_embedding_uses_the_batch_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["input"] == ["one"]
        return httpx.Response(200, json={"embeddings": [[0.25, 0.75]]})

    result = asyncio.run(_provider(handler).embed_text("one"))

    assert result == (0.25, 0.75)


def test_batch_rejects_a_bare_string_instead_of_embedding_characters() -> None:
    with pytest.raises(EmbeddingInputError, match="sequence of strings"):
        asyncio.run(_provider(lambda request: httpx.Response(500)).embed_batch("text"))


def test_ollama_embedding_unavailable_is_clear() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(
        EmbeddingUnavailableError,
        match="Ollama embeddings are unavailable at http://ollama.test",
    ):
        asyncio.run(_provider(handler).embed_text("query"))


def test_oversized_input_error_is_surfaced_without_truncation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["truncate"] is False
        return httpx.Response(
            400,
            json={"error": "input length exceeds the model context window"},
        )

    with pytest.raises(EmbeddingResponseError, match="HTTP 400"):
        asyncio.run(_provider(handler).embed_text("oversized source text"))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"model": "embeddinggemma"}),
        httpx.Response(200, json={"embeddings": [[]]}),
        httpx.Response(200, json={"embeddings": [[True, 1.0]]}),
        httpx.Response(
            200,
            content=b'{"embeddings":[[NaN,1.0]]}',
            headers={"content-type": "application/json"},
        ),
    ],
)
def test_malformed_embedding_responses_are_rejected(
    response: httpx.Response,
) -> None:
    with pytest.raises(EmbeddingResponseError):
        asyncio.run(_provider(lambda request: response).embed_text("query"))


def test_embedding_count_must_match_batch_input() -> None:
    provider = _provider(
        lambda request: httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
    )

    with pytest.raises(
        EmbeddingResponseError,
        match="count did not match input count",
    ):
        asyncio.run(provider.embed_batch(("first", "second")))


def test_inconsistent_embedding_dimensions_are_rejected() -> None:
    provider = _provider(
        lambda request: httpx.Response(
            200,
            json={"embeddings": [[1.0, 0.0], [1.0, 0.0, 0.0]]},
        )
    )

    with pytest.raises(
        EmbeddingResponseError,
        match="inconsistent dimensions",
    ):
        asyncio.run(provider.embed_batch(("first", "second")))
