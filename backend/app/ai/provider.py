"""AI provider abstraction and OpenAI-compatible adapter."""

from __future__ import annotations

import json
import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..core.config import Settings

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("paperlens.provider")


class AIProviderError(Exception):
    """Safe provider failure without credentials or response contents."""

    def __init__(self, message: str, *, retryable: bool = True, code: str = "UNAVAILABLE") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class AIProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """Generate plain text from a provider."""

    @abstractmethod
    async def generate_structured(self, prompt: str, schema: type[T]) -> T:
        """Generate and validate one Pydantic object."""


class OpenAICompatibleProvider(AIProvider):
    """Adapter for OpenAI-compatible chat-completions APIs."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str,
        timeout: float = 60.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout)
        self.max_retries = max(0, min(max_retries, 3))
        self.transport = transport

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        if not self.api_key:
            raise AIProviderError("AI provider credentials are unavailable.", retryable=False, code="AUTHENTICATION")
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty provider content")
                return content
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code == 429 or status_code >= 500 or status_code == 408
            code = "RATE_LIMIT" if status_code == 429 else "TIMEOUT" if status_code == 408 else "UNAVAILABLE" if retryable else "AUTHENTICATION" if status_code in {401, 403} else "INVALID_RESPONSE"
            raise AIProviderError("The AI provider request failed.", retryable=retryable, code=code) from exc
        except httpx.TimeoutException as exc:
            raise AIProviderError("The AI provider request timed out.", code="TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise AIProviderError("The AI provider is unavailable.", code="UNAVAILABLE") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AIProviderError("The AI provider returned an invalid response.", retryable=False, code="INVALID_RESPONSE") from exc

    async def generate_structured(self, prompt: str, schema: type[T]) -> T:
        last_error: Exception | None = None
        request_prompt = prompt
        for attempt in range(self.max_retries + 1):
            try:
                raw = await self.generate(request_prompt)
                return schema.model_validate(_decode_json(raw))
            except AIProviderError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
                if attempt < self.max_retries:
                    logger.warning("provider_retry code=%s attempt=%d", exc.code, attempt + 1)
                    await asyncio.sleep(min(4.0, (2**attempt) * 0.25 + random.uniform(0, 0.1)))
                    request_prompt = (
                        f"{prompt}\n\nThe provider request failed transiently. Retry and return only valid JSON "
                        f"matching this schema:\n{json.dumps(schema.model_json_schema())}"
                    )
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    logger.warning("provider_retry code=INVALID_RESPONSE attempt=%d", attempt + 1)
                    await asyncio.sleep(min(4.0, (2**attempt) * 0.25 + random.uniform(0, 0.1)))
                    request_prompt = (
                        f"{prompt}\n\nYour previous output failed schema validation. "
                        f"Return only valid JSON matching this schema:\n{json.dumps(schema.model_json_schema())}"
                    )
        raise AIProviderError("The AI provider returned invalid structured output.", retryable=False, code="INVALID_RESPONSE") from last_error


class UnavailableAIProvider(AIProvider):
    """Explicit provider used when extraction is requested without configuration."""

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        raise AIProviderError("AI provider credentials are unavailable.", retryable=False, code="AUTHENTICATION")

    async def generate_structured(self, prompt: str, schema: type[T]) -> T:
        raise AIProviderError("AI provider credentials are unavailable.", retryable=False, code="AUTHENTICATION")


def create_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider.lower() in {"none", "disabled"}:
        return UnavailableAIProvider()
    return OpenAICompatibleProvider(
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        base_url=settings.ai_base_url,
        timeout=settings.ai_request_timeout,
        max_retries=settings.ai_max_retries,
    )


def _decode_json(raw: str) -> Any:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").removeprefix("json").removesuffix("```").strip()
    return json.loads(cleaned)
