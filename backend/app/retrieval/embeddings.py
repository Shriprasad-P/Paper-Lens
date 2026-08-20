"""Provider-neutral embeddings with a deterministic local fallback for tests."""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

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
    return UnavailableEmbeddingProvider(
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
        version=settings.embedding_version,
    )
