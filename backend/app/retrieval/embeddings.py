"""Provider-neutral embeddings with a deterministic local fallback for tests."""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

import httpx

from ..ai.provider import AIProviderError
from ..core.config import Settings


class EmbeddingProvider(ABC):
    model: str = "unknown"
    dimension: int = 0
    version: str = "v1"

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed source texts without exposing provider-specific SDKs."""

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """Embed one retrieval query."""


class UnavailableEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, model: str = "unavailable", dimension: int = 0, version: str = "v1") -> None:
        self.model = model
        self.dimension = dimension
        self.version = version

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise AIProviderError("Embedding provider credentials are unavailable.", retryable=False)

    async def embed_query(self, query: str) -> list[float]:
        raise AIProviderError("Embedding provider credentials are unavailable.", retryable=False)


class HashEmbeddingProvider(EmbeddingProvider):
    """Stable feature-hash vectors; useful for deterministic local semantic tests."""

    def __init__(self, *, dimension: int = 64, model: str = "hash-v1", version: str = "v1") -> None:
        self.model = model
        self.dimension = max(8, dimension)
        self.version = version

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        tokens = re.findall(r"[A-Za-z0-9]+(?:[-_/+.][A-Za-z0-9]+)*", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 else -1.0
            values[index] += sign
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values] if norm else values


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Genuine local embeddings served by Ollama's native ``/api/embed`` API.

    Ollama does not require an API key on loopback.  PaperLens still sends a
    configurable local sentinel when one is supplied so the same adapter can
    be used behind a local proxy without ever requiring a hosted credential.
    """

    def __init__(
        self,
        *,
        model: str,
        dimension: int = 0,
        version: str = "ollama-v1",
        base_url: str = "http://127.0.0.1:11434",
        api_key: str | None = None,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
        batch_size: int = 64,
    ) -> None:
        self.model = model
        self.dimension = max(0, int(dimension))
        self.version = version
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = httpx.Timeout(timeout)
        self.transport = transport
        self.batch_size = max(1, int(batch_size))

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > self.batch_size:
            vectors: list[list[float]] = []
            for start in range(0, len(texts), self.batch_size):
                vectors.extend(await self._embed_batch(texts[start:start + self.batch_size]))
            return vectors
        return await self._embed_batch(texts)

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = await client.post("/api/embed", json={"model": self.model, "input": texts})
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code == 429 or status_code >= 500 or status_code == 408
            code = "RATE_LIMIT" if status_code == 429 else "TIMEOUT" if status_code == 408 else "UNAVAILABLE" if retryable else "INVALID_RESPONSE"
            raise AIProviderError("The local Ollama embedding request failed.", retryable=retryable, code=code) from exc
        except httpx.TimeoutException as exc:
            raise AIProviderError("The local Ollama embedding request timed out.", code="TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise AIProviderError("The local Ollama embedding service is unavailable.", code="UNAVAILABLE") from exc
        except (TypeError, ValueError) as exc:
            raise AIProviderError("The local Ollama embedding response was invalid.", retryable=False, code="INVALID_RESPONSE") from exc

        raw_vectors = body.get("embeddings") if isinstance(body, dict) else None
        if not isinstance(raw_vectors, list) or len(raw_vectors) != len(texts):
            raise AIProviderError("The local Ollama embedding response was invalid.", retryable=False, code="INVALID_RESPONSE")
        vectors: list[list[float]] = []
        for raw_vector in raw_vectors:
            if not isinstance(raw_vector, list) or not raw_vector:
                raise AIProviderError("The local Ollama embedding response was invalid.", retryable=False, code="INVALID_RESPONSE")
            try:
                vector = [float(value) for value in raw_vector]
            except (TypeError, ValueError) as exc:
                raise AIProviderError("The local Ollama embedding response was invalid.", retryable=False, code="INVALID_RESPONSE") from exc
            if any(not math.isfinite(value) for value in vector):
                raise AIProviderError("The local Ollama embedding response was invalid.", retryable=False, code="INVALID_RESPONSE")
            norm = math.sqrt(sum(value * value for value in vector))
            if norm <= 0:
                raise AIProviderError("The local Ollama embedding response was invalid.", retryable=False, code="INVALID_RESPONSE")
            if self.dimension and len(vector) != self.dimension:
                raise AIProviderError("The local Ollama embedding dimension did not match configuration.", retryable=False, code="INVALID_RESPONSE")
            self.dimension = len(vector)
            vectors.append([value / norm for value in vector])
        return vectors

    async def embed_query(self, query: str) -> list[float]:
        vectors = await self.embed_texts([query])
        return vectors[0]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider = settings.embedding_provider.lower().strip()
    if provider in {"hash", "local", "mock"}:
        return HashEmbeddingProvider(
            dimension=settings.embedding_dimension,
            model=settings.embedding_model,
            version=settings.embedding_version,
        )
    if provider in {"ollama", "ollama_local", "local_ollama"}:
        return OllamaEmbeddingProvider(
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
            version=settings.embedding_version,
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            timeout=settings.ai_request_timeout,
        )
    return UnavailableEmbeddingProvider(
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
        version=settings.embedding_version,
    )
